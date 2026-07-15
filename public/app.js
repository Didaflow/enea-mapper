/* ENEA Mapper — frontend controller
   Pipeline: /api/evidence (web search) -> /api/map (constrained by evidence)
   Renders a Figure-1 quadrant map, fixed Brusseau interrogation, and export. */

'use strict';

// ─── Fixed framework data ──────────────────────────────────────────────────
const INDICATORS = ['autonomy', 'dignity', 'performance', 'accountability', 'equity'];

const INDICATOR_META = {
  autonomy:       { label: 'Autonomia' },
  dignity:        { label: 'Dignità' },
  performance:    { label: 'Performance' },
  accountability: { label: 'Accountability' },
  equity:         { label: 'Equità' },
};

// The five questions ARE the framework — never regenerated, only parametrised on {T}.
const PRINCIPLES = [
  {
    key: 'autonomy', label: 'Autonomia',
    blurb: "Studenti e docenti devono poter co-definire le proprie regole, senza che l'AI veicoli interferenze esterne.",
    q: "{T} incorpora delle 'regole' (prescrizioni) nel suo design? Da chi originano? Segui la mappa: qualcuna di queste regole raggiunge la relazione studente-docente, passando per {T}?",
  },
  {
    key: 'dignity', label: 'Dignità',
    blurb: 'Gli studenti devono poter usare i tool AI esclusivamente per imparare, senza che servano scopi altrui.',
    q: 'Quali altri fini sono incorporati nel design di {T}? Da chi originano? Segui la mappa: qualcuno di questi fini raggiunge gli studenti, passando per {T}?',
  },
  {
    key: 'performance', label: 'Performance',
    blurb: "L'output dei tool AI deve essere costantemente funzionale, efficace ed efficiente.",
    q: 'Cosa può alterare la qualità degli output di {T}? Chi influisce sulla qualità? Segui la mappa: sorgenti di performance diverse dall’input degli studenti raggiungono il blocco {T}?',
  },
  {
    key: 'accountability', label: 'Accountability',
    blurb: 'Studenti e docenti devono riconoscere quando i tool decidono, come, e di chi è la responsabilità degli output.',
    q: "Chi o cosa è all'origine dei suggerimenti di {T}? Gli studenti possono riconoscerlo? Segui la mappa: esiste un percorso che permette agli studenti di risalire all'origine?",
  },
  {
    key: 'equity', label: 'Equità',
    blurb: 'Tutti gli studenti nelle classi che usano il tool devono poterlo sfruttare efficacemente.',
    q: "Nella stessa classe, alcuni studenti possono usare {T} produttivamente mentre altri ricevono meno benefici? Il blocco 'studenti' può essere suddiviso in sotto-blocchi con benefici diversi?",
  },
];

const FLAG_STATES = [
  { v: 'green', cls: 'green', label: 'Nessun flag' },
  { v: 'amber', cls: 'amber', label: 'Da approfondire' },
  { v: 'red',   cls: 'red',   label: 'Indagine necessaria' },
];

const EXAMPLES = [
  { name: 'GitHub Copilot', use: 'Assistente AI di programmazione usato dagli studenti negli esercizi di coding', context: 'Corso introduttivo di programmazione, laurea triennale' },
  { name: 'ChatGPT', use: 'Chatbot generalista usato dagli studenti per completare i compiti scritti', context: 'Corso di laurea triennale in economia' },
  { name: 'Maurice (Didaflow)', use: 'Agente AI che supporta studenti e docenti con i dati del corso', context: 'Executive education, business school' },
];

const TYPE_LABEL = { human: 'ATTANTE UMANO', nonhuman: 'ATTANTE NON-UMANO', prescription: 'PRESCRIZIONE' };
const QUADRANT_LABEL = {
  training: 'Upstream · Model Training',
  design: 'Upstream · Model Design & Development',
  downstream: 'Downstream · applicazione in aula',
};
const TOOL_ID = 'TOOL';

