#!/usr/bin/env python3
"""Minimal buyer-path MCP smoke test used by setup.py.

It starts the shipped server through stdio, initializes MCP, calls the public
search_ict tool, and fails unless cited evidence is returned. It never prints
license contents.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run() -> None:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-E", "-X", "utf8", str(Path(__file__).resolve().parent / "mcp_server.py")],
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "search_ict",
                {"query": "What is FVG in ICT?", "top_k": 3},
            )
            text = "\n".join(
                item.text for item in (result.content or []) if getattr(item, "text", None)
            )
            if not text or "Search results for:" not in text or "Video:" not in text:
                raise RuntimeError("search_ict returned no cited evidence")
            print("SMOKE_OK: search_ict returned cited evidence")


if __name__ == "__main__":
    asyncio.run(run())
