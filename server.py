"""
ENEA Mapper — minimal backend proxy.

Exposes:
  POST /api/evidence  -> {name, use, context} -> {sources:[{id,title,url,claim}], accessed}
  POST /api/map       -> {name, use, context, sources} -> {tool, nodes, edges}

Serves the static single-page frontend from ./public.
"""

import datetime
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

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import anthropic_client
from anthropic_client import AnthropicError

app = FastAPI(title="ENEA Mapper")

PUBLIC_DIR = Path(__file__).parent / "public"


class ToolInput(BaseModel):
    name: str
    use: str = ""
    context: str = ""


class MapInput(ToolInput):
    sources: list = []


@app.post("/api/evidence")
async def api_evidence(inp: ToolInput):
    if not inp.name.strip():
        raise HTTPException(status_code=400, detail="Il nome del tool è obbligatorio.")
    try:
        sources = await anthropic_client.gather_evidence(
            inp.name.strip(), inp.use.strip(), inp.context.strip()
        )
    except AnthropicError as e:
        raise HTTPException(status_code=502, detail=str(e))
    accessed = datetime.date.today().isoformat()
    for s in sources:
        s["accessed"] = accessed
    return {"sources": sources, "accessed": accessed}


@app.post("/api/map")
async def api_map(inp: MapInput):
    if not inp.name.strip():
        raise HTTPException(status_code=400, detail="Il nome del tool è obbligatorio.")
    try:
        result = await anthropic_client.build_map(
            inp.name.strip(), inp.use.strip(), inp.context.strip(), inp.sources or []
        )
    except AnthropicError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result


@app.get("/api/health")
async def health():
    return {"ok": True}


# Static frontend (mounted last so /api/* wins). html=True serves index.html at /.
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")


@app.exception_handler(AnthropicError)
async def _anthropic_error_handler(request, exc):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("server:app", host="127.0.0.1", port=port, reload=False)
