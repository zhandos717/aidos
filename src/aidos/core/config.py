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

# Ollama
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")

# Ауа райы
WEATHER_API_KEY: str = os.getenv("WEATHER_API_KEY", "")
DEFAULT_CITY: str = os.getenv("DEFAULT_CITY", "Алматы")

# Музыка
MUSIC_DIR: Path = Path(os.getenv("MUSIC_DIR", "~/Music")).expanduser()

# Деректер қалтасы
DATA_DIR: Path = Path.home() / ".aidos"
DATA_DIR.mkdir(exist_ok=True)
