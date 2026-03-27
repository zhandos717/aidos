"""Sidebar — чат тарихы тізімі."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from aidos.ui.session import ChatSession
from aidos.ui.theme import BG2, BG3, BG4, BLUE, TEXT, TEXT_SEC


class Sidebar(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_new_chat: Callable,
        on_open_session: Callable[[ChatSession], None],
    ) -> None:
        super().__init__(master, width=260, corner_radius=0, fg_color=BG2)
        self._on_new_chat = on_new_chat
        self._on_open_session = on_open_session

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_propagate(False)

        self._build()

    def _build(self) -> None:
        # Логотип
        header = ctk.CTkFrame(self, fg_color="transparent", height=60)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(20, 0))
        header.grid_columnconfigure(0, weight=1)
        header.grid_propagate(False)

        ctk.CTkLabel(
            header,
            text="✦  Aidos",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text="Қазақ AI Көмекші",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_SEC,
        ).grid(row=1, column=0, sticky="w")

        # Жаңа чат батырмасы
        ctk.CTkButton(
            self,
            text="+ Жаңа чат",
            height=40,
            corner_radius=12,
            fg_color=BG3,
            hover_color=BG4,
            text_color=BLUE,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_new_chat,
        ).grid(row=1, column=0, padx=12, pady=(16, 8), sticky="ew")

        # Тарих тізімі
        self._list = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=BG3,
            scrollbar_button_hover_color=BG4,
        )
        self._list.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)
        self._list.grid_columnconfigure(0, weight=1)

    def refresh(self) -> None:
        for w in self._list.winfo_children():
            w.destroy()
        for session in ChatSession.all_sessions():
            self._add_item(session)

    def _add_item(self, session: ChatSession) -> None:
        ctk.CTkButton(
            self._list,
            text=session.title,
            anchor="w",
            height=40,
            corner_radius=10,
            fg_color="transparent",
            hover_color=BG3,
            text_color=TEXT_SEC,
            font=ctk.CTkFont(size=13),
            command=lambda s=session: self._on_open_session(s),
        ).grid(sticky="ew", pady=2)
