# ENEA Mapper

Operationalises the **ENEA method** (Ethical Network Evaluation for AI) from
Balzan, Munarini & Angeli (2024), *"Who Pilots the Copilots? Mapping a
Generative AI's Actor-Network to Assess Its Educational Impacts"*, AIED 2024,
LNCS 14830 — [doi.org/10.1007/978-3-031-64299-9_42](https://doi.org/10.1007/978-3-031-64299-9_42).

Given a GenAI tool, its classroom use, and an educational context, ENEA Mapper:

1. **Phase 1 — Evidence gathering.** Searches **primary sources** (vendor docs,
   ToS, corporate pages, official reports) covering ownership & governance,
   investors & funding, declared missions, business model, training data, and
   access/pricing (education tiers).
2. **Phase 2 — Map building.** Builds an actor-network map that replicates the
   paper's Figure 1 — upstream *Model Training* / *Model Design & Development*
   quadrants, downstream students/teachers/institutions, prescriptions as
   parallelogram nodes, and the tool as a *double boundary object* — **constrained
   by the evidence** (every node/edge is tagged 📄 documented or ◌ inferred).
3. **ENEA interrogation.** Five fixed Brusseau indicator questions with
   map-driven path highlighting, notes, and a three-state flag (traffic light).
4. **Export.** One-click Markdown ENEA report to the clipboard.

## Architecture

- **Frontend:** static single-page app (vanilla JS + SVG), served from `public/`.
- **Backend:** minimal FastAPI proxy exposing two endpoints:
  - `POST /api/evidence` → Anthropic `claude-sonnet-4-6` **with the `web_search`
    tool**, `max_tokens = 4096`.
  - `POST /api/map` → Anthropic `claude-sonnet-4-6`, `max_tokens = 4096`, no search.

Both calls use **forced tool use** (`tool_choice`) with a JSON-schema tool named
`submit_result`, so the model must return schema-valid JSON — no regex/fence
parsing. Each call **validates and retries once** on schema failure. Because
forcing `submit_result` would block web search, the evidence endpoint first lets
the model search (`tool_choice: auto`), then forces `submit_result` to structure
the findings.

The API key never reaches the browser — it lives only in the backend `.env`.

## Setup

Requires Python 3.9+.

```bash
cd enea-mapper

# 1. Virtual environment + dependencies
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure your Anthropic API key
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...

# 3. Run
python server.py                    # or: uvicorn server:app --port 8000
```

Then open <http://127.0.0.1:8000>.

## Acceptance test

Run the pipeline with:

- **Nome:** `GitHub Copilot`
- **Uso in aula:** `Assistente AI di programmazione usato dagli studenti negli esercizi di coding`
- **Contesto:** `Corso introduttivo di programmazione, laurea triennale`

The generated map should structurally resemble Figure 1: the
StackExchange/GitHub ecosystem on the *training* side; Microsoft/OpenAI/investors
on the *design & development* side; **RoI Maximisation** and **mission**
prescriptions propagating through Copilot toward students/teachers; a downstream
**educational-impact** prescription. Divergences from 2024 (e.g. changed
Microsoft–OpenAI arrangements) are acceptable when documented by sources.

Verify: no truncation, schema-valid JSON on both calls, all five indicators
covered by at least one edge, sources clickable, accessed dates stamped.

## Cost & abuse guardrails (read before publishing)

Each analysis calls `claude-sonnet-4-6` (~$3 / 1M input, $15 / 1M output) plus a
few web searches. A typical run costs **~$0.15**, worst case **~$0.30** — the
dominant, variable cost is the web-search evidence phase. The real risk of a public
endpoint is **unbounded volume**, not the per-run price. Three defenses are built in
and tunable via `.env` (see `.env.example`):

- **Result cache** (`CACHE_TTL_SECONDS`) — identical requests (everyone tries
  "GitHub Copilot") are served from cache; only cache misses cost money.
- **Per-IP rate limit** (`RATE_LIMIT_PER_IP` / `RATE_WINDOW_SECONDS`) — caps loops
  from a single client (HTTP 429 when exceeded).
- **Daily budget** (`DAILY_API_BUDGET`) — a hard cap on billable runs per UTC day;
  past it the service returns 429 until the next day, bounding daily spend.
- **`WEB_SEARCH_MAX_USES`** — caps the variable search cost per run (default 4).

**Do this before going public:** (1) use a **dedicated Anthropic API key** in a
workspace with a **monthly spend limit** set in the Console — the ultimate safety
net; (2) keep the tool behind the Didaflow site / an access code rather than fully
open. State is per-process: run a **single worker** (default), or back the
guardrails with Redis for multi-worker deployments.

`GET /api/health` reports `daily_budget_remaining`.

## Files

```
server.py            FastAPI app + endpoints + static serving + .env loader
anthropic_client.py  Anthropic proxy: forced tool use, search→structure, retry
prompts.py           Prompts, submit_result JSON schemas, validators (pure stdlib)
limits.py            Cache + per-IP rate limit + daily budget (in-memory)
public/              index.html · styles.css · app.js  (the SPA)
requirements.txt     fastapi · uvicorn · httpx
.env.example         key + guardrail settings
```

## Notes

- Model is pinned to `claude-sonnet-4-6` as specified.
- The five ENEA questions are **fixed** (they are the framework) and are only
  parametrised on the tool name — they are never regenerated by the model.
- ENEA maps are contingent constructions, not static objects; declared inference
  (◌) is a transparency feature, and flags signal *further investigation*, not
  condemnation (paper, Sec. 5).
