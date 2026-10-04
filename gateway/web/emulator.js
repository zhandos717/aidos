const UP_RATE = 16000;
const DOWN_RATE = 24000;
const FRAME = 960; // 60 ms at 16 kHz
const FRAME_US = 60000;
const READY = "Готов. Удерживайте кнопку или пробел.";

// Decimates to 16 kHz with box averaging; the fractional phase is carried across
// 128-sample render quanta, otherwise 48k→16k would drop samples every block.
const WORKLET = `
class Tap extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / ${UP_RATE};
    this.phase = 0; this.acc = 0; this.n = 0;
    this.buf = new Float32Array(320); this.len = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += ch[i]; this.n++; this.phase += 1;
      if (this.phase >= this.ratio) {
        this.phase -= this.ratio;
        this.buf[this.len++] = this.acc / this.n;
        this.acc = 0; this.n = 0;
        if (this.len === this.buf.length) { this.port.postMessage(this.buf.slice(0)); this.len = 0; }
      }
    }
    return true;
  }
}
registerProcessor("tap", Tap);`;

const ENC_CONFIG = { codec: "opus", sampleRate: UP_RATE, numberOfChannels: 1, bitrate: 24000, opus: { frameDuration: FRAME_US } };
const DEC_CONFIG = { codec: "opus", sampleRate: DOWN_RATE, numberOfChannels: 1 };

async function supported() {
  if (!("AudioEncoder" in window) || !("AudioDecoder" in window) || !window.AudioWorkletNode) return false;
  try {
    const enc = await AudioEncoder.isConfigSupported(ENC_CONFIG);
    const dec = await AudioDecoder.isConfigSupported(DEC_CONFIG);
    return Boolean(enc.supported && dec.supported);
  } catch {
    return false;
  }
}

