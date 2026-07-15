"""
ENEA Mapper — prompt builders, tool JSON schemas, and response validators.

This module is pure (standard-library only) so the framework-independent logic
(prompt assembly, schema definitions, validation + cleaning) can be unit-tested
without FastAPI/httpx installed.

Two Anthropic calls are driven from here:
  1. Evidence gathering  (web_search enabled, then forced `submit_result`)
  2. Map building        (no search, forced `submit_result`)

Both use a tool named `submit_result` with `tool_choice` forcing, so the model
must return schema-valid JSON — no regex/fence parsing.
"""

INDICATORS = ["autonomy", "dignity", "performance", "accountability", "equity"]
NODE_TYPES = ["human", "nonhuman", "prescription"]
QUADRANTS = ["training", "design", "downstream"]
TOOL_ID = "TOOL"

# ─────────────────────────────────────────────────────────────────────────────
# Tool schemas (input_schema for the forced `submit_result` tool)
# ─────────────────────────────────────────────────────────────────────────────

EVIDENCE_TOOL = {
    "name": "submit_result",
    "description": (
        "Restituisci le fonti primarie raccolte per il tool analizzato. "
        "Massimo 8 fonti. Non inventare URL: usa solo pagine effettivamente consultate."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sources": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Identificativo breve, es. S1, S2 …"},
                        "title": {"type": "string", "description": "Titolo della pagina/documento"},
                        "url": {"type": "string", "description": "URL primario e diretto"},
                        "claim": {
                            "type": "string",
                            "description": "Affermazione che la fonte supporta, in italiano, max 14 parole",
                        },
                    },
                    "required": ["id", "title", "url", "claim"],
                },
            }
        },
        "required": ["sources"],
    },
}

MAP_TOOL = {
    "name": "submit_result",
    "description": (
        "Restituisci la mappa ENEA (attori-rete) del tool analizzato, seguendo "
        "la struttura della Figura 1 del paper. Ogni nodo e ogni arco porta un "
        "campo 'ev' con gli id delle fonti che lo documentano, oppure null se è "
        "un'inferenza analitica. Non attribuire mai una fonte a un'affermazione "
        "che la fonte non supporta."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tool": {
                "type": "object",
                "description": "Il tool analizzato: 'double boundary object' a cavallo del confine upstream/downstream.",
                "properties": {
                    "label": {"type": "string"},
                    "ev": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                    },
                },
                "required": ["label", "ev"],
            },
            "nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "label": {"type": "string"},
                        "type": {"type": "string", "enum": NODE_TYPES,
                                 "description": "human=attante umano (rettangolo arrotondato), "
                                                "nonhuman=attante non-umano (rettangolo), "
                                                "prescription=prescrizione (parallelogramma)"},
                        "quadrant": {"type": "string", "enum": QUADRANTS,
                                     "description": "training=MODEL TRAINING (sx), design=MODEL DESIGN & "
                                                    "DEVELOPMENT (dx), downstream=applicazione in aula"},
                        "note": {"type": "string", "description": "Descrizione breve per il pannello dettagli"},
                        "sub": {"type": "boolean",
                                "description": "true solo sul nodo 'studenti', se suddivisibile in sotto-blocchi (equità)"},
                        "ev": {"type": ["array", "null"], "items": {"type": "string"}},
                    },
                    "required": ["id", "label", "type", "quadrant", "ev"],
                },
            },
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from": {"type": "string", "description": "id del nodo di partenza, o 'TOOL'"},
                        "to": {"type": "string", "description": "id del nodo di arrivo, o 'TOOL'"},
                        "ind": {
                            "type": "array",
                            "items": {"type": "string", "enum": INDICATORS},
                            "description": "indicatori Brusseau che questo arco 'illumina'",
                        },
                        "x": {"type": "boolean",
                              "description": "true se l'arco attraversa un confine strutturale (boundary crossing)"},
                        "ev": {"type": ["array", "null"], "items": {"type": "string"}},
                    },
                    "required": ["from", "to", "ind", "ev"],
                },
            },
        },
        "required": ["tool", "nodes", "edges"],
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

EVIDENCE_SYSTEM = (
    "Sei un ricercatore che raccoglie fonti PRIMARIE su un tool di IA generativa "
    "usato in contesto educativo, per un'analisi ENEA (Ethical Network Evaluation "
    "for AI). Privilegia documentazione ufficiale del fornitore, ToS, pagine "
    "aziendali, report ufficiali, documentazione tecnica. Evita blog secondari, "
    "notizie di terze parti e contenuti generati. "
    "Prima usa lo strumento di ricerca web per verificare i fatti su fonti primarie; "
    "poi restituisci il risultato chiamando lo strumento submit_result. "
    "Non inventare mai un URL: includi solo pagine che hai effettivamente aperto. "
    "Se non trovi una fonte primaria affidabile per un tema, ometti quel tema."
)


