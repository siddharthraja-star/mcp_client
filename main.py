import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MCP_SERVER_COMMAND = os.environ.get("MCP_SERVER_COMMAND", "npx")
MCP_SERVER_ARGS = os.environ.get(
    "MCP_SERVER_ARGS", "-y @modelcontextprotocol/server-filesystem /tmp"
).split()
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8005"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MCP Gateway running on %s:%s", HOST, PORT)
    yield


app = FastAPI(title="MCP Gateway", lifespan=lifespan)



class CallToolRequest(BaseModel):
    server: str | None = None
    tool_name: str
    arguments: dict[str, Any] = {}


def _server_params() -> StdioServerParameters:
    return StdioServerParameters(command=MCP_SERVER_COMMAND, args=MCP_SERVER_ARGS)


def _load_mcp_servers() -> dict[str, dict]:
    servers: dict[str, dict] = {}

    # Global Claude config (~/.claude.json)
    global_config = Path.home() / ".claude.json"
    if global_config.exists():
        try:
            data = json.loads(global_config.read_text())
            servers.update(data.get("mcpServers", {}))
        except Exception:
            pass

    # Project-level .mcp.json files (cwd and parents up to home)
    search_root = Path.home()
    for mcp_file in search_root.rglob(".mcp.json"):
        try:
            data = json.loads(mcp_file.read_text())
            for name, cfg in data.get("mcpServers", {}).items():
                servers[name] = {**cfg, "_source": str(mcp_file)}
        except Exception:
            pass

    return servers


@app.get("/mcp-servers")
async def list_mcp_servers():
    return {"servers": _load_mcp_servers()}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/list-tools")
async def list_tools(server: str | None = None):
    """List tools from the configured server, or a named server from .mcp.json / ~/.claude.json."""
    if server:
        servers = _load_mcp_servers()
        if server not in servers:
            raise HTTPException(status_code=404, detail=f"MCP server '{server}' not found")
        cfg = servers[server]
        source = cfg.get("_source")
        cwd = str(Path(source).parent) if source else None
        params = StdioServerParameters(
            command=cfg["command"],
            args=cfg.get("args", []),
            env=cfg.get("env"),
            cwd=cwd,
        )
    else:
        params = _server_params()

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return {"server": server or MCP_SERVER_COMMAND, "tools": [t.model_dump() for t in result.tools]}


@app.post("/call-tool")
async def call_tool(request: CallToolRequest):
    if request.server:
        servers = _load_mcp_servers()
        if request.server not in servers:
            raise HTTPException(status_code=404, detail=f"MCP server '{request.server}' not found")
        cfg = servers[request.server]
        source = cfg.get("_source")
        cwd = str(Path(source).parent) if source else None
        params = StdioServerParameters(
            command=cfg["command"],
            args=cfg.get("args", []),
            env=cfg.get("env"),
            cwd=cwd,
        )
    else:
        params = _server_params()

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                result = await session.call_tool(request.tool_name, request.arguments)
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {
                "server": request.server or MCP_SERVER_COMMAND,
                "content": [c.model_dump() for c in result.content],
                "isError": result.isError,
            }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
