"""In-process MCP server. The same tools the chat uses are exposed at /mcp."""

import logging

logger = logging.getLogger(__name__)


def mount_mcp(app) -> None:
    """Mount FastMCP when the package is installed. The app still starts without it."""
    try:
        from fastmcp import FastMCP
    except Exception:
        logger.info("fastmcp is not installed; /mcp is not mounted")
        return
    server = FastMCP("ProfAssist")

    @server.tool
    def list_profassist_tools() -> list[dict]:
        """List the professor tools and whether each one is enabled."""
        from app.profassist.platform_tools import tool_catalog

        return tool_catalog()

    from app.profassist.platform_tools import tool_catalog

    for spec in tool_catalog():

        def _bind(name: str, summary: str):
            @server.tool(name=name, description=summary)
            def run_named(message: str = "") -> dict:
                """Describe one professor tool. The signed-in chat runs it."""
                return {
                    "tool": name,
                    "summary": summary,
                    "message": message,
                    "href": "/dashboard",
                    "note": "The signed-in chat runs this tool after the privacy gate.",
                }

            return run_named

        _bind(spec["name"], spec.get("summary") or spec["name"])

    try:
        http_app = server.http_app(path="/")
    except TypeError:
        http_app = server.http_app()
    app.mount("/mcp", http_app)
