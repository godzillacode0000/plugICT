"""
MCP handshake test — launches mcp_server.py as a real subprocess against a
fixture vault and drives it over stdio like Claude Desktop would.

This is the test that would have caught the shipped v2 server: undefined
`encrypted`, wrong InitializationOptions import, and stdout banners corrupting
the JSON-RPC channel all cause this to fail.
"""

import os
import sys
import asyncio
import tempfile
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_vault_core import _write_fixture_vault  # reuse the fixture builder
import mcp_server as server

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession


def test_vault_identity_prefers_buyer_package_local_asset(tmp_path, monkeypatch):
    packaged_server = tmp_path / "mcp_server.py"
    packaged_server.write_text("# fixture", encoding="utf-8")
    (tmp_path / "VAULT.md").write_text("# Packaged identity", encoding="utf-8")
    monkeypatch.setattr(server, "__file__", str(packaged_server))
    assert server.vault_identity() == "# Packaged identity"


def test_shipped_vault_identity_names_only_exposed_search_tools():
    identity = (ROOT / "VAULT.md").read_text(encoding="utf-8")
    assert "`search_ict`" in identity
    assert "`multi_search_ict`" in identity
    assert "`search_vault`" not in identity


def test_search_tool_uses_numeric_start_seconds_for_deeplink(monkeypatch):
    monkeypatch.setattr(server, "ensure_vault", lambda: None)
    monkeypatch.setattr(server, "_rate_limit_exceeded", lambda _units: False)
    monkeypatch.setattr(server, "_licensed_to", "Fixture Buyer")
    monkeypatch.setattr(server.vc, "demo_info", lambda _db: None)
    monkeypatch.setattr(server, "search_vault", lambda *args, **kwargs: [{
        "title": "Numeric provenance",
        "method": "lexical",
        "timestamp": "9:59",
        "start_seconds": 7,
        "playlist": "Fixture",
        "snippet": "Evidence",
        "video_id": "vid123",
    }])

    result = asyncio.run(server.call_tool("search_ict", {"query": "evidence"}))

    assert "https://youtu.be/vid123?t=7" in result[0].text


def _fake_ref_store(candidates):
    class FakeRefs:
        def peek(self, ref):
            return dict(candidates[ref])

        def resolve(self, ref):
            return dict(candidates[ref])

    return FakeRefs()


def test_research_bundle_enforces_video_limit_before_append(monkeypatch):
    candidates = {
        f"r{i}": {"video_id": f"v{i}", "title": f"Video {i}", "timestamp": "0:00"}
        for i in range(4)
    }
    monkeypatch.setattr(server, "ensure_vault", lambda: None)
    monkeypatch.setattr(server, "_result_refs", _fake_ref_store(candidates))
    monkeypatch.setattr(server, "_build_bundle_ctx", lambda candidate, limit: "x" * min(limit, 4999))

    plan = server.build_research_bundle_plan("q", list(candidates), max_videos=3)
    bundle = server.build_research_bundle("q", list(candidates), max_videos=3)

    assert plan["plan"]["videos"] == 3
    assert bundle["bundle"]["videos"] == 3
    assert {e["video_id"] for e in bundle["evidence"]} == {"v0", "v1", "v2"}


def test_research_bundle_enforces_actual_per_video_and_global_char_caps(monkeypatch):
    candidates = {
        f"r{video}-{chunk}": {
            "video_id": f"v{video}", "title": f"Video {video}", "timestamp": "0:00"
        }
        for video in range(4) for chunk in range(4)
    }
    monkeypatch.setattr(server, "ensure_vault", lambda: None)
    monkeypatch.setattr(server, "_result_refs", _fake_ref_store(candidates))
    monkeypatch.setattr(server, "_build_bundle_ctx", lambda candidate, limit: "x" * min(limit, 4999))

    bundle = server.build_research_bundle(
        "q", list(candidates), max_videos=4, context_chars_per_chunk=5000)

    actual_total = sum(len(e["context"]) for e in bundle["evidence"])
    per_video = {}
    for evidence in bundle["evidence"]:
        per_video[evidence["video_id"]] = per_video.get(evidence["video_id"], 0) + len(evidence["context"])
    assert actual_total == bundle["bundle"]["total_chars"]
    assert actual_total <= server._MAX_BUNDLE_CHARS
    assert max(per_video.values()) <= server._MAX_CHARS_PER_VIDEO


async def _drive():
    tmp = tempfile.mkdtemp()
    vault, lic = _write_fixture_vault(tmp, compress=True)

    env = dict(os.environ)
    env["ICT_VAULT_FILE"] = str(vault)
    env["ICT_VAULT_LICENSE"] = str(lic)

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "scripts" / "mcp_server.py")],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.serverInfo.name == "ict-knowledge-vault"

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert {
                "vault_identity", "search_ict", "multi_search_ict", "expand_result",
                "list_playlists", "explore_concept", "vault_stats", "glossary_lookup",
                "build_research_bundle_plan", "build_research_bundle",
            } == names

            stats = await session.call_tool("vault_stats", {})
            text = stats.content[0].text
            assert "Licensed to: tester@example.com" in text

            res = await session.call_tool("search_ict", {"query": "fair value gap"})
            assert "Fair Value Gap Explained" in res.content[0].text

            gl = await session.call_tool("glossary_lookup", {"term": "FVG"})
            assert "Fair Value Gap" in gl.content[0].text

            multi = await session.call_tool("multi_search_ict", {
                "question": "what is a fair value gap",
                "queries": ["fair value gap", "imbalance"],
                "top_k": 1,
            })
            payload = json.loads(multi.content[0].text)
            assert payload["results"]
            result_ref = payload["results"][0]["result_ref"]
            assert payload["results"][0]["matched_queries"]
            assert payload["results"][0]["retrieval_sources"]

            expanded = await session.call_tool("expand_result", {
                "result_ref": result_ref,
                "before": 0,
                "after": 0,
            })
            context = json.loads(expanded.content[0].text)
            assert context["sections"][0]["position"] == "current"
            assert "Fair Value Gap" in context["sections"][0]["title"]

            bundle_search = await session.call_tool("multi_search_ict", {
                "question": "research fair value gaps",
                "queries": ["fair value gap"],
                "top_k": 1,
            })
            bundle_payload = json.loads(bundle_search.content[0].text)
            bundle_ref = bundle_payload["results"][0]["result_ref"]
            plan = await session.call_tool("build_research_bundle_plan", {
                "question": "research fair value gaps", "result_refs": [bundle_ref],
            })
            assert json.loads(plan.content[0].text)["plan"]["chunks"] == 1
            built = await session.call_tool("build_research_bundle", {
                "question": "research fair value gaps", "result_refs": [bundle_ref],
            })
            bundle = json.loads(built.content[0].text)
            assert bundle["evidence"][0]["context"]
            assert "fair value gap" in bundle["evidence"][0]["context"].lower()


def test_mcp_handshake_and_tools():
    asyncio.run(asyncio.wait_for(_drive(), timeout=60))