def evidence_user_prompt(name: str, use: str, context: str) -> str:
    return f"""Tool da analizzare:
- Nome: {name}
- Uso in aula: {use}
- Contesto educativo: {context}

Cerca fonti PRIMARIE che coprano esattamente questi temi (uno o più per fonte):
(a) proprietà e governance aziendale, incluso chi fornisce il modello di base;
(b) investitori e finanziamenti;
(c) missione/obiettivi dichiarati di ciascuna organizzazione coinvolta;
(d) modello di business / modello di ricavo;
(e) dati di addestramento secondo la documentazione ufficiale;
(f) accesso e prezzi, incluse le fasce education (rilevanti per l'equità).

Restituisci al massimo 8 fonti tramite submit_result. Per ciascuna: un id (S1, S2, …),
il titolo, l'URL primario e diretto, e una 'claim' in italiano (max 14 parole) che
descriva ciò che la fonte effettivamente supporta."""


MAP_SYSTEM = """Sei un analista che applica il metodo ENEA (Ethical Network Evaluation for AI) — Balzan, Munarini & Angeli (2024), AIED 2024. Combini l'Actor-Network Theory di Latour con gli indicatori di impatto umano di Brusseau per mappare come le PRESCRIZIONI (valori/interessi) si propagano dalla costruzione del modello fino alla relazione studente-docente.

Devi produrre una mappa che replichi la struttura della Figura 1 del paper.

DUE CONFINI STRUTTURALI:
- Un confine ORIZZONTALE separa "Upstream (costruzione del modello)" da "Downstream (applicazione in aula)".
- Un confine VERTICALE interno all'upstream separa "MODEL TRAINING" (sinistra) da "MODEL DESIGN & DEVELOPMENT" (destra).

QUADRANTI (campo quadrant di ogni nodo):
- training  = MODEL TRAINING: piattaforme, contributori, dataset (es. per Copilot: StackExchange, GitHub, i loro contributori/piattaforme, i "linguaggi di programmazione", i progetti/risposte usati come dati).
- design    = MODEL DESIGN & DEVELOPMENT: aziende, capogruppo, investitori, board, modello di base (es. per Copilot: GitHub azienda, Microsoft, OpenAI azienda/board/investitori, il modello base tipo Codex).
- downstream = applicazione in aula: studenti, docenti, istituzioni educative.

NOTAZIONE (campo type):
- human       = attante UMANO (rettangolo arrotondato): studenti, docenti, contributori, board, investitori (persone/collettivi umani).
- nonhuman    = attante NON-UMANO (rettangolo): aziende, piattaforme, dataset, modello di base, linguaggi, istituzioni.
- prescription = PRESCRIZIONE (parallelogramma): NON è un'etichetta di arco, è un NODO. Le prescrizioni si propagano tramite gli archi.

PRESCRIZIONI OBBLIGATORIE (2-3 nodi type=prescription):
1. una economica a monte (es. "Massimizzazione del RoI" / modello di business), quadrant design o training;
2. una di missione (es. la missione dichiarata dell'organizzazione, tipo "Missione OpenAI: perseguire l'AGI"), quadrant design;
3. una educativa a valle (es. "Massimizzazione dell'impatto educativo"), quadrant downstream.
Ciascuna prescrizione deve avere archi che la collegano verso il tool e/o verso studenti/docenti, così da mostrarne la propagazione.

IL TOOL come "double boundary object" (Star & Griesemer): è l'oggetto analizzato, a cavallo del confine orizzontale. NON inserirlo tra i nodes: va nel campo "tool". Negli archi usa l'id speciale "TOOL" per riferirti ad esso.

ARCHI (edges) = propagazione delle prescrizioni (frecce):
- Devono collegare gli attori/prescrizioni fino a raggiungere il tool e, a valle, studenti e docenti.
- Campo ind: sottoinsieme di ["autonomy","dignity","performance","accountability","equity"] — gli indicatori che quell'arco "illumina". Nel complesso TUTTI E CINQUE gli indicatori devono comparire in almeno un arco.
- Campo x: true se l'arco attraversa un confine strutturale (boundary crossing). Esempio dal paper: gli studenti pubblicano codice che rientra nei dati di addestramento (downstream -> training).

CAMPO sub: metti sub=true sul nodo "studenti" se il blocco è suddivisibile in sotto-blocchi con benefici diversi (aggancio all'equità).

DISCIPLINA EPISTEMICA (regola dura):
- Ogni nodo e ogni arco porta un campo "ev": lista di id di fonti (es. ["S1","S3"]) se documentato dalle fonti fornite, oppure null se è un'inferenza analitica.
- Non attribuire MAI una fonte a un'affermazione che la fonte non supporta. Nel dubbio usa null.
- Se non ti vengono fornite fonti, tutti gli ev sono null.

Adatta il numero di nodi per quadrante a ciò che le fonti e l'analisi suggeriscono. Etichette brevi; nomi propri invariati; prescrizioni in italiano. Restituisci SOLO tramite submit_result."""


