const STAGES = [
  { id: "device", label: "🎙 Колонка" },
  { id: "vad", label: "〰 VAD" },
  { id: "stt", label: "📝 STT" },
  { id: "llm", label: "🧠 LLM" },
  { id: "tts", label: "🔊 TTS" },
  { id: "out", label: "🎧 Ответ" },
];
const STATE_RU = { idle: "ожидание", listening: "слушает", thinking: "думает", speaking: "говорит" };
const STATUS_RU = { active: "идёт", ok: "ok", error: "ошибка", aborted: "прерван" };
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const fmtMs = (ms) => (ms == null ? "—" : ms >= 1000 ? `${(ms / 1000).toFixed(1)} с` : `${ms} мс`);

let state = { link: { up: false, reconnects: 0 }, devices: [], turns: [], summary: {} };

function drawPipeline() {
  const svg = $("#pipeline");
  const w = 900 / STAGES.length;
  svg.innerHTML = STAGES.map((s, i) => {
    const x = i * w + 10;
    const cx = x + (w - 40) / 2;
    const edge = i < STAGES.length - 1
      ? `<line class="edge" x1="${x + w - 40}" y1="55" x2="${x + w + 10}" y2="55"/>`
      : "";
    return `<g class="node" id="node-${s.id}"><rect x="${x}" y="30" width="${w - 40}" height="50"/><text x="${cx}" y="60">${s.label}</text><text class="ms" id="ms-${s.id}" x="${cx}" y="100"></text></g>${edge}`;
  }).join("");
}

function activate(stageIds) {
  for (const s of STAGES) $(`#node-${s.id}`)?.classList.toggle("active", stageIds.includes(s.id));
}

function showStageTimings(turn) {
  const set = (id, text) => { const el = $(`#ms-${id}`); if (el) el.textContent = text; };
  set("device", turn.utterance_secs ? `фраза ${turn.utterance_secs.toFixed(1)} с` : "");
  set("stt", turn.stt_ms ? fmtMs(turn.stt_ms) : "");
  set("llm", turn.llm_ms ? fmtMs(turn.llm_ms) : "");
  set("tts", turn.tts_ms ? fmtMs(turn.tts_ms) : "");
  set("out", turn.first_audio_ms ? `до звука ${fmtMs(turn.first_audio_ms)}` : "");
}

function renderHeader() {
  const link = $("#link-status");
  link.textContent = state.link.up ? "мозг: на связи" : "мозг: нет связи";
  link.className = `pill ${state.link.up ? "ok" : "bad"}`;
  $("#devices-online").textContent = `колонок онлайн: ${state.devices.filter((d) => d.online).length}`;
  $("#reconnects").textContent = `переподключений: ${state.link.reconnects}`;
}

function renderSummary() {
  const s = state.summary || {};
  const row = (name, st) => `<tr><td>${name}</td><td>${fmtMs(st?.median_ms)}</td><td>${fmtMs(st?.p95_ms)}</td></tr>`;
  $("#summary").innerHTML =
    `<tr><th>этап</th><th>медиана</th><th>p95</th></tr>` +
    row("до первого звука", s.first_audio) + row("STT", s.stt) + row("LLM", s.llm) + row("TTS", s.tts) + row("весь ход", s.total) +
    `<tr><td>ходов / ошибок</td><td colspan="2">${s.turns ?? 0} / ${s.errors ?? 0}</td></tr>`;
}

function renderDevices() {
  $("#devices").innerHTML = state.devices.length
    ? state.devices.map((d) => `<li><span><span class="dot ${d.online ? "on" : ""}"></span>${esc(d.device_id)}</span><span class="muted">${d.online ? esc(STATE_RU[d.state] ?? d.state) : "офлайн"}</span></li>`).join("")
    : `<li class="muted">Нет колонок</li>`;
}

