"""Sidebar — логотип, жаңа әңгіме, тарих және баптаулар."""

from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from aidos.ui.hud import AICore
from aidos.ui.session import ChatSession
from aidos.ui.theme import (
    ACCENT,
    FONT_BRAND,
    PANEL,
    RAISED,
    SURFACE,
    TEXT,
    TEXT_MUTED,
    TEXT_SEC,
    font,
)


class Sidebar(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_new_chat: Callable,
        on_open_session: Callable[[ChatSession], None],
        on_settings: Callable,
    ) -> None:
        super().__init__(master, width=248, corner_radius=0, fg_color=PANEL)
        self._on_new_chat = on_new_chat
        self._on_open_session = on_open_session
        self._on_settings = on_settings
        self._active_id: str | None = None

        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_propagate(False)
        self._build()

    def _build(self) -> None:
        brand = ctk.CTkFrame(self, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=18, pady=(22, 18))
        AICore(brand, size=28, bg=PANEL, detail=False).grid(row=0, column=0, padx=(0, 10))
        ctk.CTkLabel(
            brand, text="Aidos", text_color=TEXT,
            font=ctk.CTkFont(family=FONT_BRAND, size=21, weight="bold"),
        ).grid(row=0, column=1)

        ctk.CTkButton(
            self, text="+   Жаңа әңгіме", anchor="w", height=40, corner_radius=10,
            fg_color=SURFACE, hover_color=RAISED, text_color=TEXT, font=font(14),
            command=self._on_new_chat,
        ).grid(row=1, column=0, padx=12, sticky="ew")

        ctk.CTkLabel(
            self, text="Тарих", text_color=TEXT_MUTED, font=font(12),
        ).grid(row=2, column=0, padx=20, pady=(22, 4), sticky="w")

        self._list = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=PANEL, scrollbar_button_hover_color=RAISED,
        )
        self._list.grid(row=3, column=0, sticky="nsew", padx=6)
        self._list.grid_columnconfigure(0, weight=1)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=4, column=0, sticky="ew", padx=12, pady=(8, 14))
        bottom.grid_columnconfigure(0, weight=1)
        self._footer = ctk.CTkLabel(bottom, text="", text_color=TEXT_MUTED, font=font(11), anchor="w")
        self._footer.grid(row=0, column=0, padx=8, sticky="w")
        ctk.CTkButton(
            bottom, text="Баптаулар", width=96, height=32, corner_radius=8,
            fg_color="transparent", hover_color=RAISED, text_color=TEXT_SEC, font=font(13),
            command=self._on_settings,
        ).grid(row=0, column=1)

    def set_footer(self, text: str) -> None:
        self._footer.configure(text=text)

    def set_active(self, session_id: str | None) -> None:
        self._active_id = session_id
        self.refresh()

    def refresh(self) -> None:
        for w in self._list.winfo_children():
            w.destroy()
        for session in ChatSession.all_sessions():
            if session.messages:
                self._add_item(session)

    def _add_item(self, session: ChatSession) -> None:
        active = session.session_id == self._active_id
        ctk.CTkButton(
            self._list, text=session.title, anchor="w", height=34, corner_radius=8,
            fg_color=RAISED if active else "transparent", hover_color=RAISED,
            text_color=ACCENT if active else TEXT_SEC, font=font(13),
            command=lambda s=session: self._on_open_session(s),
        ).grid(sticky="ew", pady=1)
