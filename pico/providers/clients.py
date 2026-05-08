"""模型后端适配层。

runtime 只关心一件事：给我一个 prompt，我拿回一段文本。
不同 provider 在 HTTP 接口、响应结构、是否支持 prompt cache 上都有差异，
这些差异都在这里被抹平成统一的 complete() 接口。
"""

import json
import socket
import time
from http.client import RemoteDisconnected
import urllib.error
import urllib.request

OPENAI_COMPATIBLE_USER_AGENT = "pico/0.1"


class FakeModelClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []
        self.supports_prompt_cache = False
        self.last_completion_metadata = {}

    def complete(self, prompt, max_new_tokens, **kwargs):
        self.prompts.append(prompt)
        if not getattr(self, "last_completion_metadata", None):
            self.last_completion_metadata = {}
        if not self.outputs:
            raise RuntimeError("fake model ran out of outputs")
        return self.outputs.pop(0)


class OllamaModelClient:
    def __init__(self, model, host, temperature, top_p, timeout):
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.top_p = top_p
        self.timeout = timeout
        self.supports_prompt_cache = False
        self.last_completion_metadata = {}

    def complete(self, prompt, max_new_tokens, **kwargs):
        # Ollama 当前不支持我们这里接入的 prompt cache 语义，
        # 所以 runtime 传下来的缓存参数会被忽略。
        self.last_completion_metadata = {}
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "raw": False,
            "think": False,
            "options": {
                "num_predict": max_new_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
        }
        request = urllib.request.Request(
            self.host + "/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama request failed with HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise RuntimeError(
                "Could not reach Ollama.\n"
                "Make sure `ollama serve` is running and the model is available.\n"
                f"Host: {self.host}\n"
                f"Model: {self.model}\n"
                f"Timeout: {self.timeout}s"
            ) from exc

        if data.get("error"):
            raise RuntimeError(f"Ollama error: {data['error']}")
        return data.get("response", "")


def _normalize_versioned_base_url(base_url):
    base = str(base_url).rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return base


def _post_json(url, payload, headers, timeout):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body_text = response.read().decode("utf-8")
        response_headers = getattr(response, "headers", {}) or {}
    return body_text, response_headers.get("Content-Type", "")


def _extract_openai_text(data):
    if data.get("output_text"):
        return data["output_text"]

    for item in data.get("output", []):
        for content in item.get("content", []):
            if isinstance(content, dict):
                text = content.get("text")
                if text:
                    return text

    choices = data.get("choices", [])
    if choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        return text

    return ""


def _extract_openai_response_from_sse(body_text):
    last_response = None
    deltas = []
    for line in body_text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        response = event.get("response")
        if isinstance(response, dict):
            last_response = response
            if event.get("type") == "response.completed":
                text = _extract_openai_text(response)
                if text:
                    return text, response
        event_type = event.get("type", "")
        if event_type == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str):
                deltas.append(delta)
        elif event_type == "response.output_text.done":
            text = event.get("text")
            if isinstance(text, str) and text:
                return text, last_response or {}
        else:
            text = _extract_openai_text(event)
            if text:
                return text, event
    if deltas:
        return "".join(deltas), last_response or {}
    if isinstance(last_response, dict):
        return _extract_openai_text(last_response), last_response
    return "", {}


