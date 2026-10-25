"""MCP server (Streamable HTTP, 2025-11-25) and the Bedrock provider."""
import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app import config
from app.agents import pipeline
from app.llm import router
from app.schemas import AppSettings
from app.store import store

from test_core import _kit

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "")
    monkeypatch.setattr(config, "AWS_BEDROCK_ENABLED", False)
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")
    monkeypatch.setattr(config, "ACCESS_KEY", "")
    monkeypatch.setattr(store, "save", lambda: None)
    monkeypatch.setattr(store, "campaigns", {})
    monkeypatch.setattr(store, "jobs", {})
    monkeypatch.setattr(store, "research", {})
    monkeypatch.setattr(store, "settings", AppSettings())

    async def fake_ingest(raw, search_fn=None):
        return _kit()

    monkeypatch.setattr(pipeline, "ingest", fake_ingest)


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def rpc(client, method, params=None, id_=1, session=None, **headers):
    h = dict(HEADERS, **headers)
    if session:
        h["Mcp-Session-Id"] = session
        h.setdefault("MCP-Protocol-Version", "2025-11-25")
    body = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers=h)


def init(client):
    r = rpc(client, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
    assert r.status_code == 200
    sid = r.headers["mcp-session-id"]
    note = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=dict(HEADERS, **{"Mcp-Session-Id": sid}))
    assert note.status_code == 202 and note.content == b""
    return sid, r.json()


def call(client, sid, name, args):
    r = rpc(client, "tools/call", {"name": name, "arguments": args}, id_=7, session=sid)
    assert r.status_code == 200, r.text
    return r.json()["result"]


def wait_ready(cid, timeout=20):
    t0 = time.time()
    while store.campaigns[cid].status.value == "GENERATING" and time.time() - t0 < timeout:
        time.sleep(0.1)


def test_initialize_handshake_and_version_negotiation(client):
    sid, body = init(client)
    res = body["result"]
    assert res["protocolVersion"] == "2025-11-25" and res["capabilities"]["tools"] == {"listChanged": False}
    assert res["serverInfo"]["name"] == "monoplus" and res["instructions"]
    older = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}).json()
    assert older["result"]["protocolVersion"] == "2025-06-18"
    unknown = rpc(client, "initialize", {"protocolVersion": "1999-01-01", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}).json()
    assert unknown["result"]["protocolVersion"] == "2025-11-25"


def test_transport_rules(client):
    sid, _ = init(client)
    assert client.get("/mcp").status_code == 405
    assert rpc(client, "tools/list", session="not-a-session").status_code == 404
    bad_version = rpc(client, "tools/list", session=sid, **{"MCP-Protocol-Version": "1999-01-01"})
    assert bad_version.status_code == 400
    assert client.post("/mcp", content=b"{not json", headers=HEADERS).json()["error"]["code"] == -32700
    assert client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}], headers=HEADERS).json()["error"]["code"] == -32600
    assert rpc(client, "nope", session=sid).json()["error"]["code"] == -32601
    assert rpc(client, "ping", session=sid).json() == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers=dict(HEADERS, Origin="https://evil.example")).status_code == 403
    assert client.delete("/mcp", headers={"Mcp-Session-Id": sid}).status_code == 204
    assert rpc(client, "ping", session=sid).status_code == 404  # terminated session


def test_tools_list_schemas(client):
    sid, _ = init(client)
    tools = rpc(client, "tools/list", session=sid).json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {"create_campaign", "get_campaign_status", "list_upcoming_posts", "approve_posts", "humanize_text",
                     "research_market", "get_brand_profile"}
    for t in tools:
        assert t["inputSchema"]["type"] == "object" and t["description"] and t["title"]


def test_full_campaign_flow_over_mcp(client):
    sid, _ = init(client)
    started = call(client, sid, "create_campaign", {"website_or_handle": "bluebird.example", "days": 7, "platforms": ["instagram", "twitter"]})
    assert started["isError"] is False
    cid = started["structuredContent"]["campaign_id"]
    assert started["structuredContent"]["platforms"] == ["instagram", "x"]  # "twitter" alias accepted
    wait_ready(cid)
    status = call(client, sid, "get_campaign_status", {"campaign_id": cid})["structuredContent"]
    assert status["status"] == "DRAFT" and status["posts"] == 7 and status["approved"] == 0 and status["next_post"]
    approved = call(client, sid, "approve_posts", {"campaign_id": cid})["structuredContent"]
    assert approved["approved_now"] == 7 and approved["approved_total"] == 7
    brand = call(client, sid, "get_brand_profile", {"campaign_id": cid})["structuredContent"]
    assert brand["name"] == "Bluebird Bakery" and brand["colors"]["primary"] == "#E4572E"
    up = call(client, sid, "list_upcoming_posts", {"days": 10})["structuredContent"]
    assert up["count"] >= 6 and all(p["status"] == "APPROVED" for p in up["posts"])


def test_tool_errors_are_reported_not_raised(client):
    sid, _ = init(client)
    r = call(client, sid, "get_campaign_status", {"campaign_id": "missing"})
    assert r["isError"] is True and "No campaign" in r["content"][0]["text"]
    r = call(client, sid, "create_campaign", {"website_or_handle": ""})
    assert r["isError"] is True
    unknown = rpc(client, "tools/call", {"name": "delete_everything", "arguments": {}}, session=sid).json()
    assert unknown["error"]["code"] == -32602


def test_humanize_tool(client):
    sid, _ = init(client)
    r = call(client, sid, "humanize_text", {"text": "Let's dive in! Our cutting-edge cafe is a game-changer — just $5.", "mode": "light"})
    s = r["structuredContent"]
    assert "$5" in s["text"] and s["human_sounding_after"] > s["human_sounding_before"] and s["patterns_fixed"]


def test_mcp_requires_bearer_key_when_configured(client, monkeypatch):
    monkeypatch.setattr(config, "ACCESS_KEY", "s3cret")
    body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    r = client.post("/mcp", json=body, headers=HEADERS)
    assert r.status_code == 401 and "Bearer" in r.headers["www-authenticate"]
    assert client.post("/mcp", json=body, headers=dict(HEADERS, Authorization="Bearer s3cret")).status_code == 200


def test_bedrock_provider_uses_converse(monkeypatch):
    monkeypatch.setattr(config, "AWS_BEDROCK_ENABLED", True)
    calls = []

    class FakeBedrock:
        def converse(self, **kw):
            calls.append(kw)
            return {"output": {"message": {"content": [{"text": "Hello from Nova"}]}}, "usage": {"inputTokens": 12, "outputTokens": 4}}

    monkeypatch.setattr(router, "_bedrock_client", FakeBedrock())
    out = asyncio.run(router.complete("strategy", "You plan.", "Plan a week", temperature=1.3, max_tokens=50))
    assert out == "Hello from Nova" and router.provider == "bedrock"
    assert calls[0]["modelId"] == config.AWS_BEDROCK_MODEL_ULTRA and calls[0]["inferenceConfig"] == {"maxTokens": 50, "temperature": 1.0}
    assert calls[0]["system"] == [{"text": "You plan."}] and calls[0]["messages"][0]["content"] == [{"text": "Plan a week"}]
    asyncio.run(router.complete("format_seo", "s", "u"))
    assert calls[1]["modelId"] == config.AWS_BEDROCK_MODEL_NANO and not calls[1]["system"][0]["text"].startswith("/no_think")
    assert router.records[-1].prompt_tokens is not None
    monkeypatch.setattr(router, "_bedrock_client", None)
