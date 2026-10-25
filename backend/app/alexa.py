"""Simulated Alexa+ experience (the hackathon's web-simulation path).

A spoken or typed request is turned into an MCP tool call, which is sent as a real JSON-RPC
message through the same handler that serves /mcp. The response carries what Alexa would say,
a card to show on a screen device, and the JSON-RPC exchange itself so the demo can show it.

Intent routing uses the configured model (Nemotron or Bedrock) with the MCP tool schemas, the
way Alexa+ picks tools; without a model it falls back to keyword rules.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from . import mcp_server
from .llm import LLMError, router as llm
from .store import store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/alexa", tags=["Alexa+ simulation"])

_last_campaign: dict[str, str] = {}  # session -> campaign id the user is talking about
_rpc_id = 0

_TARGET = re.compile(r"(@[\w.]{2,30})|((?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?:/[^\s]*)?)", re.I)
_DAYS = re.compile(r"(\d{1,2})\s*(?:-|\s)?days?", re.I)
_WEEKS = re.compile(r"(\d|one|two|three|four)\s*weeks?", re.I)
_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4}


class SimulateRequest(BaseModel):
    utterance: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default", max_length=64)


ROUTER_SYSTEM = """You are Alexa+, routing a user's request to one MonoPlus MCP tool.
Tools (name: purpose):
{tools}
The user's current campaign_id (if any): {campaign}
Return JSON: {{"tool": "<tool name or none>", "arguments": {{...}}, "reply": "what to say if tool is none"}}
Use tool "none" only for greetings or when a required argument (like the website) is missing; then ask for it in "reply"."""


def _latest_campaign(session: str) -> str | None:
    if session in _last_campaign and _last_campaign[session] in store.campaigns:
        return _last_campaign[session]
    if store.campaigns:
        return max(store.campaigns.values(), key=lambda c: c.created_at).id
    return None


def _after_colon(text: str) -> str:
    return text.split(":", 1)[1].strip() if ":" in text else ""


def keyword_route(utterance: str, session: str) -> tuple[str | None, dict[str, Any], str]:
    """Rule-based intent mapping used when no model is configured."""
    t = utterance.lower()
    cid = _latest_campaign(session)
    if re.search(r"\bhumani[sz]e\b|sound (more )?human|less like ai|rewrite this", t):
        text = _after_colon(utterance) or re.sub(r"(?i)^.*?(humani[sz]e( this)?|rewrite this)\s*", "", utterance).strip()
        return ("humanize_text", {"text": text}, "") if text else (None, {}, "Sure. What's the text you'd like me to make sound more human?")
    if re.search(r"\bapprove\b", t):
        return ("approve_posts", {"campaign_id": cid}, "") if cid else (None, {}, "There's no campaign to approve yet. Want me to create one?")
    if re.search(r"\b(ready|status|progress|done yet|how'?s my campaign|how is my campaign)\b", t):
        return ("get_campaign_status", {"campaign_id": cid}, "") if cid else (None, {}, "You don't have a campaign yet. Tell me your website to start one.")
    if re.search(r"\b(upcoming|scheduled|coming up|this week|next week|calendar|what'?s posting)\b", t):
        days = 14 if "next week" in t else 7
        return "list_upcoming_posts", {"days": days}, ""
    if re.search(r"\b(brand kit|brand colou?rs|my colou?rs|logo|brand profile)\b", t):
        return ("get_brand_profile", {"campaign_id": cid}, "") if cid else (None, {}, "I don't have a brand kit yet. Tell me your website first.")
    if re.search(r"\b(research|trend|trends|what do customers|what are people|competitors?|market)\b", t) and not re.search(r"\b(campaign|posts for)\b", t):
        question = re.sub(r"(?i)^(alexa,?\s*)?(please\s*)?(research|look into|find out)\s*", "", utterance).strip(" ?.") or utterance
        return "research_market", {"question": question}, ""
    if re.search(r"\b(campaign|posts|content|calendar|market my|promote)\b", t):
        m = _TARGET.search(utterance)
        if not m:
            return None, {}, "Happy to. Which website or Instagram handle should I build the campaign from?"
        days = 30
        if (d := _DAYS.search(t)):
            days = max(1, min(31, int(d.group(1))))
        elif (w := _WEEKS.search(t)):
            n = w.group(1)
            days = min(31, 7 * (int(n) if n.isdigit() else _WORDNUM[n]))
        platforms = [p for p, keys in {"instagram": ("instagram", "insta"), "linkedin": ("linkedin",), "x": (" x ", "twitter", " x."),
                                       "facebook": ("facebook",)}.items() if any(k in f" {t} " for k in keys)]
        args: dict[str, Any] = {"website_or_handle": m.group(0).rstrip(".,!?"), "days": days}
        if platforms:
            args["platforms"] = platforms
        return "create_campaign", args, ""
    return None, {}, ("I can create a social media campaign from your website, tell you what's posting this week, approve posts, "
                      "make copy sound human, or research your market. What would you like?")


async def model_route(utterance: str, session: str) -> tuple[str | None, dict[str, Any], str]:
    tools = "\n".join(f"- {t['name']}: {t['description']} Arguments: {json.dumps(t['inputSchema']['properties'])}" for t in mcp_server.TOOLS)
    data = await llm.complete_json("classify", ROUTER_SYSTEM.format(tools=tools, campaign=_latest_campaign(session) or "none"),
                                   utterance, temperature=0.0, max_tokens=500)
    tool = data.get("tool") if isinstance(data, dict) else None
    if tool not in mcp_server.TOOL_NAMES:
        return None, {}, str((data or {}).get("reply") or "Sorry, I didn't catch that.")
    args = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
    if "campaign_id" in {k for t in mcp_server.TOOLS if t["name"] == tool for k in t["inputSchema"].get("required", [])} and not args.get("campaign_id"):
        args["campaign_id"] = _latest_campaign(session)
    return tool, args, ""


def card_for(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    if tool == "create_campaign":
        return {"type": "campaign_started", **{k: result.get(k) for k in ("campaign_id", "days", "platforms", "review_url")}}
    if tool == "get_campaign_status":
        return {"type": "campaign_status", **result}
    if tool == "list_upcoming_posts":
        return {"type": "post_list", "posts": result.get("posts", [])[:6], "count": result.get("count", 0)}
    if tool == "approve_posts":
        return {"type": "approval", **result}
    if tool == "humanize_text":
        return {"type": "humanized", **result}
    if tool == "research_market":
        return {"type": "research", "insights": result.get("insights"), "sources": result.get("sources", [])[:4], "summary": result.get("summary", "")[:900]}
    if tool == "get_brand_profile":
        return {"type": "brand", **result}
    return {"type": "text"}


@router.post("/simulate")
async def simulate(req: SimulateRequest) -> dict:
    global _rpc_id
    session = req.session_id
    tool, args, reply = None, {}, ""
    routed_by = "rules"
    if llm.enabled:
        try:
            tool, args, reply = await model_route(req.utterance, session)
            routed_by = "model"
        except (LLMError, AttributeError, TypeError) as exc:
            log.info("model routing failed, using rules: %s", exc)
            tool, args, reply = keyword_route(req.utterance, session)
    else:
        tool, args, reply = keyword_route(req.utterance, session)

    if not tool:
        return {"speech": reply, "card": {"type": "text", "text": reply}, "tool": None, "routed_by": routed_by, "rpc": None}

    _rpc_id += 1
    request = {"jsonrpc": "2.0", "id": _rpc_id, "method": "tools/call", "params": {"name": tool, "arguments": args}}
    response, _ = await mcp_server.handle(request)
    result = (response or {}).get("result", {})
    if result.get("isError"):
        speech = result["content"][0]["text"]
        return {"speech": speech, "card": {"type": "error", "text": speech}, "tool": tool, "routed_by": routed_by,
                "rpc": {"request": request, "response": response}}
    structured = result.get("structuredContent", {})
    if structured.get("campaign_id"):
        _last_campaign[session] = structured["campaign_id"]
    speech = result["content"][0]["text"].split("\n\n", 1)[0]
    return {"speech": speech, "card": card_for(tool, structured), "tool": tool, "routed_by": routed_by,
            "rpc": {"request": request, "response": response}}