def _extract_usage_cache_details(data):
    # 把不同 OpenAI-compatible 返回里的 usage 字段整理成统一结构，
    # 让 runtime/trace/report 不需要关心 provider 细节。
    usage = data.get("usage") or {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    input_details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    cached_tokens = int(input_details.get("cached_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": usage.get("total_tokens"),
        "cached_tokens": cached_tokens,
        "cache_hit": cached_tokens > 0,
    }


def _extract_openai_finish_reason(data):
    choices = data.get("choices") or []
    if choices:
        reason = choices[0].get("finish_reason")
        if reason:
            return reason
    incomplete = data.get("incomplete_details") or {}
    reason = incomplete.get("reason")
    if reason:
        return "length" if reason in {"max_output_tokens", "max_tokens"} else reason
    status = data.get("status")
    if status == "incomplete":
        return "length"
    return "stop"


def _sdk_attr_or_item(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _extract_openai_sdk_usage(response):
    usage = _sdk_attr_or_item(response, "usage", None)
    if usage is None:
        return {}
    input_tokens = _sdk_attr_or_item(usage, "input_tokens", None)
    if input_tokens is None:
        input_tokens = _sdk_attr_or_item(usage, "prompt_tokens", None)
    output_tokens = _sdk_attr_or_item(usage, "output_tokens", None)
    if output_tokens is None:
        output_tokens = _sdk_attr_or_item(usage, "completion_tokens", None)
    total_tokens = _sdk_attr_or_item(usage, "total_tokens", None)
    input_details = _sdk_attr_or_item(usage, "input_tokens_details", None)
    if input_details is None:
        input_details = _sdk_attr_or_item(usage, "prompt_tokens_details", None)
    cached_tokens = int(_sdk_attr_or_item(input_details or {}, "cached_tokens", 0) or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "cache_hit": cached_tokens > 0,
    }


def _extract_openai_sdk_response_text(response):
    output_text = _sdk_attr_or_item(response, "output_text", "")
    if isinstance(output_text, str) and output_text:
        return output_text
    for item in _sdk_attr_or_item(response, "output", []) or []:
        for content in _sdk_attr_or_item(item, "content", []) or []:
            text = _sdk_attr_or_item(content, "text", "")
            if isinstance(text, str) and text:
                return text
    return ""


def _extract_openai_sdk_chat_text(response):
    choices = _sdk_attr_or_item(response, "choices", []) or []
    if not choices:
        return ""
    message = _sdk_attr_or_item(choices[0], "message", None)
    content = _sdk_attr_or_item(message or {}, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for item in content:
            text = _sdk_attr_or_item(item, "text", "")
            if isinstance(text, str) and text:
                return text
    return ""


def _extract_openai_sdk_finish_reason(response):
    choices = _sdk_attr_or_item(response, "choices", []) or []
    if choices:
        reason = _sdk_attr_or_item(choices[0], "finish_reason", "")
        if reason:
            return reason
    incomplete = _sdk_attr_or_item(response, "incomplete_details", None)
    reason = _sdk_attr_or_item(incomplete or {}, "reason", "")
    if reason:
        return "length" if reason in {"max_output_tokens", "max_tokens"} else reason
    status = _sdk_attr_or_item(response, "status", "")
    if status == "incomplete":
        return "length"
    return "stop"


class OpenAICompatibleModelClient:
    def __init__(self, model, base_url, api_key, temperature, timeout, api_mode="auto"):
        self.model = model
        self.base_url = _normalize_versioned_base_url(base_url)
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.api_mode = api_mode
        # 当前只在明确支持 prompt cache 语义的后端上启用这条链路，
        # 避免对不支持的后端传一个“看起来统一、其实没意义”的伪参数。
        self.supports_prompt_cache = any(host in self.base_url for host in ("openai.com", "right.codes"))
        self.last_completion_metadata = {}

    def complete(self, prompt, max_new_tokens, prompt_cache_key=None, prompt_cache_retention=None):
        """向 OpenAI-compatible `/responses` 接口发起一次模型调用。

        为什么存在：
        runtime 不应该知道 HTTP 细节、SSE 细节、usage 字段长什么样，
        更不应该自己去判断 prompt cache 参数要不要带。这个函数把这些后端
        细节都包起来，对上层暴露统一的 `complete()` 行为。

        输入 / 输出：
        - 输入：完整 prompt、最大输出 token，以及可选的 prompt cache 参数
        - 输出：模型最终文本；同时把 usage / cached_tokens 等元数据写进
          `self.last_completion_metadata`

        在 agent 链路里的位置：
        它位于 `Pico.ask()` 的模型调用阶段，是稳定前缀缓存复用链路真正
        落到 provider API 的地方。
        """
        self.last_completion_metadata = {}
        if self._uses_chat_completions_by_default():
            return self._complete_chat_completions(prompt, max_new_tokens)

        input_payload = prompt
        if self.supports_prompt_cache and prompt_cache_key:
            input_payload = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        }
                    ],
                }
            ]
        payload = {
            "model": self.model,
            "input": input_payload,
            "max_output_tokens": max_new_tokens,
            "stream": False,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        # runtime 传入的是“稳定前缀”的签名，而不是整段 prompt 的签名。
        # 这样缓存复用针对的是稳定段，不会因为动态 history 每轮变化而失效。
        if self.supports_prompt_cache and prompt_cache_key:
            payload["prompt_cache_key"] = prompt_cache_key
        if self.supports_prompt_cache and prompt_cache_retention:
            payload["prompt_cache_retention"] = prompt_cache_retention

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": OPENAI_COMPATIBLE_USER_AGENT,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        attempts = 3
        for attempt in range(attempts):
            try:
                body_text, content_type = _post_json(self.base_url + "/responses", payload, headers, self.timeout)
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code >= 500 and attempt < attempts - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                if self._should_fallback_to_chat_completions(exc.code, body):
                    return self._complete_chat_completions(prompt, max_new_tokens)
                raise RuntimeError(f"OpenAI-compatible request failed with HTTP {exc.code}: {body}") from exc
            except (urllib.error.URLError, RemoteDisconnected, TimeoutError, socket.timeout) as exc:
                if attempt < attempts - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(
                    "Could not reach the OpenAI-compatible backend.\n"
                    f"Base URL: {self.base_url}\n"
                    f"Model: {self.model}\n"
                    f"Timeout: {self.timeout}s"
                ) from exc

        # 有些兼容后端返回普通 JSON，有些返回 SSE。
        # 这里两种都接住，并尽量统一抽取文本和 usage/cache 元数据。
        if content_type.startswith("text/event-stream") or body_text.lstrip().startswith("data:"):
            text, response_data = _extract_openai_response_from_sse(body_text)
            if isinstance(response_data, dict) and response_data:
                # 这些元数据会一路传回 runtime，进入 trace 和 report，
                # 用来观察 prompt cache 是否真的命中。
                self.last_completion_metadata = {
                    "prompt_cache_supported": self.supports_prompt_cache,
                    "prompt_cache_key": prompt_cache_key,
                    "prompt_cache_retention": prompt_cache_retention,
                    "finish_reason": _extract_openai_finish_reason(response_data),
                    **_extract_usage_cache_details(response_data),
                }
            if text:
                return text
            raise RuntimeError("OpenAI-compatible error: could not extract text from event stream response")

        try:
            data = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "OpenAI-compatible error: backend returned non-JSON content that could not be parsed"
            ) from exc
        if data.get("error"):
            raise RuntimeError(f"OpenAI-compatible error: {data['error']}")
        self.last_completion_metadata = {
            "prompt_cache_supported": self.supports_prompt_cache,
            "prompt_cache_key": prompt_cache_key,
            "prompt_cache_retention": prompt_cache_retention,
            "finish_reason": _extract_openai_finish_reason(data),
            **_extract_usage_cache_details(data),
        }
        return _extract_openai_text(data)

    def _should_fallback_to_chat_completions(self, code, body):
        if code < 500:
            return False
        return "bad_response_body" in str(body)

    def _uses_chat_completions_by_default(self):
        if self.api_mode == "chat":
            return True
        if self.api_mode == "responses":
            return False
        return "right.codes/codex" in self.base_url

    def _complete_chat_completions(self, prompt, max_new_tokens):
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_new_tokens,
            "stream": False,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": OPENAI_COMPATIBLE_USER_AGENT,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            body_text, _content_type = _post_json(self.base_url + "/chat/completions", payload, headers, self.timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI-compatible chat fallback failed with HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, RemoteDisconnected, TimeoutError, socket.timeout) as exc:
            raise RuntimeError(
                "Could not reach the OpenAI-compatible chat fallback.\n"
                f"Base URL: {self.base_url}\n"
                f"Model: {self.model}\n"
                f"Timeout: {self.timeout}s"
            ) from exc

        try:
            data = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenAI-compatible chat fallback returned non-JSON content") from exc
        if data.get("error"):
            raise RuntimeError(f"OpenAI-compatible chat fallback error: {data['error']}")
        text = _extract_openai_text(data)
        self.last_completion_metadata = {
            "provider_fallback": "chat_completions",
            "finish_reason": _extract_openai_finish_reason(data),
            **_extract_usage_cache_details(data),
        }
        if text:
            return text
        raise RuntimeError("OpenAI-compatible chat fallback error: could not extract text from response")


