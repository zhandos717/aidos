"""ChatArea — Jarvis стилінде хабар бабблдары мен кіріс панелі."""

from __future__ import annotations

import math
import tkinter as tk
from typing import Callable

import customtkinter as ctk

from aidos.ui.theme import (
    BG, BG3, BG4, CYAN, CYAN_DIM, CYAN_DARK, ORANGE, RED, TEXT, TEXT_SEC,
    BUBBLE_USER, BUBBLE_AI,
)


class ScanlineCanvas(tk.Canvas):
    """Топ-барда жылжитын сканерлеу сызығы."""

    def __init__(self, master, **kwargs) -> None:
        bg = kwargs.pop("bg", "#041520")
        super().__init__(master, height=2, bg=bg,
                         highlightthickness=0, **kwargs)
        self._x = 0
        self._width = 400
        self.bind("<Configure>", lambda e: setattr(self, "_width", e.width))
        self._animate()

    def _animate(self) -> None:
        self.delete("all")
        w = max(self._width, 50)
        x0 = self._x % (w + 160) - 80
        colors = [
            "#001A22", "#003344", "#006688", "#00AACC",
            "#00D4FF",
            "#00AACC", "#006688", "#003344", "#001A22",
        ]
        seg = 14
        for i, col in enumerate(colors):
            px = x0 + (i - 4) * seg
            if 0 <= px <= w:
                self.create_line(px, 0, px + seg, 2, fill=col, width=2)
        self._x += 5
        self.after(16, self._animate)


