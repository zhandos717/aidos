"""pywebview көпірі: JS → Python (Api әдістері), Python → JS (Aidos.emit оқиғалары)."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

import webview

from aidos.core.ai_factory import LLM_PROVIDERS
from aidos.core.settings import settings
from aidos.core.tts import EDGE_VOICES, TTS_EFFECTS, TTS_PROVIDERS
from aidos.core.voice import STT_LANGUAGES, STT_PROVIDERS
from aidos.ui.session import ChatSession

logger = logging.getLogger("aidos.webui")

_WEB_DIR = Path(__file__).parent / "web"
_USER = "Сіз"
_AI = "Aidos"
_PREVIEW_TEXT = "Сәлем! Мен Aidos. Барлық жүйелер дайын."


class Api:
    def __init__(self, router, tts, ai_client) -> None:
        self._router = router
        self._tts = tts
        self._ai = ai_client
        self._window: webview.Window | None = None
        self._voice = None
        self._busy = False
        self._tts_enabled = True
        self._cancel = threading.Event()
        self._speech = None
        self._session = self._fresh_session()

    # ── Python → JS ───────────────────────────────────────────────────────────

    def _emit(self, event: str, payload=None) -> None:
        if self._window is None:
            return
        data = json.dumps(payload, ensure_ascii=False)
        try:
            self._window.evaluate_js(f"window.Aidos && Aidos.emit({json.dumps(event)}, {data})")
        except Exception as exc:
            logger.debug("evaluate_js қатесі: %s", exc)

    # ── Деректер ──────────────────────────────────────────────────────────────

    @staticmethod
    def _fresh_session() -> ChatSession:
        return ChatSession(session_id=datetime.now().strftime("%Y%m%d_%H%M%S"))

    @staticmethod
    def _sessions() -> list[dict]:
        return [
            {"id": s.session_id, "title": s.title}
            for s in ChatSession.all_sessions() if s.messages
        ]

    def _options(self) -> dict:
        return {
            "llm": [
                {"id": p.id, "title": p.title, "models": p.models, "default": p.default_model, "hasKey": p.has_key()}
                for p in LLM_PROVIDERS.values()
            ],
            "stt": STT_PROVIDERS,
            "sttLang": STT_LANGUAGES,
            "tts": TTS_PROVIDERS,
            "voices": EDGE_VOICES,
            "effects": TTS_EFFECTS,
        }

    # ── JS шақыратын әдістер ──────────────────────────────────────────────────

    def init(self) -> dict:
        from dataclasses import asdict

        return {
            "settings": asdict(settings.current),
            "options": self._options(),
            "sessions": self._sessions(),
            "model": self._ai.model,
            "provider": self._ai.provider_id,
            "tts": self._tts_enabled,
        }

    def new_chat(self) -> dict:
        self._session = self._fresh_session()
        return {"sessions": self._sessions()}

    def open_session(self, session_id: str) -> dict:
        for s in ChatSession.all_sessions():
            if s.session_id == session_id:
                self._session = s
                return {
                    "title": s.title,
                    "messages": [{"user": m["sender"] == _USER, "text": m["text"]} for m in s.messages],
                }
        return {"title": "", "messages": []}

    def toggle_tts(self) -> bool:
        self._tts_enabled = not self._tts_enabled
        return self._tts_enabled

    def send(self, text: str) -> None:
        text = (text or "").strip()
        if not text or self._busy:
            return
        self._busy = True
        self._session.add(_USER, text)
        self._emit("sessions", {"list": self._sessions(), "active": self._session.session_id,
                                "title": self._session.title})
        threading.Thread(target=self._process, args=(text,), daemon=True).start()

    def stop(self) -> None:
        self._cancel.set()
        if self._speech is not None:
            self._speech.cancel()
        from aidos.core.tts import stop_playback
        stop_playback()

    def mic(self) -> None:
        if self._busy:
            return
        threading.Thread(target=self._listen, daemon=True).start()

    def save_settings(self, values: dict) -> dict:
        provider_id = values.get("llm_provider", self._ai.provider_id)
        model = (values.get("llm_model") or "").strip()
        provider = LLM_PROVIDERS.get(provider_id)
        if provider is None:
            return {"ok": False, "error": "Белгісіз провайдер"}
        if not provider.has_key():
            return {"ok": False, "error": f".env файлына {provider.key_env} кілтін қосыңыз"}
        try:
            if (provider_id, model or provider.default_model) != (self._ai.provider_id, self._ai.model):
                self._ai.switch(provider_id, model)
        except Exception as exc:
            return {"ok": False, "error": f"Қосылмады: {exc}"}
        values["max_tokens"] = int(values.get("max_tokens", settings.current.max_tokens))
        values["fast_mode"] = bool(values.get("fast_mode", True))
        known = set(settings.current.__dataclass_fields__)
        settings.update(**{k: v for k, v in values.items() if k in known})
        return {"ok": True, "model": self._ai.model, "provider": self._ai.provider_id}

    def preview_voice(self, values: dict) -> None:
        if self._tts is None:
            return
        settings.update(**{k: v for k, v in values.items() if k.startswith("tts_")})
        threading.Thread(target=self._tts.speak, args=(_PREVIEW_TEXT,), daemon=True).start()

    # ── Фондық жұмыс ──────────────────────────────────────────────────────────

    def _listen(self) -> None:
        self._emit("state", "listening")
        try:
            if self._voice is None:
                from aidos.core.voice import VoiceInput
                self._voice = VoiceInput()
            text = self._voice.listen()
        except Exception as exc:
            self._emit("state", "idle")
            self._emit("status", f"Микрофон қатесі: {exc}")
            return
        self._emit("state", "idle")
        if text:
            self._emit("heard", text)
        else:
            self._emit("status", "Дауыс анықталмады — қайталап көріңіз")

    def _process(self, text: str) -> None:
        self._emit("state", "thinking")
        self._cancel.clear()
        speech = None
        streamed = False
        shown = ""

        def on_delta(delta: str) -> None:
            nonlocal speech, streamed, shown
            if self._cancel.is_set():
                # Генерацияны үзу: исключение HTTP стримін жабады
                raise _Stopped
            if not streamed:
                streamed = True
                if self._tts and self._tts_enabled:
                    speech = self._speech = self._tts.stream()
                    self._emit("state", "speaking")
                else:
                    self._emit("state", "idle")
            shown += delta
            self._emit("delta", delta)
            if speech:
                speech.feed(delta)

        try:
            response = self._router.route(text, on_delta=on_delta)
        except _Stopped:
            response = shown
        except Exception as exc:
            response = f"Қате: {exc}"
        if self._cancel.is_set():
            response = shown.strip() or "Тоқтатылды."

        self._emit("done", response)
        self._session.add(_AI, response)
        self._busy = False
        self._emit("sessions", {"list": self._sessions(), "active": self._session.session_id,
                                "title": self._session.title})

        try:
            if self._cancel.is_set():
                pass
            elif speech:
                speech.close()
                speech.wait()
            elif self._tts and self._tts_enabled:
                self._emit("state", "speaking")
                self._tts.speak(response)
        finally:
            self._speech = None
            self._emit("state", "idle")


class _Stopped(Exception):
    pass


def run_webui(router, tts=None, ai_client=None) -> None:
    api = Api(router, tts, ai_client)
    window = webview.create_window(
        "Aidos",
        url=str(_WEB_DIR / "index.html"),
        js_api=api,
        width=1180,
        height=780,
        min_size=(820, 560),
        background_color="#04050A",
    )
    api._window = window
    webview.start()