export function initEmulator(root) {
  root.innerHTML = `
    <h2>Эмулятор колонки</h2>
    <button class="talk" id="talk" disabled>🎙 Удерживай и говори</button>
    <p class="muted" id="emu-status">Подключение…</p>
    <div class="chat" id="chat"></div>`;
  const talk = root.querySelector("#talk");
  const statusEl = root.querySelector("#emu-status");
  const chat = root.querySelector("#chat");
  const status = (text, cls = "muted") => { statusEl.textContent = text; statusEl.className = cls; };
  const say = (who, text) => {
    const p = document.createElement("p");
    p.className = who === "Сіз" ? "me" : "bot";
    p.textContent = `${who}: ${text ?? ""}`;
    chat.append(p);
    chat.scrollTop = chat.scrollHeight;
  };
  start().catch((err) => status(`Ошибка эмулятора: ${err.message}`, "note"));

  async function start() {
    if (!(await supported())) {
      status("Браузер не поддерживает Opus в WebCodecs — откройте панель в Chrome.", "note");
      return;
    }
    const res = await fetch("/api/emulator");
    if (!res.ok) {
      status(res.status === 404 ? "Эмулятор отключён на шлюзе." : `Эмулятор недоступен (HTTP ${res.status}).`, "note");
      return;
    }
    const info = await res.json();
    const ws = new WebSocket(`${location.origin.replace(/^http/, "ws")}${info.ws_url}?token=${encodeURIComponent(info.token)}`);
    ws.binaryType = "arraybuffer";
    const sendJson = (obj) => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj)); };

    // Suspended until the first press (autoplay policy); resumed inside the gesture handler.
    const ctx = new AudioContext();
    let playAt = 0;
    const playing = new Set();
    const stopPlayback = () => {
      for (const src of playing) { try { src.stop(); } catch { /* not started */ } }
      playing.clear();
      playAt = 0;
    };

    // Chrome's Opus decoder may output at 48 kHz regardless of the configured rate,
    // so the buffer is built from the AudioData's own rate and length.
    const onDecoded = (data) => {
      const opts = { planeIndex: 0, format: "f32-planar" };
      const pcm = new Float32Array(data.allocationSize(opts) / 4);
      data.copyTo(pcm, opts);
      const rate = data.sampleRate;
      data.close();
      const buf = ctx.createBuffer(1, pcm.length, rate);
      buf.copyToChannel(pcm, 0);
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      // Fresh start gets a 150 ms cushion against network jitter; later frames are chained back-to-back.
      if (playAt < ctx.currentTime + 0.02) playAt = ctx.currentTime + 0.15;
      src.start(playAt);
      playAt += buf.duration;
      playing.add(src);
      src.onended = () => playing.delete(src);
    };
    let decoder = null;
    const makeDecoder = () => {
      decoder = new AudioDecoder({ output: onDecoded, error: (e) => status(`Ошибка декодера: ${e.message}`, "note") });
      decoder.configure(DEC_CONFIG);
    };
    makeDecoder();
    let downTs = 0;

    const encoder = new AudioEncoder({
      output: (chunk) => {
        const bytes = new Uint8Array(chunk.byteLength);
        chunk.copyTo(bytes);
        if (ws.readyState === WebSocket.OPEN) ws.send(bytes);
      },
      error: (e) => status(`Ошибка кодера: ${e.message}`, "note"),
    });
    encoder.configure(ENC_CONFIG);
    let upTs = 0;
    let pending = new Float32Array(0);
    let recording = false;
    let held = false;
    let session = "";
    let chain = Promise.resolve();
    const serial = (fn) => { chain = chain.then(fn).catch((err) => status(`Ошибка эмулятора: ${err.message}`, "note")); };

    ws.onopen = () => sendJson({ type: "hello", version: 1, transport: "websocket", audio_params: { format: "opus", sample_rate: UP_RATE, channels: 1, frame_duration: 60 } });
    ws.onclose = () => { held = false; recording = false; talk.disabled = true; talk.classList.remove("down"); status("Соединение закрыто — обновите страницу.", "note"); };
    ws.onmessage = (m) => {
      if (typeof m.data !== "string") {
        if (decoder.state === "closed") makeDecoder();
        try {
          decoder.decode(new EncodedAudioChunk({ type: "key", timestamp: downTs, data: new Uint8Array(m.data) }));
        } catch { /* broken packet: skip it */ }
        downTs += FRAME_US;
        return;
      }
      let msg;
      try { msg = JSON.parse(m.data); } catch { return; }
      if (msg.type === "hello") { session = msg.session_id ?? ""; talk.disabled = false; status(READY); }
      else if (msg.type === "stt") { say("Сіз", msg.text); status("Думаю…"); }
      else if (msg.type === "tts" && msg.state === "sentence_start") { say("Айдос", msg.text); status("Говорю…"); }
      else if (msg.type === "tts" && msg.state === "stop" && !recording) status(READY);
    };

    let stream = null;
    let tapNode = null;
    async function micStart() {
      if (recording || !held || talk.disabled) return;
      try {
        stream ??= await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: false } });
      } catch {
        status("Нет доступа к микрофону — разрешите его в браузере.", "note");
        return;
      }
      if (!tapNode) {
        const url = URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" }));
        try { await ctx.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
        tapNode = new AudioWorkletNode(ctx, "tap", { numberOfOutputs: 1, outputChannelCount: [1] });
        ctx.createMediaStreamSource(stream).connect(tapNode);
        // Outputs silence; the connection keeps the node pulled by the render graph.
        tapNode.connect(ctx.destination);
        tapNode.port.onmessage = (e) => { if (recording) feed(e.data); };
      }
      // The permission prompt may have outlasted the press.
      if (!held || ws.readyState !== WebSocket.OPEN) return;
      stopPlayback();
      pending = new Float32Array(0);
      recording = true;
      talk.classList.add("down");
      sendJson({ session_id: session, type: "listen", state: "start", mode: "manual" });
      status("Слушаю…");
    }

    function encodeFrame(frame) {
      const audio = new AudioData({ format: "f32", sampleRate: UP_RATE, numberOfFrames: FRAME, numberOfChannels: 1, timestamp: upTs, data: frame });
      encoder.encode(audio);
      audio.close();
      upTs += FRAME_US;
    }

    function feed(samples) {
      const merged = new Float32Array(pending.length + samples.length);
      merged.set(pending);
      merged.set(samples, pending.length);
      let off = 0;
      while (merged.length - off >= FRAME) {
        encodeFrame(merged.slice(off, off + FRAME));
        off += FRAME;
      }
      pending = merged.slice(off);
    }

    async function micStop() {
      if (!recording) return;
      recording = false;
      talk.classList.remove("down");
      if (pending.length > 0) {
        const last = new Float32Array(FRAME);
        last.set(pending);
        encodeFrame(last);
      }
      pending = new Float32Array(0);
      // flush() resolves after every output callback has run, so all frames are on the wire before stop.
      await encoder.flush();
      sendJson({ session_id: session, type: "listen", state: "stop" });
      status("Отправлено, думаю…");
    }

    const press = () => {
      if (held || talk.disabled) return;
      held = true;
      void ctx.resume();
      serial(micStart);
    };
    const release = () => {
      if (!held) return;
      held = false;
      serial(micStop);
    };

    talk.addEventListener("pointerdown", (e) => { e.preventDefault(); press(); });
    for (const ev of ["pointerup", "pointerleave", "pointercancel"]) talk.addEventListener(ev, release);
    window.addEventListener("keydown", (e) => {
      if (e.code === "Space" && !e.repeat && (e.target === document.body || e.target === talk)) { e.preventDefault(); press(); }
    });
    window.addEventListener("keyup", (e) => { if (e.code === "Space") release(); });
    window.addEventListener("blur", release);
  }
}