class OpenAISDKModelClient:
    def __init__(self, model, base_url, api_key, temperature, timeout, api_mode="auto"):
        self.model = model
        self.base_url = _normalize_versioned_base_url(base_url)
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.api_mode = api_mode
        self.supports_prompt_cache = any(host in self.base_url for host in ("openai.com", "right.codes"))
        self.last_completion_metadata = {}
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("OpenAI SDK is not installed. Install the `openai` package.") from exc
        self.client = OpenAI(api_key=api_key, base_url=self.base_url, timeout=timeout)

    def complete(self, prompt, max_new_tokens, prompt_cache_key=None, prompt_cache_retention=None):
        self.last_completion_metadata = {}
        if self._uses_chat_completions_by_default():
            return self._complete_chat_completions(prompt, max_new_tokens)
        return self._complete_responses(prompt, max_new_tokens, prompt_cache_key, prompt_cache_retention)

    def _uses_chat_completions_by_default(self):
        if self.api_mode == "chat":
            return True
        if self.api_mode == "responses":
            return False
        return "right.codes/codex" in self.base_url

    def _complete_responses(self, prompt, max_new_tokens, prompt_cache_key, prompt_cache_retention):
        input_payload = prompt
        if self.supports_prompt_cache and prompt_cache_key:
            input_payload = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        }
                    ],
                }
            ]
        kwargs = {
            "model": self.model,
            "input": input_payload,
            "max_output_tokens": max_new_tokens,
            "stream": False,
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        extra_body = {}
        if self.supports_prompt_cache and prompt_cache_key:
            extra_body["prompt_cache_key"] = prompt_cache_key
        if self.supports_prompt_cache and prompt_cache_retention:
            extra_body["prompt_cache_retention"] = prompt_cache_retention
        if extra_body:
            kwargs["extra_body"] = extra_body
        try:
            response = self.client.responses.create(**kwargs)
        except Exception as exc:
            raise RuntimeError(
                "OpenAI SDK request failed.\n"
                f"Base URL: {self.base_url}\n"
                f"Model: {self.model}\n"
                f"Transport: responses\n"
                f"Cause: {exc}"
            ) from exc
        text = _extract_openai_sdk_response_text(response)
        self.last_completion_metadata = {
            "provider_transport": "openai_sdk_responses",
            "prompt_cache_supported": self.supports_prompt_cache,
            "prompt_cache_key": prompt_cache_key,
            "prompt_cache_retention": prompt_cache_retention,
            "finish_reason": _extract_openai_sdk_finish_reason(response),
            **_extract_openai_sdk_usage(response),
        }
        if text:
            return text
        raise RuntimeError("OpenAI SDK responses error: could not extract text from response")

    def _complete_chat_completions(self, prompt, max_new_tokens):
        kwargs = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_new_tokens,
            "stream": False,
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise RuntimeError(
                "OpenAI SDK request failed.\n"
                f"Base URL: {self.base_url}\n"
                f"Model: {self.model}\n"
                f"Transport: chat_completions\n"
                f"Cause: {exc}"
            ) from exc
        text = _extract_openai_sdk_chat_text(response)
        self.last_completion_metadata = {
            "provider_transport": "openai_sdk_chat",
            "provider_fallback": "chat_completions",
            "finish_reason": _extract_openai_sdk_finish_reason(response),
            **_extract_openai_sdk_usage(response),
        }
        if text:
            return text
        raise RuntimeError("OpenAI SDK chat completions error: could not extract text from response")


def _extract_anthropic_text(data):
    for item in data.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text:
                return text
    return ""


def _extract_anthropic_sdk_text(message):
    for item in _sdk_attr_or_item(message, "content", []) or []:
        item_type = _sdk_attr_or_item(item, "type", "")
        text = _sdk_attr_or_item(item, "text", "")
        if item_type == "text" and isinstance(text, str) and text:
            return text
    return ""


def _extract_anthropic_sdk_usage(message):
    usage = _sdk_attr_or_item(message, "usage", None)
    if usage is None:
        return {}
    input_tokens = _sdk_attr_or_item(usage, "input_tokens", None)
    output_tokens = _sdk_attr_or_item(usage, "output_tokens", None)
    total = None
    if input_tokens is not None and output_tokens is not None:
        total = int(input_tokens) + int(output_tokens)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
    }


