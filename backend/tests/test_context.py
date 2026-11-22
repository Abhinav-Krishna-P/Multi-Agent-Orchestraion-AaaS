from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


def _rows(*pairs):
    return [SimpleNamespace(role=role, content=content) for role, content in pairs]


def test_system_prompt_only():
    from app.agent.context import build_messages

    out = build_messages("You are helpful.", None, _rows(("user", "Hi")))
    assert isinstance(out[0], SystemMessage)
    assert out[0].content == "You are helpful."


def test_summary_appended():
    from app.agent.context import build_messages

    out = build_messages("You are helpful.", "S", _rows(("user", "Hi")))
    assert out[0].content == "You are helpful.\n\nSummary of the conversation so far:\nS"


def test_roles_mapped_in_order():
    from app.agent.context import build_messages

    out = build_messages("P", None, _rows(("user", "one"), ("assistant", "two"), ("user", "three")))
    assert [type(m) for m in out] == [SystemMessage, HumanMessage, AIMessage, HumanMessage]
    assert [m.content for m in out[1:]] == ["one", "two", "three"]


def test_leading_assistant_dropped():
    from app.agent.context import build_messages

    out = build_messages("P", None, _rows(("assistant", "old"), ("assistant", "older"), ("user", "hi")))
    assert [type(m) for m in out] == [SystemMessage, HumanMessage]
    assert out[1].content == "hi"


def test_history_ending_with_user_ok():
    from app.agent.context import build_messages

    out = build_messages("P", None, _rows(("user", "one"), ("assistant", "two"), ("user", "again")))
    assert isinstance(out[-1], HumanMessage) and out[-1].content == "again"


def test_empty_system_prompt_still_first():
    from app.agent.context import build_messages

    out = build_messages("", None, _rows(("user", "Hi")))
    assert isinstance(out[0], SystemMessage) and isinstance(out[1], HumanMessage)
