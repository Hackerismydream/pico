# P03｜Agent Loop

<callout emoji="🎯">
**任务：**修复一个失败测试，并告诉用户改了什么。
**可见结果：**第五次模型调用运行测试得到 `7 passed`，第六次模型调用整理修改内容并回复用户。
**Agent Loop：**程序把目前发生过的事情交给模型；模型要用工具，程序就执行工具、记下结果，再调用模型。模型直接回答，或者达到最多调用次数、被用户取消时，循环结束。
下面的六次调用是为了讲清控制流程而设计的教学轨迹，不是 Pico benchmark，也不代表每个任务固定执行六次。
</callout>

## 一个请求，为什么调用六次模型

用户只发送一次请求。模型返回工具调用后，Pico 会按顺序执行这一批调用，把结果全部写进 messages，再进入下一次模型调用。这个例子因此经历了六次模型调用：

| 第几次 | 模型决定 | 实际结果 | 下一次多看见什么 |
|-|-|-|-|
| 1 | `read_file` | 读到失败测试和相关代码 | 文件内容 |
| 2 | `edit_file` | 旧文本没有匹配，修改失败 | 工具返回的失败原因 |
| 3 | `read_file` | 重新读取精确范围 | 准确的原始文本 |
| 4 | `edit_file` | 修改成功 | `edit_file` 返回的成功结果 |
| 5 | `exec` | `7 passed` | `exec` 返回的测试输出 |
| 6 | 直接回复 | 说明改动和测试结果 | 本次执行结束 |

### 这六次调用为什么叫一个 Loop

1. 程序把用户请求和前面发生过的事情交给模型。
2. 模型需要工具时，Pico 执行工具，并把成功或失败结果记下来。
3. 程序带着更新后的记录再次调用模型。模型直接回答，或者达到最多调用次数、被用户取消时，循环才结束。

> 把它压成一行：模型判断 → 工具执行 → 结果写回 → 模型再判断。负责重复这条路径的程序，就是 Agent Loop。

从用户请求进入执行，到 Pico 返回结果或报告失败，叫一个 **Turn**。Turn 中每次调用模型并处理它的结果，叫一次 **Iteration**。这六次 Iteration 共用一份不断增长的 **messages**。

文件确实已经在第四次调用后落盘，但模型不会直接看见磁盘；它通过 `edit_file` 返回的工具结果知道修改成功。

**看图 1：**第二次修改失败后，第三次模型调用为什么知道要重新读文件？

![](images/P03/img1.jpg)

图中下半部分是答案：工具调用和工具结果都会追加到 messages，下一次模型调用会看见前面已经发生的事。

---

## 先认路：谁接住这次请求

先看职责，不背类名。外层负责排队和收尾，中间层把请求交给 Agent，最里面的循环才负责反复调用模型和工具。

