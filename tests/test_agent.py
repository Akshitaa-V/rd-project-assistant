import json

from rdpa import agent, config, tools
from rdpa.evaluate import retrieval_eval, routing_eval


def test_retrieval_quality_on_labelled_questions():
    result = retrieval_eval()
    assert result["cases"] == 32
    assert result["hit_at_1"] >= 29 and result["hit_at_3"] >= 30


def test_search_returns_cited_snippets():
    hits = tools.search_knowledge_base("copper clip bonding hotspot")
    assert hits[0]["doc_id"] == "RD-101-design-review"
    assert "148" in hits[0]["snippet"]


def test_routing_eval_all_correct():
    assert routing_eval()["wrong"] == []


def test_offline_agent_answers_with_source():
    res = agent.ask("What did the design review decide for the GaN charger?", model=None)
    assert "planar" in res.answer and "[source: RD-105-design-review]" in res.answer
    assert res.trace[0]["tool"] == "search_knowledge_base"


def test_offline_agent_project_status():
    res = agent.ask("How is RD-108 doing?", model=None)
    assert res.answer.startswith("RD-108") and res.trace[0]["tool"] == "get_project_status"


def test_unknown_project_comes_back_as_error_not_crash():
    out = tools.call("get_project_status", {"project": "RD-999"})
    assert "error" in out
    assert "could not answer" in agent._format("get_project_status", out)


def test_unknown_tool_and_bad_args_are_data():
    assert "error" in tools.call("drop_database", {})
    assert "error" in tools.call("get_open_risks", {"nonsense": 1})


def test_llm_failure_falls_back_to_offline(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("litellm")

    def boom(**_kw):
        raise ConnectionError("no network")
    fake.completion = boom
    monkeypatch.setitem(sys.modules, "litellm", fake)
    res = agent.ask("Which milestones are overdue?", model="some/model")
    assert res.mode.startswith("offline (LLM failed") and res.answer.startswith("Overdue")


def test_llm_mode_runs_tool_loop(monkeypatch):
    """Simulated model: first asks for a tool, then answers. Checks the loop wiring."""
    import sys
    import types

    class Fn:
        def __init__(self, name, arguments):
            self.name, self.arguments = name, arguments

    class Call:
        id = "call_1"
        function = Fn("get_open_risks", json.dumps({"min_score": 15}))

    class Msg:
        def __init__(self, content=None, tool_calls=None):
            self.content, self.tool_calls = content, tool_calls

        def model_dump(self):
            return {"role": "assistant", "content": self.content}

    replies = iter([Msg(tool_calls=[Call()]), Msg(content="There are high risks on RD-101.")])
    fake = types.ModuleType("litellm")
    fake.completion = lambda **_kw: types.SimpleNamespace(choices=[types.SimpleNamespace(message=next(replies))])
    monkeypatch.setitem(sys.modules, "litellm", fake)
    res = agent.ask("What are the high risks?", model="fake/model")
    assert res.mode == "llm:fake/model" and res.trace[0]["tool"] == "get_open_risks"
    assert all(r["score"] >= 15 for r in res.trace[0]["result"])


def test_tool_schemas_match_functions():
    assert {s["function"]["name"] for s in tools.TOOL_SCHEMAS} == set(tools.TOOLS)
    assert config.DOCS_DIR.exists()
