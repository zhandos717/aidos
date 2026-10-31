"""Баптаулар терезесі — LLM / STT / TTS провайдерлері мен тема."""

from __future__ import annotations

import threading
from collections.abc import Callable

import customtkinter as ctk

from aidos.core.ai_factory import LLM_PROVIDERS
from aidos.core.settings import settings
from aidos.core.tts import EDGE_VOICES, TTS_EFFECTS, TTS_PROVIDERS
from aidos.core.voice import STT_LANGUAGES, STT_PROVIDERS
from aidos.ui.theme import (
    ACCENT,
    ACCENT_DARK,
    BG,
    ERR,
    FONT,
    LINE,
    LINE2,
    OK,
    PANEL,
    TEXT,
    TEXT_MUTED,
    TEXT_SEC,
    THEME_ID,
    THEMES,
)

_TOKEN_LIMITS = {150: "Өте қысқа", 300: "Қысқа", 600: "Орташа", 1500: "Ұзын"}

_PREVIEW_TEXT = "Сәлем! Мен Aidos. Барлық жүйелер дайын."


def _llm_title(pid: str) -> str:
    p = LLM_PROVIDERS[pid]
    return p.title if p.has_key() else f"{p.title}  · кілт жоқ"


class _Choice:
    """Көрсетілетін атау ↔ ішкі id картасы бар OptionMenu."""

    def __init__(self, master, options: dict[str, str], value: str, command: Callable | None = None) -> None:
        self._to_id = {title: key for key, title in options.items()}
        self._to_title = options
        self.widget = ctk.CTkOptionMenu(
            master, values=list(options.values()), height=32, corner_radius=8,
            fg_color=PANEL, button_color=ACCENT_DARK, button_hover_color=LINE2,
            text_color=TEXT, dropdown_fg_color=PANEL, dropdown_hover_color=LINE,
            dropdown_text_color=TEXT, font=ctk.CTkFont(family=FONT, size=14),
            dropdown_font=ctk.CTkFont(family=FONT, size=14),
            command=(lambda _t: command()) if command else None,
        )
        self.set(value)

    def get(self) -> str:
        return self._to_id[self.widget.get()]

    def set(self, value: str) -> None:
        self.widget.set(self._to_title.get(value, next(iter(self._to_title.values()))))


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master, ai_client, tts, on_applied: Callable[[], None]) -> None:
        super().__init__(master)
        self._ai = ai_client
        self._tts = tts
        self._on_applied = on_applied

        self.title("Баптаулар")
        self.geometry("520x640")
        self.resizable(False, True)
        self.configure(fg_color=BG)
        self.transient(master)
        self.after(50, self.grab_set)

        self._build()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _section(self, row: int, title: str) -> ctk.CTkFrame:
        ctk.CTkLabel(
            self._body, text=title, font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
            text_color=TEXT,
        ).grid(row=row, column=0, sticky="w", pady=(14, 4))
        frame = ctk.CTkFrame(self._body, fg_color=PANEL, corner_radius=8, border_width=1, border_color=LINE)
        frame.grid(row=row + 1, column=0, sticky="ew")
        frame.grid_columnconfigure(1, weight=1)
        return frame

    @staticmethod
    def _field(frame, row: int, label: str, widget) -> None:
        ctk.CTkLabel(
            frame, text=label, font=ctk.CTkFont(family=FONT, size=13), text_color=TEXT_SEC, width=110, anchor="w",
        ).grid(row=row, column=0, padx=(12, 8), pady=6, sticky="w")
        widget.grid(row=row, column=1, padx=(0, 12), pady=6, sticky="ew")

    def _build(self) -> None:
        cfg = settings.current
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._body = ctk.CTkScrollableFrame(self, fg_color=BG, corner_radius=0)
        self._body.grid(row=0, column=0, sticky="nsew", padx=16, pady=(8, 0))
        self._body.grid_columnconfigure(0, weight=1)

        llm = self._section(0, "Модель (LLM)")
        self._llm = _Choice(llm, {pid: _llm_title(pid) for pid in LLM_PROVIDERS}, cfg.llm_provider,
                            command=self._on_llm_changed)
        self._field(llm, 0, "Провайдер", self._llm.widget)
        self._model = ctk.CTkComboBox(
            llm, values=[], height=32, corner_radius=8, fg_color=PANEL, border_color=LINE2,
            button_color=ACCENT_DARK, text_color=TEXT, dropdown_fg_color=PANEL,
            font=ctk.CTkFont(family=FONT, size=14),
        )
        self._field(llm, 1, "Модель", self._model)
        self._on_llm_changed(cfg.llm_model)
        self._max_tokens = _Choice(llm, {str(n): label for n, label in _TOKEN_LIMITS.items()}, str(cfg.max_tokens))
        self._field(llm, 2, "Жауап ұзындығы", self._max_tokens.widget)
        self._fast = ctk.CTkSwitch(
            llm, text="Жылдам жауап (бір LLM сұранысы)", font=ctk.CTkFont(family=FONT, size=13),
            text_color=TEXT, progress_color=ACCENT, button_color=TEXT, fg_color=LINE2,
        )
        if cfg.fast_mode:
            self._fast.select()
        self._fast.grid(row=3, column=0, columnspan=2, padx=12, pady=(4, 10), sticky="w")

        stt = self._section(2, "Сөзді тану (STT)")
        self._stt = _Choice(stt, STT_PROVIDERS, cfg.stt_provider)
        self._field(stt, 0, "Провайдер", self._stt.widget)
        self._stt_lang = _Choice(stt, STT_LANGUAGES, cfg.stt_language)
        self._field(stt, 1, "Тіл", self._stt_lang.widget)

        tts = self._section(4, "Дауыс (TTS)")
        self._tts_provider = _Choice(tts, TTS_PROVIDERS, cfg.tts_provider)
        self._field(tts, 0, "Провайдер", self._tts_provider.widget)
        self._voice = _Choice(tts, EDGE_VOICES, cfg.tts_voice)
        self._field(tts, 1, "Дауыс (edge)", self._voice.widget)
        ru_voices = {k: v for k, v in EDGE_VOICES.items() if not k.startswith("kk-")}
        self._voice_ru = _Choice(tts, ru_voices, cfg.tts_voice_ru)
        self._field(tts, 2, "Орысша мәтін", self._voice_ru.widget)
        self._effect = _Choice(tts, TTS_EFFECTS, cfg.tts_effect)
        self._field(tts, 3, "Эффект", self._effect.widget)
        self._preview_btn = ctk.CTkButton(
            tts, text="Тыңдап көру", height=30, corner_radius=8, fg_color=ACCENT_DARK,
            hover_color=LINE2, text_color=ACCENT, border_width=1, border_color=ACCENT,
            font=ctk.CTkFont(family=FONT, size=13, weight="bold"), command=self._preview,
        )
        self._preview_btn.grid(row=4, column=0, columnspan=2, padx=12, pady=(4, 10), sticky="ew")

        ui = self._section(6, "Интерфейс")
        self._theme = _Choice(ui, {k: v["name"] for k, v in THEMES.items()}, cfg.ui_theme)
        self._field(ui, 0, "Тема", self._theme.widget)
        ctk.CTkLabel(
            ui, text="Тема келесі іске қосқанда ауысады", font=ctk.CTkFont(family=FONT, size=11),
            text_color=TEXT_MUTED,
        ).grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="w")

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=1, column=0, sticky="ew", padx=16, pady=12)
        bottom.grid_columnconfigure(0, weight=1)
        self._message = ctk.CTkLabel(
            bottom, text="", font=ctk.CTkFont(family=FONT, size=12), text_color=TEXT_SEC,
            wraplength=300, justify="left", anchor="w",
        )
        self._message.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            bottom, text="Болдырмау", width=100, height=36, corner_radius=8, fg_color=BG,
            hover_color=LINE, text_color=TEXT_SEC, border_width=1, border_color=LINE2,
            font=ctk.CTkFont(family=FONT, size=13), command=self.destroy,
        ).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkButton(
            bottom, text="Сақтау", width=100, height=36, corner_radius=8, fg_color=ACCENT,
            hover_color=ACCENT, text_color=BG, border_width=0,
            font=ctk.CTkFont(family=FONT, size=13, weight="bold"), command=self._save,
        ).grid(row=0, column=2, padx=(8, 0))

    # ── Әрекеттер ─────────────────────────────────────────────────────────────

    def _on_llm_changed(self, model: str = "") -> None:
        provider = LLM_PROVIDERS[self._llm.get()]
        self._model.configure(values=provider.models)
        self._model.set(model or provider.default_model)

    def _tts_values(self) -> dict:
        return {
            "tts_provider": self._tts_provider.get(),
            "tts_voice": self._voice.get(),
            "tts_voice_ru": self._voice_ru.get(),
            "tts_effect": self._effect.get(),
        }

    def _preview(self) -> None:
        if self._tts is None:
            return
        settings.update(**self._tts_values())
        self._preview_btn.configure(state="disabled", text="Ойнатылуда…")

        def run() -> None:
            self._tts.speak(_PREVIEW_TEXT)
            self.after(0, lambda: self._preview_btn.configure(state="normal", text="Тыңдап көру"))

        threading.Thread(target=run, daemon=True).start()

    def _save(self) -> None:
        provider_id = self._llm.get()
        model = self._model.get().strip()
        if not LLM_PROVIDERS[provider_id].has_key():
            key = LLM_PROVIDERS[provider_id].key_env
            self._message.configure(text=f".env файлына {key} кілтін қосыңыз", text_color=ERR)
            return
        try:
            if (provider_id, model) != (self._ai.provider_id, self._ai.model):
                self._ai.switch(provider_id, model)
        except Exception as exc:
            self._message.configure(text=f"Қосылмады: {exc}", text_color=ERR)
            return

        theme = self._theme.get()
        settings.update(
            llm_provider=provider_id, llm_model=model,
            fast_mode=bool(self._fast.get()), max_tokens=int(self._max_tokens.get()),
            stt_provider=self._stt.get(), stt_language=self._stt_lang.get(),
            ui_theme=theme, **self._tts_values(),
        )
        self._on_applied()
        if theme != THEME_ID:
            self._message.configure(text="Сақталды. Тема келесі іске қосқанда ауысады", text_color=OK)
            self.after(1600, self.destroy)
        else:
            self.destroy()
