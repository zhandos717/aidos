"""Конфигурация және logging баптауы."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def setup_logging() -> logging.Logger:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="[AIDOS] %(levelname)s %(name)s: %(message)s",
    )
    return logging.getLogger("aidos")


logger = setup_logging()

# AI провайдер: "ollama", "openrouter" немесе "agentrouter"
AI_PROVIDER: str = os.getenv("AI_PROVIDER", "ollama")

# Ollama
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")

# OpenRouter
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-235b-a22b")

# AgentRouter
AGENTROUTER_API_KEY: str = os.getenv("AGENTROUTER_API_KEY", "")
AGENTROUTER_MODEL: str = os.getenv("AGENTROUTER_MODEL", "gpt-5")

# Ауа райы
WEATHER_API_KEY: str = os.getenv("WEATHER_API_KEY", "")
DEFAULT_CITY: str = os.getenv("DEFAULT_CITY", "Алматы")

# Музыка
MUSIC_DIR: Path = Path(os.getenv("MUSIC_DIR", "~/Music")).expanduser()

# Wake word
_ww = os.getenv("WAKE_WORD_MODEL", "")
WAKE_WORD_MODEL: Path | None = Path(_ww) if _ww else None

# Деректер қалтасы
DATA_DIR: Path = Path(os.getenv("AIDOS_DATA_DIR") or (Path.home() / ".aidos"))
DATA_DIR.mkdir(exist_ok=True)
