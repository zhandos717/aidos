"""AidosUI — негізгі терезе: Sidebar + ChatArea + логика."""

from __future__ import annotations

import json
import threading
import tkinter as tk
from datetime import datetime

import customtkinter as ctk

from aidos.ui.theme import BG, BG3, BG4, BLUE, RED, UI_STATE_FILE, ICON_PNG
from aidos.ui.session import ChatSession
from aidos.ui.sidebar import Sidebar
from aidos.ui.chat import ChatArea


class AidosUI(ctk.CTk):
    def __init__(self, router, tts=None) -> None:
        super().__init__()
        self._router = router
        self._tts = tts
        self._thinking = False
        self._recording = False
        self._tts_enabled = True
        self._voice_input = None
        self._current_session: ChatSession | None = None

        self.title("Aidos")
        self.minsize(720, 500)
        self.configure(fg_color=BG)
        self._set_icon()
        self._restore_geometry()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._sidebar.refresh()
        self._new_chat()

    # ── Терезе ────────────────────────────────────────────────────────────────

    def _restore_geometry(self) -> None:
        geometry = "1020x700"
        try:
            if UI_STATE_FILE.exists():
                data = json.loads(UI_STATE_FILE.read_text(encoding="utf-8"))
                geometry = data.get("geometry", geometry)
        except Exception:
            pass
        self.geometry(geometry)

    def _save_geometry(self) -> None:
        try:
            UI_STATE_FILE.write_text(
                json.dumps({"geometry": self.geometry()}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _on_close(self) -> None:
        self._save_geometry()
        self.destroy()

    def _set_icon(self) -> None:
        if not ICON_PNG.exists():
            return
        try:
            from PIL import Image, ImageTk
            img = Image.open(ICON_PNG).resize((256, 256), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.iconphoto(True, photo)
            self._icon_ref = photo  # GC-ден қорғау
        except Exception:
            pass

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self._sidebar = Sidebar(
            self,
            on_new_chat=self._new_chat,
            on_open_session=self._open_session,
        )
        self._sidebar.grid(row=0, column=0, sticky="nsew")

        self._chat = ChatArea(
            self,
            on_send=self._on_send,
            on_mic=self._on_mic,
            on_toggle_tts=self._toggle_tts,
        )
        self._chat.grid(row=0, column=1, sticky="nsew")

    # ── TTS ───────────────────────────────────────────────────────────────────

    def _toggle_tts(self) -> None:
        self._tts_enabled = not self._tts_enabled
        if self._tts_enabled:
            self._chat.tts_btn.configure(text="🔊", fg_color=BLUE)
        else:
            self._chat.tts_btn.configure(text="🔇", fg_color=BG3)

    # ── Микрофон ──────────────────────────────────────────────────────────────

    def _on_mic(self) -> None:
        if self._recording or self._thinking:
            return
        self._recording = True
        self._chat.set_mic_recording(True)
        threading.Thread(target=self._record_and_send, daemon=True).start()

    def _record_and_send(self) -> None:
        try:
            if self._voice_input is None:
                from aidos.core.voice import VoiceInput
                self._voice_input = VoiceInput()
            text = self._voice_input.listen()
        except Exception as exc:
            self.after(0, lambda: self._chat.status.configure(text=f"Микрофон қатесі: {exc}"))
            self.after(0, self._reset_mic)
            return

        self.after(0, self._reset_mic)
        if text:
            self.after(0, self._dispatch_voice_text, text)
        else:
            self.after(0, lambda: self._chat.status.configure(text="Дауыс анықталмады"))
            self.after(2000, lambda: self._chat.status.configure(text=""))

    def _reset_mic(self) -> None:
        self._recording = False
        self._chat.set_mic_recording(False)

    def _dispatch_voice_text(self, text: str) -> None:
        self._chat.entry.delete(0, tk.END)
        self._chat.entry.insert(0, text)
        self._on_send(text)

    # ── Чат ───────────────────────────────────────────────────────────────────

    def _new_chat(self) -> None:
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_session = ChatSession(session_id=session_id)
        self._chat.clear()
        self._chat.title_label.configure(text="Жаңа чат")
        self._chat.add_bubble(
            "Aidos",
            "Сәлем! Мен Aidos — сіздің қазақ AI көмекшіңізмін. 👋",
            is_user=False,
        )

    def _open_session(self, session: ChatSession) -> None:
        self._current_session = session
        self._chat.clear()
        self._chat.title_label.configure(text=session.title)
        for msg in session.messages:
            self._chat.add_bubble(
                msg["sender"],
                msg["text"],
                is_user=msg["sender"] == "Сіз",
            )

    # ── Жіберу ────────────────────────────────────────────────────────────────

    def _on_send(self, text: str) -> None:
        if self._thinking or not text:
            return

        self._chat.add_bubble("Сіз", text, is_user=True)
        if self._current_session:
            self._current_session.add("Сіз", text)
            self._chat.title_label.configure(text=self._current_session.title)
            self.after(0, self._sidebar.refresh)

        self._thinking = True
        self._chat.set_thinking(True)

        threading.Thread(target=self._process, args=(text,), daemon=True).start()

    def _process(self, text: str) -> None:
        try:
            response = self._router.route(text)
        except Exception as exc:
            response = f"Қате: {exc}"
        self.after(0, self._on_response, response)

    def _on_response(self, response: str) -> None:
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return

        self._chat.add_bubble("Aidos", response, is_user=False)
        if self._current_session:
            self._current_session.add("Aidos", response)
            self.after(0, self._sidebar.refresh)

        self._thinking = False
        self._chat.set_thinking(False)

        if self._tts and self._tts_enabled:
            threading.Thread(target=self._tts.speak, args=(response,), daemon=True).start()