class ChatArea(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_send: Callable[[str], None],
        on_mic: Callable,
        on_toggle_tts: Callable,
    ) -> None:
        super().__init__(master, corner_radius=0, fg_color="#020A0F")
        self._on_send = on_send
        self._on_mic = on_mic
        self._on_toggle_tts = on_toggle_tts
        self._thinking_running = False
        self._thinking_dot_idx = 0
        self._entry_glow_t = 0.0

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build()
        self._start_entry_glow()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._build_topbar()
        self._build_messages()
        self._build_input()

    def _build_topbar(self) -> None:
        topbar = ctk.CTkFrame(self, fg_color="#041520", height=56, corner_radius=0)
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_columnconfigure(2, weight=1)
        topbar.grid_propagate(False)

        # Left cyan accent bar
        tk.Canvas(topbar, width=3, bg="#00D4FF",
                  highlightthickness=0).grid(row=0, column=0, sticky="ns")

        self.title_label = ctk.CTkLabel(
            topbar,
            text="//  ЖАҢА СЕАНС",
            font=ctk.CTkFont(family="Courier", size=13, weight="bold"),
            text_color=CYAN,
        )
        self.title_label.grid(row=0, column=1, padx=(10, 16), sticky="w")

        # Moving scanline fills the remaining space
        ScanlineCanvas(topbar, bg="#041520").grid(
            row=0, column=2, sticky="ew", padx=4
        )

        self.tts_btn = ctk.CTkButton(
            topbar,
            text="◉",
            width=36,
            height=36,
            corner_radius=4,
            fg_color=CYAN_DARK,
            hover_color="#0A2030",
            text_color=CYAN,
            border_width=1,
            border_color=CYAN,
            font=ctk.CTkFont(size=16),
            command=self._on_toggle_tts,
        )
        self.tts_btn.grid(row=0, column=3, padx=(0, 12), sticky="e")

    def _build_messages(self) -> None:
        self._messages = ctk.CTkScrollableFrame(
            self,
            corner_radius=0,
            fg_color="#020A0F",
            scrollbar_button_color=BG3,
            scrollbar_button_hover_color=BG4,
        )
        self._messages.grid(row=1, column=0, sticky="nsew")
        self._messages.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(
            self, text="",
            text_color=TEXT_SEC,
            font=ctk.CTkFont(family="Courier", size=10),
        )
        self.status.grid(row=2, column=0, padx=20, pady=(4, 0), sticky="w")

    def _build_input(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="#041520", corner_radius=0, height=76)
        bar.grid(row=3, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_propagate(False)

        # Top border glow line (animated)
        self._border_canvas = tk.Canvas(bar, height=1, bg="#003344",
                                        highlightthickness=0)
        self._border_canvas.grid(row=0, column=0, sticky="ew")

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.grid(row=1, column=0, padx=12, pady=10, sticky="ew")
        inner.grid_columnconfigure(0, weight=1)

        # Entry wrapper with animated border
        self._entry_frame = ctk.CTkFrame(
            inner, fg_color="#041520",
            corner_radius=4, border_width=1, border_color=CYAN_DARK,
        )
        self._entry_frame.grid(row=0, column=0, sticky="ew")
        self._entry_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self._entry_frame,
            text="▶",
            font=ctk.CTkFont(family="Courier", size=11),
            text_color=CYAN,
            width=22,
        ).grid(row=0, column=0, padx=(8, 0))

        self.entry = ctk.CTkEntry(
            self._entry_frame,
            placeholder_text="КОМАНДА ЕНГІЗУ...",
            placeholder_text_color="#1A4455",
            height=44,
            font=ctk.CTkFont(family="Courier", size=13),
            corner_radius=0,
            fg_color="transparent",
            border_width=0,
            text_color=CYAN,
        )
        self.entry.grid(row=0, column=1, sticky="ew", padx=(4, 8))
        self.entry.bind("<Return>", self._handle_send)

        self.mic_btn = ctk.CTkButton(
            inner,
            text="◎",
            width=44,
            height=44,
            corner_radius=4,
            fg_color="#041520",
            hover_color="#0A2030",
            text_color=TEXT_SEC,
            border_width=1,
            border_color="#0A2030",
            font=ctk.CTkFont(size=18),
            command=self._on_mic,
        )
        self.mic_btn.grid(row=0, column=1, padx=(8, 0))

        self.send_btn = ctk.CTkButton(
            inner,
            text="ЖІБЕРУ",
            width=84,
            height=44,
            corner_radius=4,
            fg_color=CYAN_DARK,
            hover_color="#0A3050",
            text_color=CYAN,
            border_width=1,
            border_color=CYAN,
            font=ctk.CTkFont(family="Courier", size=11, weight="bold"),
            command=self._handle_send,
        )
        self.send_btn.grid(row=0, column=2, padx=(8, 0))

    # ── Animations ─────────────────────────────────────────────────────────────

    def _start_entry_glow(self) -> None:
        self._entry_glow_t = 0.0
        self._tick_entry_glow()

    def _tick_entry_glow(self) -> None:
        self._entry_glow_t += 0.04
        intensity = (math.sin(self._entry_glow_t) + 1) / 2  # 0..1
        g = int(50 + intensity * 80)    # 50..130
        b = int(80 + intensity * 120)   # 80..200
        color = f"#00{g:02x}{b:02x}"
        try:
            self._entry_frame.configure(border_color=color)
            self._border_canvas.configure(bg=color)
        except Exception:
            pass
        self.after(40, self._tick_entry_glow)

    def _animate_thinking(self) -> None:
        if not self._thinking_running:
            return
        frames = [
            "AIDOS ОЙЛАНУДА  ·",
            "AIDOS ОЙЛАНУДА  ··",
            "AIDOS ОЙЛАНУДА  ···",
            "AIDOS ОЙЛАНУДА  ····",
        ]
        self.status.configure(text=frames[self._thinking_dot_idx % 4])
        self._thinking_dot_idx += 1
        self.after(350, self._animate_thinking)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _handle_send(self, event=None) -> None:
        text = self.entry.get().strip()
        if text:
            self.entry.delete(0, tk.END)
            self._on_send(text)

    # ── Public API ─────────────────────────────────────────────────────────────

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
        outer.grid(row=row, column=0, sticky="ew", padx=16, pady=5)
        outer.grid_columnconfigure(0, weight=1)

        if is_user:
            bubble = ctk.CTkFrame(
                outer, fg_color=BUBBLE_USER, corner_radius=4,
                border_width=1, border_color="#0A3050",
            )
            bubble.grid(row=0, column=0, sticky="e")

            ctk.CTkLabel(
                bubble,
                text="ПАЙДАЛАНУШЫ  ◈",
                font=ctk.CTkFont(family="Courier", size=9),
                text_color="#1A4455",
            ).pack(anchor="e", padx=12, pady=(6, 0))

            ctk.CTkLabel(
                bubble,
                text=text,
                font=ctk.CTkFont(family="Courier", size=13),
                text_color=CYAN,
                wraplength=430,
                justify="left",
            ).pack(padx=14, pady=(2, 10))
        else:
            row_inner = ctk.CTkFrame(outer, fg_color="transparent")
            row_inner.grid(row=0, column=0, sticky="w")

            # Hex avatar
            avatar = tk.Canvas(row_inner, width=36, height=36,
                               bg="#020A0F", highlightthickness=0)
            avatar.grid(row=0, column=0, sticky="n", padx=(0, 10), pady=2)
            self._draw_hex_avatar(avatar)

            col = ctk.CTkFrame(row_inner, fg_color="transparent")
            col.grid(row=0, column=1, sticky="w")

            ctk.CTkLabel(
                col,
                text="◈  AIDOS  //  AI",
                font=ctk.CTkFont(family="Courier", size=9),
                text_color=TEXT_SEC,
            ).pack(anchor="w", pady=(0, 2))

            bubble = ctk.CTkFrame(
                col, fg_color=BUBBLE_AI, corner_radius=4,
                border_width=1, border_color="#0A2030",
            )
            bubble.pack(anchor="w")

            label = ctk.CTkLabel(
                bubble,
                text="",
                font=ctk.CTkFont(family="Courier", size=13),
                text_color="#80C8E0",
                wraplength=430,
                justify="left",
            )
            label.pack(padx=14, pady=10)
            speed = max(8, 20 - len(text) // 80)   # longer text → faster reveal
            self._typewriter(label, text, 0, speed)

        self.after(80, lambda: self._messages._parent_canvas.yview_moveto(1.0))

    @staticmethod
    def _draw_hex_avatar(canvas: tk.Canvas) -> None:
        cx = cy = 18
        r = 14
        pts: list[float] = []
        for i in range(6):
            a = math.radians(i * 60 - 30)
            pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
        canvas.create_polygon(pts, outline="#00D4FF", fill="#041520", width=1)
        canvas.create_text(cx, cy, text="AI", fill="#00D4FF",
                           font=("Courier", 8, "bold"))

    def _typewriter(self, label: ctk.CTkLabel, text: str,
                    idx: int, speed: int) -> None:
        if idx <= len(text):
            cursor = "▌" if idx < len(text) else ""
            label.configure(text=text[:idx] + cursor)
            if idx % 6 == 0:
                try:
                    self._messages._parent_canvas.yview_moveto(1.0)
                except Exception:
                    pass
            self.after(speed, lambda: self._typewriter(label, text, idx + 1, speed))
        else:
            label.configure(text=text)

    def set_thinking(self, thinking: bool) -> None:
        if thinking:
            self._thinking_running = True
            self._thinking_dot_idx = 0
            self.send_btn.configure(
                state="disabled", fg_color="#020A0F",
                text="···", text_color=TEXT_SEC,
            )
            self._animate_thinking()
        else:
            self._thinking_running = False
            self.send_btn.configure(
                state="normal", fg_color=CYAN_DARK,
                text="ЖІБЕРУ", text_color=CYAN,
            )
            self.status.configure(text="")

    def set_mic_recording(self, recording: bool) -> None:
        if recording:
            self.mic_btn.configure(
                text="◉", fg_color="#1A0500",
                text_color=ORANGE, border_color=ORANGE,
            )
            self.status.configure(text="◉  ДАУЫС КІРУІ БЕЛСЕНДІ...")
        else:
            self.mic_btn.configure(
                text="◎", fg_color="#041520",
                text_color=TEXT_SEC, border_color="#0A2030",
            )
