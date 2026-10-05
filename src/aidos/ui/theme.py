"""Jarvis / Iron Man палитрасы мен константалар."""

from pathlib import Path

import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Jarvis color palette
BG          = "#020A0F"   # почти чёрный с синим
BG2         = "#041520"   # тёмно-синий
BG3         = "#0A2030"   # морской синий
BG4         = "#0D3045"   # средний морской

CYAN        = "#00D4FF"   # основной голографический голубой
CYAN_DIM    = "#0077AA"   # приглушённый голубой
CYAN_DARK   = "#003344"   # тёмный голубой (фон кнопок)

ORANGE      = "#FF6B00"   # оранжевый (дуговой реактор / запись)
RED         = "#FF2244"   # красный для ошибок
GREEN       = "#00FF88"   # зелёный для статуса

TEXT        = "#C8F0FF"   # светло-голубоватый белый
TEXT_SEC    = "#3A7080"   # приглушённый голубой

BUBBLE_USER = "#0A1A2A"   # пузырь пользователя
BUBBLE_AI   = "#041520"   # пузырь AI

# Алиасы для совместимости с app.py
BLUE        = CYAN
BLUE_DARK   = CYAN_DIM

HISTORY_DIR   = Path.home() / ".aidos" / "chats"
UI_STATE_FILE = Path.home() / ".aidos" / "ui_state.json"
ASSETS_DIR    = Path(__file__).parent.parent.parent.parent / "assets"
ICON_PNG      = ASSETS_DIR / "icon.png"

HISTORY_DIR.mkdir(parents=True, exist_ok=True)
