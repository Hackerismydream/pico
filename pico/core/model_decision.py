"""Parse model text into Pico runtime decisions."""

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelDecision:
    kind: str
    payload: Any
    parse_error_type: str = ""


class ModelDecisionAdapter:
    def parse(self, raw):
        kind, payload = parse_model_output(raw)
        return ModelDecision(kind=kind, payload=payload, parse_error_type=parse_error_type(kind, payload))


def parse_model_output(raw):
    raw = str(raw)
    if "<tool>" in raw and ("<final>" not in raw or raw.find("<tool>") < raw.find("<final>")):
        body = extract(raw, "tool")
        try:
            payload = json.loads(body)
        except Exception:
            return "retry", retry_notice("model returned malformed tool JSON")
        if not isinstance(payload, dict):
            return "retry", retry_notice("tool payload must be a JSON object")
        if not str(payload.get("name", "")).strip():
            return "retry", retry_notice("tool payload is missing a tool name")
        args = payload.get("args", {})
        if args is None:
            payload["args"] = {}
        elif not isinstance(args, dict):
            return "retry", retry_notice("tool args must be an object")
        return "tool", payload
    if "<tool" in raw and ("<final>" not in raw or raw.find("<tool") < raw.find("<final>")):
        payload = parse_xml_tool(raw)
        if payload is not None:
            return "tool", payload
        return "retry", retry_notice()
    if "<final>" in raw:
        final = extract(raw, "final").strip()
        if final:
            return "final", final
        return "retry", retry_notice("model returned an empty <final> answer")
    raw = raw.strip()
    if raw:
        return "final", raw
    return "retry", retry_notice("model returned an empty response")


def parse_error_type(kind, payload):
    if kind != "retry":
        return ""
    text = str(payload)
    if "tool args must be an object" in text:
        return "invalid_tool_args"
    if "malformed tool JSON" in text:
        return "malformed_tool_json"
    if "empty response" in text:
        return "empty_response"
    return "malformed_tool"


def retry_notice(problem=None):
    prefix = "Runtime notice"
    if problem:
        prefix += f": {problem}"
    else:
        prefix += ": model returned malformed tool output"
    return (
        f"{prefix}. Reply with a valid <tool> call or a non-empty <final> answer. "
        'For one multi-line file, prefer <tool name="write_file" path="file.py"><content>...</content></tool>. '
        'For multiple files, prefer <tool name="write_files"><file path="README.md"><content>...</content></file></tool>.'
    )


def parse_xml_tool(raw):
    match = re.search(r"<tool(?P<attrs>[^>]*)>(?P<body>.*?)</tool>", str(raw), re.S)
    if not match:
        return None
    attrs = parse_attrs(match.group("attrs"))
    name = str(attrs.pop("name", "")).strip()
    if not name:
        return None

    body = match.group("body")
    args = dict(attrs)
    if name == "write_files":
        files = []
        for file_match in re.finditer(r"<file(?P<attrs>[^>]*)>(?P<body>.*?)</file>", body, re.S):
            file_attrs = parse_attrs(file_match.group("attrs"))
            file_body = file_match.group("body")
            content = extract_raw(file_body, "content") if "<content>" in file_body else file_body.strip("\n")
            content = strip_cdata(content)
            files.append({"path": file_attrs.get("path", ""), "content": content})
        if files:
            args["files"] = files
            return {"name": name, "args": args}
    for key in ("content", "old_text", "new_text", "command", "task", "pattern", "path"):
        if f"<{key}>" in body:
            args[key] = strip_cdata(extract_raw(body, key))

    body_text = body.strip("\n")
    if name == "write_file" and "content" not in args and body_text:
        args["content"] = strip_cdata(body_text)
    if name == "delegate" and "task" not in args and body_text:
        args["task"] = body_text.strip()
    return {"name": name, "args": args}


def parse_attrs(text):
    attrs = {}
    for match in re.finditer(r"""([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""", str(text)):
        attrs[match.group(1)] = match.group(2) if match.group(2) is not None else match.group(3)
    return attrs


def extract(text, tag):
    start_tag = f"<{tag}>"
    end_tag = f"</{tag}>"
    text = str(text)
    start = text.find(start_tag)
    if start == -1:
        return text
    start += len(start_tag)
    end = text.find(end_tag, start)
    if end == -1:
        return text[start:].strip()
    return text[start:end].strip()


def extract_raw(text, tag):
    start_tag = f"<{tag}>"
    end_tag = f"</{tag}>"
    text = str(text)
    start = text.find(start_tag)
    if start == -1:
        return text
    start += len(start_tag)
    end = text.find(end_tag, start)
    if end == -1:
        return text[start:]
    return text[start:end]


def strip_cdata(text):
    text = str(text)
    if text.startswith("<![CDATA[") and text.endswith("]]>"):
        return text[len("<![CDATA[") : -len("]]>")]
    return text
