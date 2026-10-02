"""End-to-end test: a real MCP client starts the server as a subprocess over stdio."""
import json
import os
import sys
from pathlib import Path

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def _session_run(fn):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    params = StdioServerParameters(command=sys.executable, args=["-m", "rdpa.mcp_server"], env=env, cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def _text(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


def test_mcp_lists_read_only_tools():
    async def go(s):
        return (await s.list_tools()).tools
    tools = anyio.run(_session_run, go)
    names = {t.name for t in tools}
    assert names == {"get_portfolio_status", "get_project_status", "list_overdue_milestones",
                     "get_open_risks", "search_knowledge_base"}
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)


def test_mcp_tool_call_returns_project_data():
    async def go(s):
        return await s.call_tool("get_project_status", {"project": "bootloader"})
    result = anyio.run(_session_run, go)
    assert not result.is_error
    data = json.loads(_text(result))
    assert data["project_id"] == "RD-103" and data["status"] in {"red", "amber", "green"}


def test_mcp_knowledge_search():
    async def go(s):
        return await s.call_tool("search_knowledge_base", {"query": "overtime approval"})
    result = anyio.run(_session_run, go)
    assert "PROC-02" in _text(result)


def test_mcp_unknown_project_is_tool_error():
    async def go(s):
        return await s.call_tool("get_project_status", {"project": "RD-999"})
    result = anyio.run(_session_run, go)
    assert result.is_error and "Unknown project" in _text(result)


def test_mcp_weekly_report_resource():
    async def go(s):
        return await s.read_resource("rdpa://reports/weekly-status")
    result = anyio.run(_session_run, go)
    assert "Weekly Status Report" in result.contents[0].text
