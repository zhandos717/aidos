"""ChatArea — сәлемдесу экраны, хабарлар және кіріс панелі."""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from aidos.ui.hud import IDLE, LISTENING, SPEAKING, THINKING, AICore
from aidos.ui.theme import (
    ACCENT,
    ACCENT2,
    BG,
    LINE,
    LINE2,
    RAISED,
    SURFACE,
    TEXT,
    TEXT_MUTED,
    TEXT_SEC,
    font,
    mix,
)

_STATE_TEXT = {
    IDLE: "",
    LISTENING: "Тыңдап тұрмын",
    THINKING: "Ойланып жатырмын",
    SPEAKING: "Сөйлеп тұрмын",
}

_SUGGESTIONS = [
    "Бүгін ауа райы қандай?",
    "Көңілді музыка қос",
    "10 минуттан кейін еске сал",
    "Расскажи что-нибудь интересное",
]

_WRAP_AI = 600
_WRAP_USER = 440


class ChatArea(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_send: Callable[[str], None],
        on_mic: Callable,
        on_toggle_tts: Callable,
    ) -> None:
        super().__init__(master, corner_radius=0, fg_color=BG)
        self._on_send = on_send
        self._on_mic = on_mic
        self._on_toggle_tts = on_toggle_tts
        self._state = IDLE
        self._recording = False
        self._typing_row = None
        self._stream = None
        self._glow_t = 0.0

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_topbar()
        self._build_body()
        self._build_composer()
        self._tick_glow()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_topbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=BG, height=60, corner_radius=0)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)
        bar.grid_propagate(False)

        self._mini_core = AICore(bar, size=34, bg=BG, detail=False)
        self._mini_core.grid(row=0, column=0, padx=(24, 10), pady=13)

        titles = ctk.CTkFrame(bar, fg_color="transparent")
        titles.grid(row=0, column=1, sticky="w")
        self.title_label = ctk.CTkLabel(titles, text="Жаңа әңгіме", text_color=TEXT, font=font(15, "bold"))
        self.title_label.grid(row=0, column=0, sticky="w")
        self._state_label = ctk.CTkLabel(titles, text="", text_color=TEXT_MUTED, font=font(12), height=14)
        self._state_label.grid(row=1, column=0, sticky="w")

        self.tts_btn = ctk.CTkButton(
            bar, text="Дауыс қосулы", width=120, height=32, corner_radius=16,
            fg_color=SURFACE, hover_color=RAISED, text_color=TEXT_SEC, font=font(12),
            command=self._on_toggle_tts,
        )
        self.tts_btn.grid(row=0, column=2, padx=24)

    def _build_body(self) -> None:
        self._body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self._body.grid(row=1, column=0, sticky="nsew")
        self._body.grid_rowconfigure(0, weight=1)
        self._body.grid_columnconfigure(0, weight=1)

        self._messages = ctk.CTkScrollableFrame(
            self._body, corner_radius=0, fg_color=BG,
            scrollbar_button_color=BG, scrollbar_button_hover_color=LINE2,
        )
        self._messages.grid_columnconfigure(0, weight=1)

        self._welcome = ctk.CTkFrame(self._body, fg_color=BG)
        self._welcome.grid_columnconfigure(0, weight=1)
        self._welcome.grid_rowconfigure(0, weight=1)
        self._welcome.grid_rowconfigure(5, weight=1)
        self._big_core = AICore(self._welcome, size=240, bg=BG)
        self._big_core.grid(row=1, column=0, pady=(0, 18))
        ctk.CTkLabel(
            self._welcome, text="Сәлем! Немен көмектесейін?", text_color=TEXT, font=font(26, "bold"),
        ).grid(row=2, column=0)
        ctk.CTkLabel(
            self._welcome, text="Жазыңыз немесе микрофонды басып айтыңыз — қазақша да, орысша да түсінемін.",
            text_color=TEXT_SEC, font=font(14),
        ).grid(row=3, column=0, pady=(6, 22))

        chips = ctk.CTkFrame(self._welcome, fg_color="transparent")
        chips.grid(row=4, column=0)
        for i, text in enumerate(_SUGGESTIONS):
            ctk.CTkButton(
                chips, text=text, height=36, corner_radius=18, fg_color=SURFACE, hover_color=RAISED,
                border_width=1, border_color=LINE, text_color=TEXT_SEC, font=font(13),
                command=lambda t=text: self._on_send(t),
            ).grid(row=i // 2, column=i % 2, padx=5, pady=5)

        self._show_welcome(True)

    def _build_composer(self) -> None:
        wrap = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        wrap.grid(row=2, column=0, sticky="ew", padx=48, pady=(4, 6))
        wrap.grid_columnconfigure(0, weight=1)

        self._composer = ctk.CTkFrame(wrap, fg_color=SURFACE, corner_radius=26, border_width=1, border_color=LINE)
        self._composer.grid(row=0, column=0, sticky="ew")
        self._composer.grid_columnconfigure(0, weight=1)

        self.entry = ctk.CTkEntry(
            self._composer, placeholder_text="Сұрағыңызды жазыңыз…", placeholder_text_color=TEXT_MUTED,
            height=50, font=font(15), corner_radius=0, fg_color="transparent", border_width=0, text_color=TEXT,
        )
        self.entry.grid(row=0, column=0, sticky="ew", padx=(22, 8), pady=1)
        self.entry.bind("<Return>", self._handle_send)

        self.mic_btn = ctk.CTkButton(
            self._composer, text="🎙", width=40, height=40, corner_radius=20,
            fg_color=RAISED, hover_color=LINE2, text_color=TEXT, font=font(17),
            command=self._on_mic,
        )
        self.mic_btn.grid(row=0, column=1, padx=(0, 6))

        self.send_btn = ctk.CTkButton(
            self._composer, text="↑", width=40, height=40, corner_radius=20,
            fg_color=ACCENT, hover_color=mix(ACCENT, "#FFFFFF", 0.2), text_color=BG,
            text_color_disabled=TEXT_MUTED, font=font(19, "bold"), command=self._handle_send,
        )
        self.send_btn.grid(row=0, column=2, padx=(0, 6))

        self.status = ctk.CTkLabel(wrap, text="", text_color=TEXT_MUTED, font=font(11), height=18)
        self.status.grid(row=1, column=0, pady=(4, 0))

    # ── Күй ───────────────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        self._state = state
        self._mini_core.set_state(state)
        self._big_core.set_state(state)
        self._state_label.configure(
            text=_STATE_TEXT[state], text_color=ACCENT2 if state == LISTENING else TEXT_MUTED,
        )

    def _show_welcome(self, show: bool) -> None:
        if show:
            self._messages.grid_forget()
            self._welcome.grid(row=0, column=0, sticky="nsew")
            self._mini_core.grid_remove()
        else:
            self._welcome.grid_forget()
            self._messages.grid(row=0, column=0, sticky="nsew")
            self._mini_core.grid()

    def _tick_glow(self) -> None:
        """Жазу кезінде кіріс жиегі ақырын жыпылықтайды."""
        if self._recording:
            self._glow_t += 0.15
            t = (math.sin(self._glow_t) + 1) / 2
            self._composer.configure(border_color=mix(LINE2, ACCENT2, 0.4 + 0.6 * t))
        self.after(40, self._tick_glow)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _handle_send(self, event=None) -> None:
        text = self.entry.get().strip()
        if text:
            self.entry.delete(0, tk.END)
            self._on_send(text)

    def _scroll_bottom(self) -> None:
        try:
            self._messages._parent_canvas.yview_moveto(1.0)
        except tk.TclError:
            pass

    def _next_row(self) -> ctk.CTkFrame:
        self._show_welcome(False)
        row = ctk.CTkFrame(self._messages, fg_color="transparent")
        row.grid(row=len(self._messages.winfo_children()), column=0, sticky="ew", padx=40, pady=8)
        row.grid_columnconfigure(0, weight=1)
        return row

    # ── Public API ─────────────────────────────────────────────────────────────

    def clear(self) -> None:
        for w in self._messages.winfo_children():
            w.destroy()
        self._typing_row = None
        self._stream = None
        self._show_welcome(True)

    def add_bubble(self, sender: str, text: str, is_user: bool, animate: bool = True):
        try:
            if not self.winfo_exists():
                return None
        except tk.TclError:
            return None
        self._remove_typing()
        row = self._next_row()

        if is_user:
            bubble = ctk.CTkFrame(row, fg_color=SURFACE, corner_radius=18)
            bubble.grid(row=0, column=0, sticky="e")
            ctk.CTkLabel(
                bubble, text=text, text_color=TEXT, font=font(15), wraplength=_WRAP_USER, justify="left",
            ).pack(padx=16, pady=10)
            self.after(50, self._scroll_bottom)
            return None

        label = ctk.CTkLabel(
            row, text="" if animate else text, text_color=TEXT, font=font(15),
            wraplength=_WRAP_AI, justify="left", anchor="w",
        )
        label.grid(row=0, column=0, sticky="w")
        if animate:
            self._reveal(label, text.split(" "), 0)
        self.after(50, self._scroll_bottom)
        return label

    def _reveal(self, label: ctk.CTkLabel, words: list[str], n: int) -> None:
        try:
            if not label.winfo_exists():
                return
        except tk.TclError:
            return
        n = min(len(words), n + 2)
        label.configure(text=" ".join(words[:n]))
        if n < len(words):
            if n % 20 == 0:
                self._scroll_bottom()
            self.after(28, lambda: self._reveal(label, words, n))
        else:
            self._scroll_bottom()

    def start_stream(self) -> None:
        self._remove_typing()
        self._stream = {"label": self.add_bubble("Aidos", "", is_user=False, animate=False), "text": "", "n": 0}

    def append_stream(self, delta: str) -> None:
        if not self._stream or self._stream["label"] is None:
            return
        self._stream["text"] += delta
        self._stream["n"] += 1
        self._stream["label"].configure(text=self._stream["text"] + " ▍")
        if self._stream["n"] % 6 == 0:
            self._scroll_bottom()

    def finish_stream(self, text: str) -> None:
        if self._stream and self._stream["label"] is not None:
            self._stream["label"].configure(text=text)
        self._stream = None
        self._scroll_bottom()

    # ── Ойлану индикаторы ─────────────────────────────────────────────────────

    def _remove_typing(self) -> None:
        if self._typing_row is not None:
            self._typing_row.destroy()
            self._typing_row = None

    def _animate_typing(self, dots: list[tk.Canvas], step: int) -> None:
        if self._typing_row is None:
            return
        for i, dot in enumerate(dots):
            t = (math.sin(step * 0.25 - i * 0.9) + 1) / 2
            dot.itemconfigure("d", fill=mix(LINE2, ACCENT, t))
        self.after(40, lambda: self._animate_typing(dots, step + 1))

    def set_thinking(self, thinking: bool) -> None:
        if thinking:
            self.send_btn.configure(state="disabled", fg_color=RAISED)
            self._remove_typing()
            self._typing_row = self._next_row()
            holder = ctk.CTkFrame(self._typing_row, fg_color="transparent")
            holder.grid(row=0, column=0, sticky="w", pady=6)
            dots = []
            for i in range(3):
                dot = tk.Canvas(holder, width=10, height=10, bg=BG, highlightthickness=0)
                dot.create_oval(1, 1, 9, 9, fill=LINE2, outline="", tags="d")
                dot.grid(row=0, column=i, padx=3)
                dots.append(dot)
            self._animate_typing(dots, 0)
            self.after(50, self._scroll_bottom)
        else:
            self._remove_typing()
            self.send_btn.configure(state="normal", fg_color=ACCENT)

    def set_mic_recording(self, recording: bool) -> None:
        self._recording = recording
        if recording:
            self.mic_btn.configure(fg_color=ACCENT2, text_color=BG, hover_color=ACCENT2)
            self.status.configure(text="Тыңдап тұрмын — 5 секунд сөйлеңіз", text_color=ACCENT2)
        else:
            self.mic_btn.configure(fg_color=RAISED, text_color=TEXT, hover_color=LINE2)
            self._composer.configure(border_color=LINE)
            self.status.configure(text="", text_color=TEXT_MUTED)

    def set_tts_enabled(self, enabled: bool) -> None:
        self.tts_btn.configure(
            text="Дауыс қосулы" if enabled else "Дауыс өшірулі",
            text_color=TEXT_SEC if enabled else TEXT_MUTED,
            fg_color=SURFACE if enabled else BG,
        )
