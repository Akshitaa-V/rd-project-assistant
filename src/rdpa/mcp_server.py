"""MCP server exposing the R&D portfolio tools to any MCP client.

Run over stdio (for desktop clients and IDEs):      python -m rdpa.mcp_server
Run over Streamable HTTP (for shared/remote use):   python -m rdpa.mcp_server --http
All tools are read-only.
"""
from __future__ import annotations

import json
import sys

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import config, tools

server = MCPServer(
    name="rd-project-assistant",
    instructions="Read-only access to R&D project status, milestones, risks and the project knowledge base.",
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


@server.tool(annotations=READ_ONLY)
def get_portfolio_status() -> dict:
    """Traffic-light status (red/amber/green) of every R&D project, with reasons and portfolio totals."""
    return tools.get_portfolio_status()


@server.tool(annotations=READ_ONLY)
def get_project_status(project: str) -> dict:
    """Schedule, budget burn and risk figures for one project, given its id (RD-101) or part of its name."""
    return _checked(tools.call("get_project_status", {"project": project}))


@server.tool(annotations=READ_ONLY)
def list_overdue_milestones(project: str | None = None) -> list[dict]:
    """Milestones past their planned date and not completed, most overdue first. Optionally for one project."""
    return _checked(tools.call("list_overdue_milestones", {"project": project}))


@server.tool(annotations=READ_ONLY)
def get_open_risks(project: str | None = None, min_score: int = 0) -> list[dict]:
    """Open risks with score = probability x impact (1-25), highest first. min_score=15 returns high risks."""
    return _checked(tools.call("get_open_risks", {"project": project, "min_score": min_score}))


@server.tool(annotations=READ_ONLY)
def search_knowledge_base(query: str, k: int = 3) -> list[dict]:
    """Search design review minutes, risk reviews and process documents. Each hit cites its document id."""
    return tools.search_knowledge_base(query, k=k)


@server.resource("rdpa://reports/weekly-status")
def weekly_status_report() -> str:
    """The latest generated weekly status report (Markdown)."""
    path = config.OUT_DIR / "weekly_status_report.md"
    return path.read_text(encoding="utf-8") if path.exists() else "No report generated yet. Run: python -m rdpa build"


def _checked(result):
    if isinstance(result, dict) and "error" in result:
        raise ToolError(result["error"])  # message is shown to the client so the model can correct itself
    return result


def main() -> None:
    if not config.DB_PATH.exists():
        print(json.dumps({"error": "database missing, run: python -m rdpa build"}), file=sys.stderr)
    if "--http" in sys.argv:
        server.run("streamable-http")
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