def _normalize_anthropic_stop_reason(reason):
    reason = str(reason or "")
    if reason == "max_tokens":
        return "length"
    return reason or "stop"


def _normalize_anthropic_sdk_base_url(base_url):
    base = str(base_url).rstrip("/")
    if base.endswith("/v1"):
        return base[:-3]
    return base


class AnthropicCompatibleModelClient:
    def __init__(self, model, base_url, api_key, temperature, timeout):
        self.model = model
        self.base_url = _normalize_versioned_base_url(base_url)
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.supports_prompt_cache = False
        self.last_completion_metadata = {}

    def complete(self, prompt, max_new_tokens, prompt_cache_key=None, prompt_cache_retention=None):
        # 为了保持统一接口，runtime 仍然会传缓存参数进来；
        # 这里只是显式丢弃，因为当前 Anthropic-compatible 路径没有接缓存复用。
        del prompt_cache_key, prompt_cache_retention
        self.last_completion_metadata = {}
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        }
                    ],
                }
            ],
            "max_tokens": max_new_tokens,
            "stream": False,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        attempts = 3
        for attempt in range(attempts):
            try:
                body_text, _content_type = _post_json(self.base_url + "/messages", payload, headers, self.timeout)
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code >= 500 and attempt < attempts - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Anthropic-compatible request failed with HTTP {exc.code}: {body}") from exc
            except (urllib.error.URLError, RemoteDisconnected, TimeoutError, socket.timeout) as exc:
                if attempt < attempts - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(
                    "Could not reach the Anthropic-compatible backend.\n"
                    f"Base URL: {self.base_url}\n"
                    f"Model: {self.model}\n"
                    f"Timeout: {self.timeout}s"
                ) from exc

        try:
            data = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Anthropic-compatible error: backend returned non-JSON content that could not be parsed"
            ) from exc
        if data.get("error"):
            raise RuntimeError(f"Anthropic-compatible error: {data['error']}")
        text = _extract_anthropic_text(data)
        self.last_completion_metadata = {
            "provider_transport": "anthropic_compatible",
            "finish_reason": _normalize_anthropic_stop_reason(data.get("stop_reason")),
            "stop_reason": data.get("stop_reason") or "",
            **_extract_usage_cache_details(data),
        }
        if text:
            return text
        raise RuntimeError("Anthropic-compatible error: could not extract text from response")


