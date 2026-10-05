"""Sidebar — Jarvis стилінде чат тарихы панелі."""

from __future__ import annotations

import math
import tkinter as tk
from typing import Callable

import customtkinter as ctk

from aidos.ui.session import ChatSession
from aidos.ui.theme import BG2, BG3, BG4, CYAN, CYAN_DIM, CYAN_DARK, TEXT, TEXT_SEC


class ArcReactorCanvas(tk.Canvas):
    """Анимацияланған дуга реактор — Jarvis белгішесі."""

    def __init__(self, master, size: int = 56, **kwargs) -> None:
        bg = kwargs.pop("bg", "#041520")
        super().__init__(master, width=size, height=size,
                         bg=bg, highlightthickness=0, **kwargs)
        self._size = size
        self._angle = 0
        self._pulse = 0.0
        self._pulse_dir = 1
        self._animate()

    def _animate(self) -> None:
        self._angle = (self._angle + 2) % 360
        self._pulse += 0.04 * self._pulse_dir
        if self._pulse >= 1.0:
            self._pulse_dir = -1
        elif self._pulse <= 0.0:
            self._pulse_dir = 1
        self._draw()
        self.after(30, self._animate)

    def _draw(self) -> None:
        self.delete("all")
        cx = cy = self._size // 2
        r = self._size // 2 - 4

        # Outer static ring
        self.create_oval(cx - r, cy - r, cx + r, cy + r,
                         outline="#004466", width=1)

        # Three rotating arcs
        for i in range(3):
            start = self._angle + i * 120
            self.create_arc(cx - r + 2, cy - r + 2, cx + r - 2, cy + r - 2,
                            start=start, extent=55,
                            style="arc", outline="#00D4FF", width=2)

        # Inner hexagon (rotates slower)
        hex_r = r * 0.42
        pts: list[float] = []
        for i in range(6):
            a = math.radians(i * 60 - self._angle * 0.4)
            pts += [cx + hex_r * math.cos(a), cy + hex_r * math.sin(a)]
        self.create_polygon(pts, outline="#00AACC", fill="#020A0F", width=1)

        # Pulsing core
        glow = int(5 + self._pulse * 4)
        self.create_oval(cx - glow, cy - glow, cx + glow, cy + glow,
                         fill="#00D4FF", outline="")
        self.create_oval(cx - 3, cy - 3, cx + 3, cy + 3,
                         fill="#FFFFFF", outline="")


class Sidebar(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_new_chat: Callable,
        on_open_session: Callable[[ChatSession], None],
    ) -> None:
        super().__init__(master, width=280, corner_radius=0, fg_color="#041520")
        self._on_new_chat = on_new_chat
        self._on_open_session = on_open_session

        self.grid_rowconfigure(5, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_propagate(False)

        self._build()
        self._start_status_animation()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # Top cyan accent line
        tk.Canvas(self, height=2, bg="#00D4FF",
                  highlightthickness=0).grid(row=0, column=0, sticky="ew")

        # Header: arc reactor + title
        header = ctk.CTkFrame(self, fg_color="transparent", height=90)
        header.grid(row=1, column=0, sticky="ew", padx=14, pady=(14, 0))
        header.grid_columnconfigure(1, weight=1)
        header.grid_propagate(False)

        self._reactor = ArcReactorCanvas(header, size=54, bg="#041520")
        self._reactor.grid(row=0, column=0, rowspan=2, padx=(0, 12), pady=2)

        ctk.CTkLabel(
            header,
            text="J.A.R.V.I.S",
            font=ctk.CTkFont(family="Courier", size=16, weight="bold"),
            text_color=CYAN,
        ).grid(row=0, column=1, sticky="w")

        ctk.CTkLabel(
            header,
            text="Қазақ AI Жүйесі",
            font=ctk.CTkFont(family="Courier", size=10),
            text_color=TEXT_SEC,
        ).grid(row=1, column=1, sticky="w")

        # Animated status line
        self._status_label = ctk.CTkLabel(
            self,
            text="■ SYSTEM ONLINE",
            font=ctk.CTkFont(family="Courier", size=10),
            text_color="#00FF88",
        )
        self._status_label.grid(row=2, column=0, padx=14, pady=(6, 6), sticky="w")

        # New session button
        ctk.CTkButton(
            self,
            text="⊕  ЖАҢА СЕАНС",
            height=40,
            corner_radius=4,
            fg_color=CYAN_DARK,
            hover_color="#0A2030",
            text_color=CYAN,
            font=ctk.CTkFont(family="Courier", size=12, weight="bold"),
            border_width=1,
            border_color=CYAN,
            command=self._on_new_chat,
        ).grid(row=3, column=0, padx=12, pady=(0, 8), sticky="ew")

        # Sessions header label
        ctk.CTkLabel(
            self,
            text="◈  ДЕРЕКТЕР БАЗАСЫ",
            font=ctk.CTkFont(family="Courier", size=9),
            text_color="#1A4455",
        ).grid(row=4, column=0, padx=14, pady=(4, 2), sticky="w")

        # Session list
        self._list = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=BG3,
            scrollbar_button_hover_color=BG4,
        )
        self._list.grid(row=5, column=0, sticky="nsew", padx=8, pady=4)
        self._list.grid_columnconfigure(0, weight=1)

        # Bottom version line
        ctk.CTkLabel(
            self,
            text="AIDOS v2.0  //  CLASSIFIED",
            font=ctk.CTkFont(family="Courier", size=9),
            text_color="#102030",
        ).grid(row=6, column=0, pady=(4, 10))

    # ── Status animation ───────────────────────────────────────────────────────

    def _start_status_animation(self) -> None:
        self._status_texts = [
            "■ SYSTEM ONLINE",
            "■ AI CORE ACTIVE",
            "■ NEURAL NET: 98%",
            "■ MEMORY: SECURE",
            "■ ENCRYPTION: ON",
        ]
        self._status_idx = 0
        self._blink_on = True
        self._tick_status()

    def _tick_status(self) -> None:
        if self._blink_on:
            self._status_label.configure(
                text=self._status_texts[self._status_idx],
                text_color="#00FF88",
            )
        else:
            self._status_label.configure(text_color="#006633")
            self._status_idx = (self._status_idx + 1) % len(self._status_texts)

        self._blink_on = not self._blink_on
        self.after(1100, self._tick_status)

    # ── Sessions ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        for w in self._list.winfo_children():
            w.destroy()
        for session in ChatSession.all_sessions():
            self._add_item(session)

    def _add_item(self, session: ChatSession) -> None:
        ctk.CTkButton(
            self._list,
            text=f"▷  {session.title}",
            anchor="w",
            height=36,
            corner_radius=4,
            fg_color="transparent",
            hover_color="#0A2030",
            text_color=TEXT_SEC,
            font=ctk.CTkFont(family="Courier", size=11),
            command=lambda s=session: self._on_open_session(s),
        ).grid(sticky="ew", pady=1)