// ─── State ─────────────────────────────────────────────────────────────────
const state = {
  tool: { name: '', use: '', context: '' },
  sources: [],
  accessed: '',
  map: null,
  layout: null,      // { boxes: {id: {x,y,w,h,...}}, tool: box }
  activeInd: null,
  selected: null,    // node id or '__tool__'
  flags: {},
  notes: {},
};

// ─── DOM helpers ───────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function setPhase(n, status) {
  const el = document.querySelector(`.phase[data-phase="${n}"]`);
  if (el) el.setAttribute('data-status', status);
}
function banner(el, kind, text) {
  el.innerHTML = text ? `<div class="banner banner-${kind}">${esc(text)}</div>` : '';
}

// ─── Pipeline ──────────────────────────────────────────────────────────────
async function run() {
  const name = $('in-name').value.trim();
  const use = $('in-use').value.trim();
  const context = $('in-context').value.trim();
  banner($('input-banner'), 'error', '');
  if (!name) { banner($('input-banner'), 'error', 'Inserisci almeno il nome del tool.'); return; }

  state.tool = { name, use, context };
  state.sources = []; state.map = null; state.layout = null;
  state.activeInd = null; state.selected = null; state.flags = {}; state.notes = {};
  $('sources-section').style.display = 'none';
  $('map-section').style.display = 'none';
  $('questions-section').style.display = 'none';

  const searchEnabled = $('opt-search') && $('opt-search').checked;
  const btn = $('btn-run');
  btn.disabled = true;
  btn.textContent = searchEnabled ? 'Raccolgo le evidenze…' : 'Costruisco la mappa…';
  setPhase(1, searchEnabled ? 'active' : 'done'); setPhase(2, 'idle');
  $('loading').style.display = 'block';

  try {
    // Phase 1 — evidence (optional: needs high API limits)
    if (searchEnabled) {
      const ev = await postJSON('/api/evidence', { name, use, context });
      state.sources = ev.sources || [];
      state.accessed = ev.accessed || new Date().toISOString().slice(0, 10);
      setPhase(1, 'done');
    } else {
      state.sources = [];
      state.accessed = new Date().toISOString().slice(0, 10);
    }
    renderSources();
    $('sources-section').style.display = 'block';

    // Phase 2 — map
    btn.textContent = 'Costruisco la mappa…';
    setPhase(2, 'active');
    const map = await postJSON('/api/map', { name, use, context, sources: state.sources });
    state.map = map;
    setPhase(2, 'done');
    renderMap();
    renderQuestions();
    $('map-section').style.display = 'block';
    $('questions-section').style.display = 'block';
  } catch (e) {
    const active = document.querySelector('.phase[data-status="active"]');
    if (active) active.setAttribute('data-status', 'error');
    banner($('input-banner'), 'error', 'Errore: ' + (e.message || e));
  } finally {
    $('loading').style.display = 'none';
    btn.disabled = false; btn.textContent = 'Genera la mappa ENEA';
  }
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

// ─── Sources panel ─────────────────────────────────────────────────────────
function renderSources() {
  const grid = $('sources-grid');
  const b = $('sources-banner');
  if (!state.sources.length) {
    banner(b, 'warn', 'Nessuna fonte primaria trovata: la mappa è interamente inferenziale. Trattala come bozza interpretativa, non come ricostruzione documentata.');
    grid.innerHTML = '';
    return;
  }
  b.innerHTML = '';
  grid.innerHTML = state.sources.map((s) => `
    <div class="source-card" id="src-${esc(s.id)}">
      <div class="source-id">[${esc(s.id)}]</div>
      <div class="source-title">${esc(s.title)}</div>
      <div class="source-claim">«${esc(s.claim)}»</div>
      <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a>
      <div class="source-meta">consultato ${esc(s.accessed || state.accessed)}</div>
    </div>`).join('');
}

function flashSource(id) {
  const el = $('src-' + id);
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
}

// ─── Map layout (Figure 1: quadrants + boundaries) ─────────────────────────
const VB = { W: 1080, H: 744, vline: 540, boundaryY: 466 };

function layoutMap(map) {
  const regions = {
    training:   { x0: 22,  x1: 524,  y0: 74,  y1: 406, cols: 3 },
    design:     { x0: 556, x1: 1058, y0: 74,  y1: 406, cols: 3 },
    downstream: { x0: 22,  x1: 1058, y0: 512, y1: 724, cols: 4 },
  };
  const byQuad = { training: [], design: [], downstream: [] };
  map.nodes.forEach((n) => (byQuad[n.quadrant] || byQuad.design).push(n));

  const boxes = {};
  for (const q of Object.keys(byQuad)) {
    const nodes = byQuad[q];
    const r = regions[q];
    const n = nodes.length;
    if (!n) continue;
    const cols = Math.min(r.cols, n);
    const rows = Math.ceil(n / cols);
    const cellW = (r.x1 - r.x0) / cols;
    const cellH = (r.y1 - r.y0) / rows;
    nodes.forEach((node, i) => {
      const col = i % cols, row = Math.floor(i / cols);
      // center the last (possibly short) row
      const rowStart = row * cols;
      const inRow = Math.min(cols, n - rowStart);
      const rowOffset = (cols - inRow) * cellW / 2;
      const cx = r.x0 + rowOffset + cellW * (col + 0.5);
      const cy = r.y0 + cellH * (row + 0.5);
      const w = clamp(node.label.length * 6.9 + 22, 92, 152);
      boxes[node.id] = { x: cx, y: cy, w, h: 46, node };
    });
  }

  const toolLabel = map.tool.label || state.tool.name;
  const tool = { x: VB.vline, y: VB.boundaryY, w: clamp(toolLabel.length * 8 + 30, 150, 220), h: 56, label: toolLabel };
  return { boxes, tool };
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

function boxCenter(id) {
  if (id === TOOL_ID) return state.layout.tool;
  return state.layout.boxes[id];
}

function borderPoint(box, tx, ty) {
  const dx = tx - box.x, dy = ty - box.y;
  if (dx === 0 && dy === 0) return { x: box.x, y: box.y };
  const hw = box.w / 2 + 2, hh = box.h / 2 + 2;
  const sx = dx !== 0 ? hw / Math.abs(dx) : Infinity;
  const sy = dy !== 0 ? hh / Math.abs(dy) : Infinity;
  const s = Math.min(sx, sy);
  return { x: box.x + dx * s, y: box.y + dy * s };
}

function wrapLabel(label, w) {
  const maxChars = Math.max(6, Math.floor((w - 12) / 6.6));
  if (label.length <= maxChars) return [label];
  const words = label.split(' ');
  const lines = ['', ''];
  let li = 0;
  for (const word of words) {
    const test = lines[li] ? lines[li] + ' ' + word : word;
    if (test.length > maxChars && li === 0 && lines[1] === '') { li = 1; lines[1] = word; }
    else if (li === 1 && test.length > maxChars) { lines[1] = lines[1] + ' ' + word; }
    else lines[li] = test;
  }
  if (lines[1].length > maxChars) lines[1] = lines[1].slice(0, maxChars - 1) + '…';
  return lines[1] ? [lines[0], lines[1]] : [lines[0]];
}

function nodeShape(box, type) {
  const { x, y, w, h } = box;
  const l = x - w / 2, t = y - h / 2, r = x + w / 2, bt = y + h / 2;
  if (type === 'prescription') {
    const sk = 12;
    return `<polygon class="shape" points="${l + sk},${t} ${r},${t} ${r - sk},${bt} ${l},${bt}" />`;
  }
  const rx = type === 'human' ? 15 : 2;
  return `<rect class="shape" x="${l}" y="${t}" width="${w}" height="${h}" rx="${rx}" />`;
}

function labelTspans(label, x, y, w) {
  const lines = wrapLabel(label, w);
  if (lines.length === 1) return `<text class="label" x="${x}" y="${y + 4}" text-anchor="middle">${esc(lines[0])}</text>`;
  return `<text class="label" x="${x}" y="${y - 3}" text-anchor="middle">` +
    `<tspan x="${x}" dy="0">${esc(lines[0])}</tspan>` +
    `<tspan x="${x}" dy="14">${esc(lines[1])}</tspan></text>`;
}

function renderMap() {
  $('map-tool-name').textContent = state.map.tool.label || state.tool.name;
  state.layout = layoutMap(state.map);
  const L = state.layout;
  const { W, H, vline, boundaryY } = VB;
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Mappa ENEA della rete di attori">`;
  svg += `<defs><marker id="arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#5A5450"/></marker>`;
  svg += `<marker id="arrow-coral" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#D96D60"/></marker></defs>`;

  // boundaries
  svg += `<line class="boundary-line" x1="20" y1="${boundaryY}" x2="${W - 20}" y2="${boundaryY}" />`;
  svg += `<line class="boundary-line" x1="${vline}" y1="60" x2="${vline}" y2="${boundaryY}" />`;
  svg += `<text class="quadrant-label" x="272" y="52" text-anchor="middle">MODEL TRAINING</text>`;
  svg += `<text class="quadrant-label" x="807" y="52" text-anchor="middle">MODEL DESIGN &amp; DEVELOPMENT</text>`;
  svg += `<text class="boundary-label" x="${W - 24}" y="${boundaryY - 7}" text-anchor="end">Upstream (costruzione del modello)</text>`;
  svg += `<text class="boundary-label" x="${W - 24}" y="${boundaryY + 17}" text-anchor="end">Downstream (applicazione in aula)</text>`;

  // edges (under nodes)
  state.map.edges.forEach((e, i) => {
    const a = boxCenter(e.from), b = boxCenter(e.to);
    if (!a || !b) return;
    const p1 = borderPoint(a, b.x, b.y);
    const p2 = borderPoint(b, a.x, a.y);
    const cls = 'edge' + (e.x ? ' cross' : '');
    const marker = e.x ? 'url(#arrow-coral)' : 'url(#arrow)';
    svg += `<path class="${cls}" data-edge="${i}" data-ind="${(e.ind || []).join(',')}" d="M${p1.x.toFixed(1)} ${p1.y.toFixed(1)} L${p2.x.toFixed(1)} ${p2.y.toFixed(1)}" marker-end="${marker}" />`;
  });

  // nodes
  state.map.nodes.forEach((n) => {
    const box = L.boxes[n.id];
    if (!box) return;
    let inner = nodeShape(box, n.type);
    // students sub-block (equity hook): inner dashed rectangle
    if (n.sub) {
      const iw = box.w - 14, ih = box.h - 12;
      inner += `<rect x="${box.x - iw / 2}" y="${box.y - ih / 2}" width="${iw}" height="${ih}" rx="4" fill="none" stroke="#B85248" stroke-width="1" stroke-dasharray="4 3" />`;
    }
    const dot = n.ev ? `<circle class="ev-dot" cx="${box.x + box.w / 2 - 7}" cy="${box.y - box.h / 2 + 7}" r="3" fill="#3C7D5E" />`
                     : `<circle class="ev-dot" cx="${box.x + box.w / 2 - 7}" cy="${box.y - box.h / 2 + 7}" r="3" fill="#B07B2E" />`;
    svg += `<g class="node ${n.type}" data-node="${esc(n.id)}" tabindex="0">${inner}${dot}${labelTspans(n.label, box.x, box.y, box.w)}</g>`;
  });

  // tool node (double boundary object) — two nested rects
  const t = L.tool;
  svg += `<g class="node tool-node" data-node="${TOOL_ID}" tabindex="0">` +
    `<rect class="shape outer" x="${t.x - t.w / 2 - 4}" y="${t.y - t.h / 2 - 4}" width="${t.w + 8}" height="${t.h + 8}" rx="6" />` +
    `<rect class="shape" x="${t.x - t.w / 2}" y="${t.y - t.h / 2}" width="${t.w}" height="${t.h}" rx="4" />` +
    `<text class="label" x="${t.x}" y="${t.y - 2}" text-anchor="middle">${esc(t.label)}</text>` +
    `<text class="tooltag" x="${t.x}" y="${t.y + 15}" text-anchor="middle">DOUBLE BOUNDARY OBJECT</text></g>`;

  svg += `</svg>`;
  $('map-canvas').innerHTML = svg;
  renderFilters();
  applyHighlight();

  // Suite bridge: let the Autonomy Budget app inherit the tool + downstream actors.
  try {
    localStorage.setItem('enea:suite', JSON.stringify({
      tool: state.map.tool.label || state.tool.name,
      actors: state.map.nodes.filter((n) => n.quadrant === 'downstream' && n.type === 'human').map((n) => n.label),
    }));
  } catch (e) { /* localStorage unavailable — non-fatal */ }
}

// ─── Filter chips + path highlighting ──────────────────────────────────────
function renderFilters() {
  const f = $('filters');
  f.innerHTML = '<span class="hint">ILLUMINA:</span>' +
    INDICATORS.map((k) => `<button class="chip-filter" data-ind="${k}" aria-pressed="false">${INDICATOR_META[k].label}</button>`).join('') +
    `<button class="chip-filter reset" data-ind="" aria-pressed="true">Tutta la rete</button>`;
  f.querySelectorAll('.chip-filter').forEach((b) =>
    b.addEventListener('click', () => setFilter(b.dataset.ind || null)));
}

function setFilter(ind) {
  state.activeInd = ind;
  document.querySelectorAll('#filters .chip-filter').forEach((b) =>
    b.setAttribute('aria-pressed', String((b.dataset.ind || null) === ind)));
  document.querySelectorAll('.btn-illumina').forEach((b) =>
    b.setAttribute('aria-pressed', String(b.dataset.ind === ind)));
  applyHighlight();
}

function applyHighlight() {
  const ind = state.activeInd;
  const svg = $('map-canvas');
  const litNodes = new Set([TOOL_ID]);
  svg.querySelectorAll('.edge').forEach((edge) => {
    edge.classList.remove('lit', 'dim');
    if (!ind) return;
    const inds = (edge.dataset.ind || '').split(',').filter(Boolean);
    if (inds.includes(ind)) {
      edge.classList.add('lit');
      const i = +edge.dataset.edge;
      const e = state.map.edges[i];
      litNodes.add(e.from); litNodes.add(e.to);
    } else {
      edge.classList.add('dim');
    }
  });
  svg.querySelectorAll('.node').forEach((g) => {
    g.classList.remove('dim');
    if (ind && g.dataset.node !== TOOL_ID && !litNodes.has(g.dataset.node)) g.classList.add('dim');
  });
}

// ─── Detail panel ──────────────────────────────────────────────────────────
function evBadges(ev) {
  if (ev && ev.length) {
    return ev.map((id) => `<span class="badge doc" data-src="${esc(id)}">📄 documentato · ${esc(id)}</span>`).join('');
  }
  return '<span class="badge inf">◌ inferito</span>';
}

function selectNode(id) {
  state.selected = id;
  const panel = $('detail-panel');
  const layout = $('map-layout');
  if (id === TOOL_ID) {
    const t = state.map.tool;
    panel.innerHTML = `
      <div class="field-label" style="margin-top:0;color:var(--coral)">DOUBLE BOUNDARY OBJECT</div>
      <h3>${esc(t.label)}</h3>
      <p class="field-val">Il tool sta a cavallo dei confini strutturali (Star &amp; Griesemer). Media <b>due volte</b>: tra <i>upstream</i> (costruzione) e <i>downstream</i> (aula), e all'interno dell'upstream tra <i>design/sviluppo</i> e <i>dati di addestramento</i>. Le prescrizioni che lo attraversano raggiungono la relazione studente-docente.</p>
      <div class="field-label">EVIDENZE</div><div>${evBadges(t.ev)}</div>
      <button class="btn-close" data-close="1">Chiudi</button>`;
  } else {
    const n = state.map.nodes.find((x) => x.id === id);
    if (!n) return;
    panel.innerHTML = `
      <div class="field-label" style="margin-top:0;color:var(--coral)">${TYPE_LABEL[n.type]}</div>
      <h3>${esc(n.label)}</h3>
      <div class="field-label">QUADRANTE</div><div class="field-val">${QUADRANT_LABEL[n.quadrant]}</div>
      ${n.note ? `<div class="field-label">NOTA</div><div class="field-val">${esc(n.note)}</div>` : ''}
      ${n.sub ? '<div class="field-label">EQUITÀ</div><div class="field-val">Blocco suddivisibile in sotto-blocchi con benefici diversi.</div>' : ''}
      <div class="field-label">EVIDENZE</div><div>${evBadges(n.ev)}</div>
      <button class="btn-close" data-close="1">Chiudi</button>`;
  }
  panel.style.display = 'block';
  layout.classList.add('with-panel');
  panel.querySelector('[data-close]').addEventListener('click', closeDetail);
  panel.querySelectorAll('.badge.doc').forEach((b) =>
    b.addEventListener('click', () => flashSource(b.dataset.src)));
}

function closeDetail() {
  state.selected = null;
  $('detail-panel').style.display = 'none';
  $('map-layout').classList.remove('with-panel');
}

// ─── Questions ─────────────────────────────────────────────────────────────
function renderQuestions() {
  const T = state.tool.name;
  const grid = $('q-grid');
  grid.innerHTML = PRINCIPLES.map((p) => `
    <div class="q-card" data-key="${p.key}">
      <div class="q-head">
        <div>
          <span class="q-name">${p.label}</span>
          <p class="q-blurb">${esc(p.blurb)}</p>
        </div>
        <div class="flags" data-key="${p.key}">
          ${FLAG_STATES.map((s) => `<button class="flag ${s.cls}" data-flag="${s.v}" title="${s.label}" aria-pressed="false"></button>`).join('')}
          <span class="flag-label">—</span>
        </div>
      </div>
      <div class="q-rule"></div>
      <p class="q-text">${esc(p.q.replaceAll('{T}', T))}</p>
      <div class="q-actions">
        <button class="btn-illumina" data-ind="${p.key}" aria-pressed="false">Illumina i percorsi sulla mappa</button>
      </div>
      <textarea rows="2" data-key="${p.key}" placeholder="Le tue note su questo indicatore…"></textarea>
    </div>`).join('');

  grid.querySelectorAll('.btn-illumina').forEach((b) =>
    b.addEventListener('click', () => {
      setFilter(state.activeInd === b.dataset.ind ? null : b.dataset.ind);
      $('map-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));

  grid.querySelectorAll('.flags').forEach((wrap) => {
    const key = wrap.dataset.key;
    const labelEl = wrap.querySelector('.flag-label');
    wrap.querySelectorAll('.flag').forEach((btn) => {
      btn.addEventListener('click', () => {
        const v = btn.dataset.flag;
        state.flags[key] = state.flags[key] === v ? undefined : v;
        const cur = state.flags[key];
        wrap.querySelectorAll('.flag').forEach((f) => {
          f.setAttribute('aria-pressed', String(f.dataset.flag === cur));
          f.setAttribute('data-dim', String(!!cur && f.dataset.flag !== cur));
        });
        labelEl.textContent = cur ? FLAG_STATES.find((s) => s.v === cur).label : '—';
      });
    });
  });

  grid.querySelectorAll('textarea').forEach((ta) =>
    ta.addEventListener('input', () => { state.notes[ta.dataset.key] = ta.value; }));
}

// ─── Export markdown ───────────────────────────────────────────────────────
function flagMd(v) {
  return v === 'green' ? '🟢 Nessun flag'
    : v === 'amber' ? '🟡 Da approfondire'
    : v === 'red' ? '🔴 Indagine necessaria' : '⚪ Non valutato';
}
function labelOf(id) {
  if (id === TOOL_ID) return state.map.tool.label;
  const n = state.map.nodes.find((x) => x.id === id);
  return n ? n.label : id;
}
function evMd(ev) { return ev && ev.length ? `[${ev.join(', ')}]` : '(inferito)'; }

function exportMarkdown() {
  const m = state.map, t = state.tool;
  const L = [];
  L.push(`# Report ENEA — ${t.name}`);
  L.push(`*Uso in aula:* ${t.use || '—'}  `);
  L.push(`*Contesto:* ${t.context || '—'}  `);
  L.push(`*Data analisi:* ${state.accessed}`);
  if (!state.sources.length) {
    L.push(`\n> ⚠️ Nessuna fonte primaria: mappa interamente inferenziale (bozza interpretativa).`);
  }

  const quads = [['training', 'Upstream — Model Training'], ['design', 'Upstream — Model Design & Development'], ['downstream', 'Downstream — applicazione in aula']];
  L.push(`\n## Attori della rete per quadrante`);
  for (const [q, title] of quads) {
    const ns = m.nodes.filter((n) => n.quadrant === q);
    if (!ns.length) continue;
    L.push(`\n### ${title}`);
    ns.forEach((n) => {
      const kind = n.type === 'human' ? 'umano' : n.type === 'prescription' ? 'prescrizione' : 'non-umano';
      L.push(`- **${n.label}** (${kind}) ${evMd(n.ev)}${n.sub ? ' — *suddivisibile (equità)*' : ''}${n.note ? ` — ${n.note}` : ''}`);
    });
  }
  L.push(`\n**Tool (double boundary object): ${m.tool.label}** ${evMd(m.tool.ev)}`);

  L.push(`\n## Propagazione delle prescrizioni (archi)`);
  m.edges.forEach((e) => {
    const inds = (e.ind || []).map((k) => INDICATOR_META[k].label).join(', ') || '—';
    const cross = e.x ? ' · ⇄ attraversamento di confine' : '';
    L.push(`- ${labelOf(e.from)} → ${labelOf(e.to)} · indicatori: ${inds}${cross} ${evMd(e.ev)}`);
  });

  L.push(`\n## Interrogazione ENEA (indicatori di Brusseau)`);
  PRINCIPLES.forEach((p) => {
    L.push(`\n### ${p.label} — ${flagMd(state.flags[p.key])}`);
    L.push(`*${p.q.replaceAll('{T}', t.name)}*`);
    if (state.notes[p.key]) L.push(`\n> Note: ${state.notes[p.key]}`);
  });

  L.push(`\n## Bibliografia`);
  if (state.sources.length) {
    state.sources.forEach((s) => L.push(`- [${s.id}] ${s.title}. ${s.url} (consultato ${s.accessed || state.accessed})`));
  } else {
    L.push(`- Nessuna fonte primaria raccolta.`);
  }

  L.push(`\n---`);
  L.push(`Metodo: Balzan, Munarini & Angeli (2024), «Who Pilots the Copilots? Mapping a Generative AI's Actor-Network to Assess Its Educational Impacts», AIED 2024, LNCS 14830 (doi.org/10.1007/978-3-031-64299-9_42). Indicatori: Brusseau (2023), «AI human impact». Le mappe ENEA sono costruzioni contingenti, non oggetti statici; l'inferenza dichiarata (◌) è una feature di trasparenza, non un limite. I flag segnalano ulteriore indagine, non condanne.`);

  const text = L.join('\n');
  navigator.clipboard.writeText(text).then(() => {
    const b = $('btn-export');
    const prev = b.textContent;
    b.textContent = 'Copiato ✓';
    setTimeout(() => (b.textContent = prev), 2000);
  }, () => {
    // clipboard blocked: fall back to a prompt
    window.prompt('Copia il report:', text);
  });
}

// ─── Init ──────────────────────────────────────────────────────────────────
function init() {
  $('btn-run').addEventListener('click', run);
  $('btn-export').addEventListener('click', exportMarkdown);

  const ex = $('examples');
  EXAMPLES.forEach((e) => {
    const b = document.createElement('button');
    b.className = 'chip-example';
    b.textContent = e.name;
    b.addEventListener('click', () => {
      $('in-name').value = e.name; $('in-use').value = e.use; $('in-context').value = e.context;
    });
    ex.appendChild(b);
  });

  // event delegation for node clicks (SVG built via innerHTML)
  $('map-canvas').addEventListener('click', (ev) => {
    const g = ev.target.closest('[data-node]');
    if (g) selectNode(g.dataset.node);
  });
  $('map-canvas').addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    const g = ev.target.closest('[data-node]');
    if (g) { ev.preventDefault(); selectNode(g.dataset.node); }
  });
}

document.addEventListener('DOMContentLoaded', init);
