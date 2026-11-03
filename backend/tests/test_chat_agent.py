"""Chat agent tests: summarization only fires past the trigger and keeps
the most recent turns; references come only from real tool artifacts."""
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage

from app.chat import agent


def test_summarization_does_not_fire_under_the_trigger():
    messages = [HumanMessage("hi")] * 10
    assert agent._summarize_if_needed({"messages": messages}) == {}


def test_summarization_keeps_the_most_recent_messages(monkeypatch):
    monkeypatch.setattr(agent, "_MODEL",
                        SimpleNamespace(invoke=lambda msgs: SimpleNamespace(content="Patient discussed knee pain.")))
    messages = [HumanMessage(f"message {i}") for i in range(12)]
    update = agent._summarize_if_needed({"messages": messages})
    new_messages = update["messages"]
    assert isinstance(new_messages[0], RemoveMessage)
    assert isinstance(new_messages[1], SystemMessage)
    assert "knee pain" in new_messages[1].content
    # The 4 most recent original messages are kept, unchanged, after the summary.
    assert new_messages[2:] == messages[-4:]


def test_summarization_degrades_gracefully_if_the_model_call_fails(monkeypatch):
    def broken(msgs):
        raise RuntimeError("upstream down")
    monkeypatch.setattr(agent, "_MODEL", SimpleNamespace(invoke=broken))
    messages = [HumanMessage(f"message {i}") for i in range(12)]
    update = agent._summarize_if_needed({"messages": messages})
    assert isinstance(update["messages"][1], SystemMessage)  # a fallback summary message, not a crash


def test_ask_extracts_references_only_from_search_my_records_artifacts(monkeypatch):
    """A tool result from a different tool, or plain assistant text claiming
    a citation, must never be trusted as a reference."""
    monkeypatch.setattr(agent, "_ensure_built", lambda: None)
    monkeypatch.setattr(agent, "_MODEL", SimpleNamespace())
    monkeypatch.setattr(agent, "_CHECKPOINTER", None)

    final_state = {"messages": [
        HumanMessage("what did the doctor say"),
        ToolMessage(content="...", name="search_my_records", tool_call_id="1",
                    artifact=[{"chunk_id": "c1", "text": "knee pain noted"}]),
        ToolMessage(content="...", name="list_my_appointments", tool_call_id="2",
                    artifact=[{"id": "a1"}]),  # a different tool -- must not become a "reference"
        AIMessage("Here is what the doctor said, citing chunk c99."),  # unverified claim in prose
    ]}

    class FakeAgent:
        def invoke(self, input, config):
            return final_state
    monkeypatch.setattr(agent, "create_react_agent", lambda *a, **kw: FakeAgent())

    result = agent.ask("patient-1", "what did the doctor say")
    assert result.reply == "Here is what the doctor said, citing chunk c99."
    assert result.references == [{"chunk_id": "c1", "text": "knee pain noted"}]


def test_ask_deduplicates_references_by_chunk_id(monkeypatch):
    monkeypatch.setattr(agent, "_ensure_built", lambda: None)
    monkeypatch.setattr(agent, "_MODEL", SimpleNamespace())
    monkeypatch.setattr(agent, "_CHECKPOINTER", None)
    chunk = {"chunk_id": "c1", "text": "knee pain"}
    final_state = {"messages": [
        ToolMessage(content="...", name="search_my_records", tool_call_id="1", artifact=[chunk]),
        ToolMessage(content="...", name="search_my_records", tool_call_id="2", artifact=[chunk]),
        AIMessage("Reply."),
    ]}
    monkeypatch.setattr(agent, "create_react_agent",
                        lambda *a, **kw: SimpleNamespace(invoke=lambda i, config: final_state))
    result = agent.ask("patient-1", "query")
    assert result.references == [chunk]
