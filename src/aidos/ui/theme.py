"""UI темалары мен константалар.

Тема модуль импортталғанда бір рет таңдалады — ауыстыру қайта іске қосуды талап етеді.
"""

from pathlib import Path

import customtkinter as ctk

from aidos.core.settings import settings

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ACCENT — негізгі (шаңырақ), ACCENT2 — тыңдау күйі
THEMES: dict[str, dict] = {
    "shanyrak": {
        "name": "Шаңырақ",
        "BG": "#0E1120", "PANEL": "#12162A", "SURFACE": "#1A1F38", "RAISED": "#232946",
        "LINE": "#262C4A", "LINE2": "#343B60",
        "ACCENT": "#E8B547", "ACCENT_DARK": "#3A3220", "ACCENT2": "#4CC3E0",
        "TEXT": "#EEEDF5", "TEXT_SEC": "#A3A6C2", "TEXT_MUTED": "#61668A",
        "OK": "#6FD3A0", "ERR": "#FF7A6B",
    },
    "jarvis": {
        "name": "Jarvis",
        "BG": "#071318", "PANEL": "#0A1A21", "SURFACE": "#10242D", "RAISED": "#16303B",
        "LINE": "#173039", "LINE2": "#22434F",
        "ACCENT": "#5FD4F4", "ACCENT_DARK": "#12333D", "ACCENT2": "#F2B35B",
        "TEXT": "#E6F4F8", "TEXT_SEC": "#93B3BD", "TEXT_MUTED": "#557480",
        "OK": "#6FD3A0", "ERR": "#FF7A6B",
    },
    "ultron": {
        "name": "Ultron",
        "BG": "#140A0C", "PANEL": "#1A0E11", "SURFACE": "#241316", "RAISED": "#2E181C",
        "LINE": "#2F1A1E", "LINE2": "#43262B",
        "ACCENT": "#F0545C", "ACCENT_DARK": "#3E1A1D", "ACCENT2": "#C9CED6",
        "TEXT": "#F6ECEC", "TEXT_SEC": "#C0A3A6", "TEXT_MUTED": "#7E6064",
        "OK": "#6FD3A0", "ERR": "#FFB4A8",
    },
}

THEME_ID = settings.current.ui_theme if settings.current.ui_theme in THEMES else "shanyrak"
T = THEMES[THEME_ID]

BG, PANEL, SURFACE, RAISED = T["BG"], T["PANEL"], T["SURFACE"], T["RAISED"]
LINE, LINE2 = T["LINE"], T["LINE2"]
ACCENT, ACCENT_DARK, ACCENT2 = T["ACCENT"], T["ACCENT_DARK"], T["ACCENT2"]
TEXT, TEXT_SEC, TEXT_MUTED = T["TEXT"], T["TEXT_SEC"], T["TEXT_MUTED"]
OK, ERR = T["OK"], T["ERR"]

# Жүйелік шрифтте қазақ әріптерінің бәрі бар; Avenir Next — тек латын логотипке
FONT = ".AppleSystemUIFont"
FONT_BRAND = "Avenir Next"

HISTORY_DIR   = Path.home() / ".aidos" / "chats"
UI_STATE_FILE = Path.home() / ".aidos" / "ui_state.json"
ASSETS_DIR    = Path(__file__).parent.parent.parent.parent / "assets"
ICON_PNG      = ASSETS_DIR / "icon.png"

HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def font(size: int = 14, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


def mix(a: str, b: str, t: float) -> str:
    """Екі hex түсті t (0..1) бойынша араластыру."""
    t = max(0.0, min(1.0, t))
    ra, ga, ba = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    rb, gb, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    r, g, b_ = round(ra + (rb - ra) * t), round(ga + (gb - ga) * t), round(ba + (bb - ba) * t)
    return f"#{r:02x}{g:02x}{b_:02x}"
