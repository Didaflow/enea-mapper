"""
Anthropic proxy logic for ENEA Mapper.

Both endpoints force structured output with `tool_choice` on a tool named
`submit_result`. The evidence endpoint additionally enables the web_search
server tool. Because forcing `submit_result` from the start would prevent the
model from searching, evidence gathering runs in two internal steps:

  1. tool_choice=auto with web_search + submit_result available  -> model searches
  2. if the model didn't already emit submit_result, a forced tool_choice call
     structures the gathered evidence into schema-valid JSON.

Each endpoint validates the result and retries ONCE on validation failure.
"""

import os
import httpx

import prompts

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 6}
MAX_TOKENS = 4096
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicError(RuntimeError):
    pass


def _headers():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise AnthropicError("ANTHROPIC_API_KEY non impostata (vedi .env.example)")
    return {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


async def _post(client: httpx.AsyncClient, body: dict) -> dict:
    resp = await client.post(ANTHROPIC_URL, headers=_headers(), json=body, timeout=120.0)
    if resp.status_code >= 400:
        detail = resp.text[:600]
        raise AnthropicError(f"Anthropic API {resp.status_code}: {detail}")
    return resp.json()


def _find_tool_use(content, name="submit_result"):
    for block in content or []:
        if block.get("type") == "tool_use" and block.get("name") == name:
            return block.get("input")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Map endpoint — single forced call + one retry
# ─────────────────────────────────────────────────────────────────────────────

async def build_map(name, use, context, sources):
    system = prompts.MAP_SYSTEM
    user = prompts.map_user_prompt(name, use, context, sources)
    async with httpx.AsyncClient() as client:
        messages = [{"role": "user", "content": user}]
        last_err = None
        for attempt in range(2):  # initial + one retry
            body = {
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "system": system,
                "tools": [prompts.MAP_TOOL],
                "tool_choice": {"type": "tool", "name": "submit_result"},
                "messages": messages,
            }
            data = await _post(client, body)
            payload = _find_tool_use(data.get("content"))
            ok, cleaned, err = prompts.validate_map(payload or {})
            if ok:
                return cleaned
            last_err = err
            # feed the error back for the retry
            messages = [
                {"role": "user", "content": user},
                {"role": "user", "content":
                    f"La risposta precedente non era valida ({err}). "
                    "Richiama submit_result con una mappa corretta e completa."},
            ]
        raise AnthropicError(f"Mappa non valida dopo il retry: {last_err}")


# ─────────────────────────────────────────────────────────────────────────────
# Evidence endpoint — search (auto) then forced structuring + one retry
# ─────────────────────────────────────────────────────────────────────────────

async def gather_evidence(name, use, context):
    system = prompts.EVIDENCE_SYSTEM
    user = prompts.evidence_user_prompt(name, use, context)
    async with httpx.AsyncClient() as client:
        messages = [{"role": "user", "content": user}]

        # Step 1: let the model search the web (auto tool choice). The web_search
        # server tool executes inside the call; handle pause_turn continuations.
        data = None
        for _ in range(6):
            body = {
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "system": system,
                "tools": [WEB_SEARCH_TOOL, prompts.EVIDENCE_TOOL],
                "tool_choice": {"type": "auto"},
                "messages": messages,
            }
            data = await _post(client, body)
            if data.get("stop_reason") == "pause_turn":
                messages.append({"role": "assistant", "content": data.get("content")})
                continue
            break

        payload = _find_tool_use(data.get("content")) if data else None

        # Step 2: if the model didn't emit submit_result, force it now.
        if payload is None and data is not None:
            messages.append({"role": "assistant", "content": data.get("content")})
            messages.append({"role": "user", "content":
                "Ora restituisci le fonti primarie raccolte chiamando submit_result "
                "(massimo 8, con id, title, url e claim in italiano ≤14 parole)."})
            payload = await _forced_evidence(client, system, messages)

        ok, cleaned, err = prompts.validate_evidence(payload or {})
        if ok:
            return cleaned["sources"]

        # One retry: force again with the validation error surfaced.
        messages.append({"role": "user", "content":
            f"La risposta non era valida ({err}). Richiama submit_result con l'array 'sources' corretto."})
        payload = await _forced_evidence(client, system, messages)
        ok, cleaned, err = prompts.validate_evidence(payload or {})
        if ok:
            return cleaned["sources"]
        # Never hard-fail evidence: an empty source set is a valid (interpretive) state.
        return []


async def _forced_evidence(client, system, messages):
    body = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system,
        # keep web_search declared so prior server-tool blocks stay referenced,
        # but force submit_result so the model must return structured JSON.
        "tools": [WEB_SEARCH_TOOL, prompts.EVIDENCE_TOOL],
        "tool_choice": {"type": "tool", "name": "submit_result"},
        "messages": messages,
    }
    data = await _post(client, body)
    return _find_tool_use(data.get("content"))