| 源码 | 普通话职责 | 这章何时打开 |
|-|-|-|
| [`pico/spine/scheduler.py`](https://github.com/Hackerismydream/pico/blob/61de762c97ab3972d3a343d9f92ca3c97467a769/pico/spine/scheduler.py) | 让同一会话里的请求排队执行，并负责取消和收尾 | 看 Turn 的外层 |
| [`pico/agent/spine_runner.py`](https://github.com/Hackerismydream/pico/blob/61de762c97ab3972d3a343d9f92ca3c97467a769/pico/agent/spine_runner.py) | 接住排队后的请求，传递输出和途中到达的新消息 | 看请求怎样进入 Agent |
| [`pico/agent/loop/main.py`](https://github.com/Hackerismydream/pico/blob/61de762c97ab3972d3a343d9f92ca3c97467a769/pico/agent/loop/main.py) | 把准备 messages、运行循环和保存结果串起来 | 本章主文件 |

第一次阅读只跟这三个文件。工具、模型错误和空响应的文件放到章末，需要验证时再打开。

---

## messages 怎样把失败带到下一次调用

第二次 Iteration 调用 `edit_file` 后，messages 里会多出一条“模型请求修改”的消息和一条“工具报告失败”的消息。先看教学版结构：

```json
[
  {
    "role": "user",
    "content": "修复这个失败测试"
  },
  {
    "role": "assistant",
    "content": null,
    "tool_call": {
      "id": "call_02",
      "name": "edit_file",
      "arguments": {"old_text": "...", "new_text": "..."}
    }
  },
  {
    "role": "tool",
    "tool_call_id": "call_02",
    "name": "edit_file",
    "content": "old_text did not match"
  }
]
```

真实模型协议会把工具名和参数再包一层，并把参数编码成 JSON 字符串；那是接入模型时需要处理的格式，不影响这里的关键关系：调用 ID、工具名和结果会一起留在 messages 中。

| 时点 | 刚刚追加的消息 | 下一次模型能据此做什么 |
|-|-|-|
| Iteration 1 之后 | `read_file` 调用和文件内容 | 根据真实代码生成修改参数 |
| Iteration 2 之后 | `edit_file` 调用和失败结果 | 知道原文本没有匹配，不能假装修改成功 |
| Iteration 3 之前 | 前两次新增内容全部保留 | 重新读取精确范围，再换一组参数 |

`tool_call_id` 把调用和结果配成一对。Pico 通过 `ContextBuilder.add_tool_result()` 写入 tool 消息，并把工具内容包在不可信数据边界内，防止文件或网页里的文字冒充新的系统指令。

---

## 一次 Iteration 在 Pico 里怎样推进

现在再看循环。一次正常推进只做一件事：让模型根据当前 messages 决定下一步，然后把真实执行结果写回来。

```python
while iteration < max_iterations:
    messages += drain_new_user_messages()
    tools = tool_registry.get_definitions()

    call_messages, call_tools, call_model = before_llm_call(
        messages, tools, model
    )
    response = provider(call_messages, call_tools, call_model)

    if response.tool_calls:
        messages.append(response.as_assistant_message())
        for call in response.tool_calls:       # 顺序执行
            result = execute(call)
            messages.append(tool_result(call.id, result))
        continue

    return response.visible_text
```

对照源码时，按这个顺序读：

1. `drain()` 把 Turn 中途到达的新用户消息合并进来。
2. `ToolRegistry.get_definitions()` 取得当前可用工具。
3. `StrategyRegistry.before_llm_call()` 可以调整本次发送的 messages、工具或模型。
4. Provider 调用模型；返回后 `after_llm_call()` 记录用量等信息。
5. 有 tool calls 时，Pico 先保存 assistant 消息，再按顺序执行工具并保存每条结果。
6. 没有 tool calls 且存在可见正文时，这段正文成为最终回答。

**看图 2：**工具结果为什么必须回到 messages，而不能由工具直接生成最终回答？

![](images/P03/img2.jpg)

工具只负责执行。模型读取结果后决定继续调用工具还是结束，这段重复控制就是 Agent Loop。

---

## edit_file 失败后，为什么还能继续

`edit_file` 返回失败时，失败首先是一条工具结果。它会进入 messages，等待下一次模型调用处理。Turn 是否正常收尾、测试是否真的通过，是后面两层判断。

| 哪一层 | 回答什么问题 | 在六次轨迹里 |
|-|-|-|
| 工具结果 | 这一次读、写或命令有没有成功 | Iteration 2 的 `edit_file` 失败 |
| Turn 终态 | 运行时是正常返回、取消还是抛出异常 | Iteration 6 返回后由 Spine 发出事件 |
| 任务验收 | 用户目标是否真的满足验收条件 | 本例用测试命令及其 `7 passed` 输出作为证据 |

任务验收有时也写作 `Task Verifier`，它不是 Pico 里一个固定的类。不同任务可以用测试、接口响应或人工检查作为验收方式。

Pico 还会观察连续失败。只要同一个工具连续发生两次确定性失败，且错误不属于限流、超时等短暂问题，循环就把“停止重复、检查精确路径或更换方案”的提示追加到最后一条 tool 消息。提示触发后连续计数归零；一个 Turn 最多插入两次。

> 这个保护只推动模型换方法。它不宣布修复成功，也不提前制造 TurnFailed；如果模型仍然无法完成，最大 Iteration 会负责收口。

---

## 继续尝试和最终结束，分开看

先看循环怎样继续。每种恢复都有边界，避免一次异常变成无限重试。

| 遇到什么 | Pico 怎样继续 | 默认边界 |
|-|-|-|
| 工具结果失败 | 写回 messages，让模型读取失败原因并调整 | 受整个 Turn 的 Iteration 上限约束 |
| 同一工具连续硬失败 | 在第二次失败结果后追加换方案提示 | 每个新连续段满 2 次触发；每 Turn 最多 2 次提示 |
| 上下文超限 | 收缩旧 tool results，重试当前 Iteration；这次溢出不计入 Iteration | 最多 2 次收缩重试 |
| Provider 短暂错误 | 非流式路径按约 1、2、4 秒退避并加入 ±10% 抖动；错误允许且配置了候选模型时继续 fallback | 每个模型 4 次尝试；流式路径当前不走这套重试 |
| 没有可见正文 | 思考内容已有时用 `PREFILL`；工具后空回复用 `NUDGE`；普通空回复用 `RETRY` | 默认分别为 2、1、3 次，可配置 |

恢复预算耗尽或错误无法恢复后，再看最终结果。达到最大 Iteration 时，Pico 会再调用一次模型整理现状；这次调用禁用工具，源码称为 Synthesis。

| 情况 | 循环内部 | 向外传播 | Spine 终态 |
|-|-|-|-|
| 模型给出最终正文 | `completed` | 返回 TurnOutcome | `TurnEnded` |
| 达到最大 Iteration | `interrupted`，执行 tools-disabled Synthesis | 返回 TurnOutcome | `TurnEnded` |
| Provider 无法恢复 | `error` | `ProviderTurnError` | `TurnFailed` |
| 用户取消 | 循环被中断 | `CancelledError` | `TurnFailed(cancelled=True)` |
| 保存或其他收尾异常 | 异常离开 | 原异常继续向外 | `TurnFailed(cancelled=False)` |

**看图 3：**为什么 `interrupted` 最后仍可能是 `TurnEnded`？

![](images/P03/img3.jpg)

内层状态描述循环做到哪一步；Spine 事件描述这次运行怎样收尾。`TurnEnded` 只说明控制流程正常返回，任务是否完成仍要看测试或其他 verifier。

---

## 循环结束后，谁保存，谁收尾

模型给出正文或 Synthesis 完成后，`_process_message()` 按下面的顺序保存本次 Turn：

```text
_save_turn()
  └─ Session.record：把本 Turn 新消息追加到 Session
      ↓
SessionManager.save：把 Session 落盘
      ↓
ContextEngine.after_turn：处理本轮结束后的上下文更新
      ↓
MemoryBackend.store：把本轮消息交给长期记忆后端
```

`_save_turn()` 会丢弃临时恢复提示、清理不适合持久化的字段，并截断过长的工具结果。Session 已经落盘后，如果 `after_turn` 或 `MemoryBackend.store` 抛出异常，异常仍会到达 Spine，因此不会发出成功的 `TurnEnded`。

<callout emoji="💡">
**取消只能阻止后续步骤。**已经写入文件、发送到外部系统的消息，以及已经流式展示给用户的文本都可能无法撤回。恢复任务前，先检查现场，再决定从哪里继续。
</callout>

---

## 回到源码：验证、练习和面试

理解主线后，再用函数和测试验证。下面的链接固定到本章使用的源码提交。

| 源码锚点 | 验证什么 |
|-|-|
| [`Lane._run_worker()`](https://github.com/Hackerismydream/pico/blob/61de762c97ab3972d3a343d9f92ca3c97467a769/pico/spine/scheduler.py#L201)、[`Lane._run_turn()`](https://github.com/Hackerismydream/pico/blob/61de762c97ab3972d3a343d9f92ca3c97467a769/pico/spine/scheduler.py#L271) | 排队、取消、`TurnStarted`、`TurnEnded`、`TurnFailed` |
| [`AgentTurnRunner`](https://github.com/Hackerismydream/pico/blob/61de762c97ab3972d3a343d9f92ca3c97467a769/pico/agent/spine_runner.py#L20) | `req / emit / drain` 怎样进入 AgentLoop |
| [`_run_agent_loop()`](https://github.com/Hackerismydream/pico/blob/61de762c97ab3972d3a343d9f92ca3c97467a769/pico/agent/loop/main.py#L1098) | messages、模型调用、顺序工具执行、恢复和内部状态 |
| [`add_tool_result()`](https://github.com/Hackerismydream/pico/blob/61de762c97ab3972d3a343d9f92ca3c97467a769/pico/agent/context/builder.py#L314) | `tool_call_id` 和不可信工具输出包装 |
| [`ToolRegistry`](https://github.com/Hackerismydream/pico/blob/61de762c97ab3972d3a343d9f92ca3c97467a769/pico/agent/tools/registry.py) | 工具定义从哪里来，工具调用怎样执行 |
| [`Provider`](https://github.com/Hackerismydream/pico/blob/61de762c97ab3972d3a343d9f92ca3c97467a769/pico/providers/base.py) | 非流式模型调用怎样退避重试，何时切换候选模型 |
| [`classify_empty_response()`](https://github.com/Hackerismydream/pico/blob/61de762c97ab3972d3a343d9f92ca3c97467a769/pico/agent/loop/recovery.py#L84) | `PREFILL / NUDGE / RETRY` 的选择与预算 |
| [`_process_message()`](https://github.com/Hackerismydream/pico/blob/61de762c97ab3972d3a343d9f92ca3c97467a769/pico/agent/loop/main.py#L1521)、[`_save_turn()`](https://github.com/Hackerismydream/pico/blob/61de762c97ab3972d3a343d9f92ca3c97467a769/pico/agent/loop/main.py#L1842) | 错误向外传播与持久化顺序 |

<callout emoji="✅">
**事实基线：**`origin/main = 61de762c97ab3972d3a343d9f92ca3c97467a769`。
在该提交的独立 worktree 中，覆盖空响应、上下文超限、最大 Iteration、重复工具失败、终态、持久化、错误分类、工具超时、检查点和事件关联的 10 个测试文件共 `150 passed`。
</callout>

### 动手练习

1. 从 [`test_agent_loop_tool_loop_break.py`](https://github.com/Hackerismydream/pico/blob/61de762c97ab3972d3a343d9f92ca3c97467a769/tests/test_agent_loop_tool_loop_break.py) 找出一条工具失败后继续执行的轨迹。
2. 为六次 Iteration 各写一行：本次新增了哪条 assistant 或 tool 消息。
3. 分别判断正常回答、达到上限、Provider 无法恢复和取消会产生 `TurnEnded` 还是 `TurnFailed`。
4. 解释为什么测试通过属于任务验收（Task Verifier），而不是 Spine 终态。
5. 不看图，画出 Lane、AgentTurnRunner、`run_turn / _process_message`、`_run_agent_loop` 的所有权边界。

### 面试里怎样讲

> Pico 的 Agent Loop 运行在一个 Turn 内，一个 Turn 可以包含多次 Iteration。每次 Iteration 都把当前 messages 和工具定义交给 Provider；模型返回 tool call 时，Pico 先保存 assistant 消息，再按顺序执行工具，并通过 tool_call_id 把结果写回 messages。下一次模型调用因此能根据真实执行结果继续决策。工具失败只表示这一次动作失败，Pico 会把失败交回模型；同一工具连续发生确定性失败时，还会注入有界的换方案提示。上下文超限、Provider 短暂错误和空响应也各有独立预算。达到 max_iterations 时，循环把内部状态记为 interrupted，再做一次禁用工具的 Synthesis。最终的 TurnEnded、TurnFailed 和取消终态由 Spine Lane 负责。

读完后，先尝试脱离教材回答三个问题：

- [ ] 一个 Turn 为什么能包含六次 Iteration？

- [ ] Iteration 2 的 edit_file 失败怎样影响 Iteration 3？

- [ ] 为什么 interrupted 可以对应 TurnEnded，却不能证明任务完成？

继续阅读：

- [P04｜工具系统：read_file 是怎样被调用的](https://icnoljnkix43.feishu.cn/wiki/J8q9wwxYaiZaGQkDCyocOTZonIh)
- [P05｜从消息到上下文：模型到底看到了什么](https://icnoljnkix43.feishu.cn/wiki/M7yGwGfLHiBUk9kn3NAcF3DknYc)
- [P06｜上下文工程：Token 不够时，Pico 怎么办](https://icnoljnkix43.feishu.cn/wiki/X4jBwea88iQS3rke1p2cuHKanwf)
