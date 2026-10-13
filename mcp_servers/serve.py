"""Run an MCP server over stdio (default, for local agents and tests) or streamable HTTP
(`--http HOST:PORT`, how the services run in Docker)."""

import argparse

from mcp.server.mcpserver import MCPServer


def http_address(argv: list[str] | None, name: str) -> tuple[str, int] | None:
    parser = argparse.ArgumentParser(description=name)
    parser.add_argument("--http", metavar="HOST:PORT", help="serve streamable HTTP, not stdio")
    args = parser.parse_args(argv)
    if not args.http:
        return None
    host, port = args.http.rsplit(":", 1)
    return host, int(port)


def run(server: MCPServer, address: tuple[str, int] | None) -> None:
    if address:
        server.run("streamable-http", host=address[0], port=address[1])
    else:
        server.run("stdio")
