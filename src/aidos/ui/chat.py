"""ChatArea — хабар бабблдары мен кіріс панелі."""

from __future__ import annotations


import threading
import tkinter as tk
from typing import Callable

import customtkinter as ctk

from aidos.ui.theme import (
    BG, BG2, BG3, BG4, BLUE, BLUE_DARK, BUBBLE_AI, BUBBLE_USER, RED, TEXT, TEXT_SEC,
)


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

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build()

    def _build(self) -> None:
        self._build_topbar()
        self._build_messages()
        self._build_input()

    def _build_topbar(self) -> None:
        topbar = ctk.CTkFrame(self, fg_color=BG2, height=56, corner_radius=0)
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_columnconfigure(1, weight=1)
        topbar.grid_propagate(False)

        self.title_label = ctk.CTkLabel(
            topbar,
            text="Жаңа чат",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT,
        )
        self.title_label.grid(row=0, column=0, padx=20, sticky="w")

        self.tts_btn = ctk.CTkButton(
            topbar,
            text="🔊",
            width=36,
            height=36,
            corner_radius=18,
            fg_color=BLUE,
            hover_color=BLUE_DARK,
            font=ctk.CTkFont(size=16),
            command=self._on_toggle_tts,
        )
        self.tts_btn.grid(row=0, column=1, padx=(0, 12), sticky="e")

    def _build_messages(self) -> None:
        self._messages = ctk.CTkScrollableFrame(
            self,
            corner_radius=0,
            fg_color=BG,
            scrollbar_button_color=BG3,
            scrollbar_button_hover_color=BG4,
        )
        self._messages.grid(row=1, column=0, sticky="nsew")
        self._messages.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(
            self, text="", text_color=TEXT_SEC, font=ctk.CTkFont(size=11)
        )
        self.status.grid(row=2, column=0, padx=20, pady=(4, 0), sticky="w")

    def _build_input(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=BG2, corner_radius=0, height=72)
        bar.grid(row=3, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_propagate(False)

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.grid(row=0, column=0, padx=12, pady=14, sticky="ew")
        inner.grid_columnconfigure(0, weight=1)

        self.entry = ctk.CTkEntry(
            inner,
            placeholder_text="iMessage...",
            placeholder_text_color=TEXT_SEC,
            height=44,
            font=ctk.CTkFont(size=14),
            corner_radius=22,
            fg_color=BG3,
            border_width=0,
            text_color=TEXT,
        )
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", self._handle_send)

        self.mic_btn = ctk.CTkButton(
            inner,
            text="🎙",
            width=44,
            height=44,
            corner_radius=22,
            fg_color=BG3,
            hover_color=BG4,
            font=ctk.CTkFont(size=18),
            command=self._on_mic,
        )
        self.mic_btn.grid(row=0, column=1, padx=(8, 0))

        self.send_btn = ctk.CTkButton(
            inner,
            text="↑",
            width=44,
            height=44,
            corner_radius=22,
            fg_color=BLUE,
            hover_color=BLUE_DARK,
            font=ctk.CTkFont(size=20, weight="bold"),
            command=self._handle_send,
        )
        self.send_btn.grid(row=0, column=2, padx=(8, 0))

    def _handle_send(self, event=None) -> None:
        text = self.entry.get().strip()
        if text:
            self.entry.delete(0, tk.END)
            self._on_send(text)

    def clear(self) -> None:
        for w in self._messages.winfo_children():
            w.destroy()

    def add_bubble(self, sender: str, text: str, is_user: bool) -> None:
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return

        row = len(self._messages.winfo_children())
        outer = ctk.CTkFrame(self._messages, fg_color="transparent")
        outer.grid(row=row, column=0, sticky="ew", padx=16, pady=3)
        outer.grid_columnconfigure(0, weight=1)

        if is_user:
            bubble = ctk.CTkFrame(outer, fg_color=BUBBLE_USER, corner_radius=20)
            bubble.grid(row=0, column=0, sticky="e")
            ctk.CTkLabel(
                bubble,
                text=text,
                font=ctk.CTkFont(size=14),
                text_color="#FFFFFF",
                wraplength=400,
                justify="left",
            ).pack(padx=14, pady=10)
        else:
            row_inner = ctk.CTkFrame(outer, fg_color="transparent")
            row_inner.grid(row=0, column=0, sticky="w")

            ctk.CTkLabel(
                row_inner,
                text="✦",
                width=32,
                height=32,
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=BLUE,
                fg_color=BG3,
                corner_radius=16,
            ).grid(row=0, column=0, sticky="n", padx=(0, 8), pady=2)

            col = ctk.CTkFrame(row_inner, fg_color="transparent")
            col.grid(row=0, column=1, sticky="w")

            ctk.CTkLabel(
                col,
                text="Aidos",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=TEXT_SEC,
            ).pack(anchor="w", pady=(0, 2))

            bubble = ctk.CTkFrame(col, fg_color=BUBBLE_AI, corner_radius=20)
            bubble.pack(anchor="w")

            ctk.CTkLabel(
                bubble,
                text=text,
                font=ctk.CTkFont(size=14),
                text_color=TEXT,
                wraplength=400,
                justify="left",
            ).pack(padx=14, pady=10)

        self.after(60, lambda: self._messages._parent_canvas.yview_moveto(1.0))

    def set_thinking(self, thinking: bool) -> None:
        if thinking:
            self.send_btn.configure(state="disabled", fg_color=BG4, text="···")
            self.status.configure(text="Aidos ойлануда…")
        else:
            self.send_btn.configure(state="normal", fg_color=BLUE, text="↑")
            self.status.configure(text="")

    def set_mic_recording(self, recording: bool) -> None:
        if recording:
            self.mic_btn.configure(text="⏹", fg_color=RED)
            self.status.configure(text="🎙  Тыңдауда...")
        else:
            self.mic_btn.configure(text="🎙", fg_color=BG3)
