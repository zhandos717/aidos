"""iOS Dark Mode палитрасы мен константалар."""

from pathlib import Path

import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG          = "#000000"
BG2         = "#1C1C1E"
BG3         = "#2C2C2E"
BG4         = "#3A3A3C"
BLUE        = "#0A84FF"
BLUE_DARK   = "#0066CC"
BUBBLE_USER = "#0A84FF"
BUBBLE_AI   = "#2C2C2E"
TEXT        = "#FFFFFF"
TEXT_SEC    = "#8E8E93"
RED         = "#FF453A"

HISTORY_DIR   = Path.home() / ".aidos" / "chats"
UI_STATE_FILE = Path.home() / ".aidos" / "ui_state.json"
ASSETS_DIR    = Path(__file__).parent.parent.parent.parent / "assets"
ICON_PNG      = ASSETS_DIR / "icon.png"

HISTORY_DIR.mkdir(parents=True, exist_ok=True)