def map_user_prompt(name: str, use: str, context: str, sources: list) -> str:
    if sources:
        lines = "\n".join(
            f"- {s['id']}: {s['title']} — «{s['claim']}» ({s['url']})" for s in sources
        )
        ev_block = (
            "Fonti disponibili (usa questi id nel campo ev, solo dove pertinenti):\n" + lines
        )
    else:
        ev_block = (
            "Nessuna fonte primaria è stata raccolta: imposta ev=null ovunque. "
            "La mappa sarà interamente inferenziale."
        )
    return f"""Tool da mappare:
- Nome: {name}
- Uso in aula: {use}
- Contesto educativo: {context}

{ev_block}

Costruisci la mappa ENEA di {name} replicando la struttura della Figura 1:
lato training (piattaforme/contributori/dataset), lato design & development
(aziende/capogruppo/investitori/board/modello base), e a valle studenti, docenti,
istituzioni educative. Includi 2-3 prescrizioni (una economica a monte, una di
missione, una educativa a valle) e mostra come si propagano attraverso {name} verso
studenti e docenti. Copri tutti e cinque gli indicatori con almeno un arco. Restituisci
tramite submit_result."""


# ─────────────────────────────────────────────────────────────────────────────
# Validation + cleaning
# ─────────────────────────────────────────────────────────────────────────────

def _is_str(x):
    return isinstance(x, str) and x.strip() != ""


def validate_evidence(obj):
    """Return (ok, cleaned, error). Zero sources is valid (interpretive-draft mode)."""
    if not isinstance(obj, dict) or not isinstance(obj.get("sources"), list):
        return False, None, "manca l'array 'sources'"
    cleaned = []
    for i, s in enumerate(obj["sources"][:8]):
        if not isinstance(s, dict):
            continue
        title = s.get("title")
        url = s.get("url")
        claim = s.get("claim")
        sid = s.get("id")
        if not (_is_str(title) and _is_str(url) and _is_str(claim)):
            continue
        if not _is_str(sid):
            sid = f"S{len(cleaned) + 1}"
        cleaned.append({
            "id": sid.strip(),
            "title": title.strip(),
            "url": url.strip(),
            "claim": claim.strip(),
        })
    # de-duplicate ids
    seen = {}
    for idx, s in enumerate(cleaned):
        base = s["id"]
        if base in seen:
            s["id"] = f"{base}_{idx}"
        seen[s["id"]] = True
    return True, {"sources": cleaned}, None


def validate_map(obj):
    """Return (ok, cleaned, error). Drops malformed nodes/edges; keeps valid ones."""
    if not isinstance(obj, dict):
        return False, None, "risposta non è un oggetto"
    tool = obj.get("tool")
    if not isinstance(tool, dict) or not _is_str(tool.get("label")):
        return False, None, "manca 'tool.label'"
    if not isinstance(obj.get("nodes"), list) or not isinstance(obj.get("edges"), list):
        return False, None, "mancano 'nodes' o 'edges'"

    def clean_ev(ev):
        if isinstance(ev, list):
            return [e for e in ev if _is_str(e)] or None
        return None

    nodes = []
    ids = set()
    for n in obj["nodes"]:
        if not isinstance(n, dict):
            continue
        nid = n.get("id")
        label = n.get("label")
        ntype = n.get("type")
        quad = n.get("quadrant")
        if not (_is_str(nid) and _is_str(label)):
            continue
        if ntype not in NODE_TYPES:
            ntype = "nonhuman"
        if quad not in QUADRANTS:
            quad = "design"
        nid = nid.strip()
        if nid in ids or nid == TOOL_ID:
            continue
        ids.add(nid)
        node = {
            "id": nid,
            "label": label.strip(),
            "type": ntype,
            "quadrant": quad,
            "ev": clean_ev(n.get("ev")),
        }
        if _is_str(n.get("note")):
            node["note"] = n["note"].strip()
        if n.get("sub") is True:
            node["sub"] = True
        nodes.append(node)

    if not nodes:
        return False, None, "nessun nodo valido"

    edges = []
    valid_targets = ids | {TOOL_ID}
    for e in obj["edges"]:
        if not isinstance(e, dict):
            continue
        frm = e.get("from")
        to = e.get("to")
        if not (_is_str(frm) and _is_str(to)):
            continue
        frm, to = frm.strip(), to.strip()
        if frm not in valid_targets or to not in valid_targets or frm == to:
            continue
        ind = e.get("ind")
        ind = [x for x in ind if x in INDICATORS] if isinstance(ind, list) else []
        edge = {"from": frm, "to": to, "ind": ind, "ev": clean_ev(e.get("ev"))}
        if e.get("x") is True:
            edge["x"] = True
        edges.append(edge)

    cleaned = {
        "tool": {"label": tool["label"].strip(), "ev": clean_ev(tool.get("ev"))},
        "nodes": nodes,
        "edges": edges,
    }
    return True, cleaned, None
