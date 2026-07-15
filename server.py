"""
ENEA Mapper — minimal backend proxy.

Exposes:
  POST /api/evidence  -> {name, use, context} -> {sources:[{id,title,url,claim}], accessed}
  POST /api/map       -> {name, use, context, sources} -> {tool, nodes, edges}

Serves the static single-page frontend from ./public.
"""

import datetime
import json
import os
from pathlib import Path


def _load_dotenv():
    """Minimal .env loader (no python-dotenv dependency). KEY=VALUE per line."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


_load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import anthropic_client
from anthropic_client import AnthropicError
from limits import TTLCache, RateLimiter, DailyBudget, cache_key

app = FastAPI(title="ENEA Mapper")

PUBLIC_DIR = Path(__file__).parent / "public"

# ── Cost/abuse guardrails (tunable via env; see .env.example) ──
_cache = TTLCache(ttl=int(os.environ.get("CACHE_TTL_SECONDS", "86400")))
_ratelimit = RateLimiter(
    int(os.environ.get("RATE_LIMIT_PER_IP", "10")),
    int(os.environ.get("RATE_WINDOW_SECONDS", "3600")),
)
_budget = DailyBudget(int(os.environ.get("DAILY_API_BUDGET", "300")))


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_rate(request: Request):
    ok, retry = _ratelimit.allow(_client_ip(request))
    if not ok:
        raise HTTPException(
            status_code=429,
            detail=f"Troppe richieste da questo indirizzo. Riprova tra ~{max(1, retry // 60)} min.",
        )


def _spend_or_429():
    if not _budget.check_and_inc():
        raise HTTPException(
            status_code=429,
            detail="Quota giornaliera del servizio esaurita. Riprova domani.",
        )


class ToolInput(BaseModel):
    name: str
    use: str = ""
    context: str = ""


class MapInput(ToolInput):
    sources: list = []


@app.post("/api/evidence")
async def api_evidence(inp: ToolInput, request: Request):
    if not inp.name.strip():
        raise HTTPException(status_code=400, detail="Il nome del tool è obbligatorio.")
    _enforce_rate(request)
    name, use, context = inp.name.strip(), inp.use.strip(), inp.context.strip()

    key = cache_key("evidence", name, use, context)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    _spend_or_429()  # only cache misses consume the daily budget
    try:
        sources = await anthropic_client.gather_evidence(name, use, context)
    except AnthropicError as e:
        raise HTTPException(status_code=502, detail=str(e))
    accessed = datetime.date.today().isoformat()
    for s in sources:
        s["accessed"] = accessed
    result = {"sources": sources, "accessed": accessed}
    _cache.set(key, result)
    return result


@app.post("/api/map")
async def api_map(inp: MapInput, request: Request):
    if not inp.name.strip():
        raise HTTPException(status_code=400, detail="Il nome del tool è obbligatorio.")
    _enforce_rate(request)
    name, use, context = inp.name.strip(), inp.use.strip(), inp.context.strip()
    sources = inp.sources or []

    key = cache_key("map", name, use, context, json.dumps(sources, sort_keys=True, ensure_ascii=False))
    cached = _cache.get(key)
    if cached is not None:
        return cached

    _spend_or_429()
    try:
        result = await anthropic_client.build_map(name, use, context, sources)
    except AnthropicError as e:
        raise HTTPException(status_code=502, detail=str(e))
    _cache.set(key, result)
    return result


@app.get("/api/health")
async def health():
    return {"ok": True, "daily_budget_remaining": _budget.remaining()}


# Static frontend (mounted last so /api/* wins). html=True serves index.html at /.
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")


@app.exception_handler(AnthropicError)
async def _anthropic_error_handler(request, exc):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("server:app", host="127.0.0.1", port=port, reload=False)
