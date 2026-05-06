from pico.core.model_decision import ModelDecisionAdapter, ModelDecision


def test_model_decision_adapter_parses_json_tool_call():
    decision = ModelDecisionAdapter().parse('<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>')

    assert decision == ModelDecision(
        kind="tool",
        payload={"name": "read_file", "args": {"path": "README.md"}},
        parse_error_type="",
    )


def test_model_decision_adapter_parses_xml_write_file_tool():
    decision = ModelDecisionAdapter().parse(
        '<tool name="write_file" path="hello.py"><content><![CDATA[print("hi")\n]]></content></tool>'
    )

    assert decision.kind == "tool"
    assert decision.payload == {"name": "write_file", "args": {"path": "hello.py", "content": 'print("hi")\n'}}
    assert decision.parse_error_type == ""


def test_model_decision_adapter_parses_final_and_retry_metadata():
    adapter = ModelDecisionAdapter()

    final = adapter.parse("<final>done</final>")
    retry = adapter.parse('<tool>{"name":"read_file","args":"bad"}</tool>')
    empty = adapter.parse("")

    assert final == ModelDecision(kind="final", payload="done", parse_error_type="")
    assert retry.kind == "retry"
    assert retry.parse_error_type == "invalid_tool_args"
    assert empty.kind == "retry"
    assert empty.parse_error_type == "empty_response"