function waterfall(t) {
  const total = t.total_ms || (t.stt_ms + t.llm_ms + t.tts_ms) || 1;
  const pct = (ms) => `${Math.min(100, (ms / total) * 100)}%`;
  let left = 0;
  const seg = (cls, ms) => { const html = ms ? `<span class="${cls}" style="left:${pct(left)};width:${pct(ms)}"></span>` : ""; left += ms; return html; };
  const first = t.first_audio_ms ? `<span class="first" style="left:${pct(t.first_audio_ms)}"></span>` : "";
  return `<div class="waterfall">${seg("stt", t.stt_ms)}${seg("llm", t.llm_ms)}${seg("tts", t.tts_ms)}${first}</div>`;
}

function renderTurns() {
  const legend = `<div class="legend"><span><i style="background:var(--stt)"></i>STT</span><span><i style="background:var(--llm)"></i>LLM</span><span><i style="background:var(--tts)"></i>TTS</span><span><i style="background:var(--warn)"></i>первый звук</span></div>`;
  $("#turns").innerHTML = state.turns.length
    ? legend + state.turns.map((t) => `
      <li class="turn ${esc(t.status)}">
        <div class="turn-head"><span>${new Date(t.started_at).toLocaleTimeString("ru-RU")} · ${esc(t.device_id)}</span>
          <span>${esc(STATUS_RU[t.status] ?? t.status)} · до звука ${fmtMs(t.first_audio_ms)} · всего ${fmtMs(t.total_ms)}</span></div>
        <div class="turn-text"><b>Вы:</b> ${esc(t.transcript) || "…"}</div>
        <div class="turn-text"><b>Айдос:</b> ${esc(t.reply_text) || "…"}</div>
        ${t.status === "active" ? "" : waterfall(t)}
      </li>`).join("")
    : `<li class="muted">Ходов пока нет — скажите что-нибудь в эмулятор или колонку.</li>`;
}

function renderAll() { renderHeader(); renderSummary(); renderDevices(); renderTurns(); }

function upsertTurn(turn) {
  const i = state.turns.findIndex((t) => t.turn_id === turn.turn_id);
  if (i >= 0) state.turns[i] = turn; else state.turns.unshift(turn);
  state.turns = state.turns.slice(0, 100);
}

async function resync() {
  const res = await fetch("/api/state");
  if (res.ok) { state = await res.json(); renderAll(); }
}

function onEvent(ev) {
  switch (ev.type) {
    case "resync": return void resync();
    case "link": state.link = ev.link; renderHeader(); return;
    case "device": {
      const i = state.devices.findIndex((d) => d.device_id === ev.device.device_id);
      if (i >= 0) state.devices[i] = ev.device; else state.devices.push(ev.device);
      renderDevices(); renderHeader(); return;
    }
    case "turn_started": upsertTurn(ev.turn); activate(["device", "vad", "stt"]); renderTurns(); return;
    case "transcript": {
      const t = state.turns.find((x) => x.turn_id === ev.turn_id);
      if (t) t.transcript = ev.text;
      activate(["llm"]); renderTurns(); return;
    }
    case "speech": {
      const t = state.turns.find((x) => x.turn_id === ev.turn_id);
      if (t) { t.reply_text = t.reply_text ? `${t.reply_text} ${ev.text}` : ev.text; t.first_audio_ms ??= ev.first_audio_ms; }
      activate(["tts", "out"]); renderTurns(); return;
    }
    case "turn_end":
      upsertTurn(ev.turn); activate([]); showStageTimings(ev.turn);
      void fetch("/api/state").then((r) => r.json()).then((s) => { state.summary = s.summary; renderSummary(); });
      renderTurns(); return;
  }
}

function connectEvents() {
  const es = new EventSource("/api/events");
  es.onmessage = (m) => onEvent(JSON.parse(m.data));
  es.onopen = () => void resync();
}

async function loadEmulator() {
  const root = $("#emulator");
  try {
    const mod = await import("/emulator.js");
    if (typeof mod.initEmulator !== "function") throw new Error("no initEmulator");
    mod.initEmulator(root);
  } catch {
    root.innerHTML = `<h2>Эмулятор колонки</h2><p class="note">Эмулятор недоступен.</p>`;
  }
}

drawPipeline();
renderAll();
connectEvents();
loadEmulator();
