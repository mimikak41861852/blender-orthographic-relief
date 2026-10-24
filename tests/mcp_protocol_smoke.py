"""Verify that the server completes a real MCP STDIO handshake and lists tools."""

import pathlib
import sys

import anyio
from mcp import Client, StdioServerParameters


REPOSITORY = pathlib.Path(__file__).resolve().parents[1]


async def main():
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(REPOSITORY / "mcp_server.py")],
        cwd=REPOSITORY,
    )
    async with Client(parameters, read_timeout_seconds=20.0) as client:
        response = await client.list_tools()
        names = {tool.name for tool in response.tools}
        assert names == {"ping_blender", "list_mesh_objects", "generate_relief"}
        print("MCP_PROTOCOL_OK", sorted(names))


if __name__ == "__main__":
    anyio.run(main)