class AnthropicSDKModelClient:
    def __init__(self, model, base_url, api_key, temperature, timeout):
        self.model = model
        self.base_url = _normalize_anthropic_sdk_base_url(base_url)
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.supports_prompt_cache = False
        self.last_completion_metadata = {}
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError("Anthropic SDK is not installed. Install pico with the `anthropic` extra.") from exc
        self.client = Anthropic(api_key=api_key, base_url=self.base_url, timeout=timeout)

    def complete(self, prompt, max_new_tokens, prompt_cache_key=None, prompt_cache_retention=None):
        del prompt_cache_key, prompt_cache_retention
        self.last_completion_metadata = {}
        kwargs = {
            "model": self.model,
            "max_tokens": max_new_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        message = self.client.messages.create(**kwargs)
        text = _extract_anthropic_sdk_text(message)
        self.last_completion_metadata = {
            "provider_transport": "anthropic_sdk",
            "message_id": _sdk_attr_or_item(message, "id", ""),
            "finish_reason": _normalize_anthropic_stop_reason(_sdk_attr_or_item(message, "stop_reason", "")),
            "stop_reason": _sdk_attr_or_item(message, "stop_reason", ""),
            **_extract_anthropic_sdk_usage(message),
        }
        if text:
            return text
        raise RuntimeError("Anthropic SDK error: could not extract text from response")
