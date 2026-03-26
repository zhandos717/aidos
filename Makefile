.DEFAULT_GOAL := help
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help install run run-voice run-both ollama-start ollama-pull ollama-pull-sherkala use-qwen use-sherkala piper-download clean

help:
	@echo "Aidos — қазақ AI көмекші"
	@echo ""
	@echo "  make install              — тәуелділіктерді орнату"
	@echo "  make run                  — мәтін режимінде іске қосу"
	@echo "  make run-voice            — дауыс режимінде іске қосу"
	@echo "  make run-both             — аралас режимде іске қосу"
	@echo "  make ollama-start         — Ollama серверін іске қосу"
	@echo "  make ollama-pull          — Qwen3.5:4b жүктеу (әдепкі)"
	@echo "  make ollama-pull-sherkala — Sherkala-8B жүктеу (қазақша)"
	@echo "  make use-qwen             — Qwen3.5:4b-ге ауысу"
	@echo "  make use-sherkala         — Sherkala-8B-ге ауысу"
	@echo "  make piper-download       — Piper қазақ дауысын жүктеу"
	@echo "  make clean                — venv тазалау"

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip -q
	$(PIP) install -e . -q
	@echo "✓ Тәуелділіктер орнатылды"
	@[ -f .env ] || (cp .env.example .env && echo "✓ .env файлы жасалды — WEATHER_API_KEY қосыңыз")
	@which ffmpeg > /dev/null 2>&1 || echo "⚠ ffmpeg орнатылмаған: brew install ffmpeg"

run:
	$(PYTHON) -m aidos.main

run-voice:
	$(PYTHON) -m aidos.main --voice

run-both:
	$(PYTHON) -m aidos.main --both

ollama-start:
	ollama serve &

ollama-pull:
	ollama pull qwen3.5:4b

ollama-pull-sherkala:
	ollama pull hf.co/inceptionai/Llama-3.1-Sherkala-8B-Chat

use-qwen:
	@sed -i '' 's|^OLLAMA_MODEL=.*|OLLAMA_MODEL=qwen3.5:4b|' .env
	@echo "✓ Модель: qwen3.5:4b"

use-sherkala:
	@[ -f .env ] || cp .env.example .env
	@sed -i '' 's|^OLLAMA_MODEL=.*|OLLAMA_MODEL=hf.co/inceptionai/Llama-3.1-Sherkala-8B-Chat|' .env
	@echo "✓ Модель: Sherkala-8B"

piper-download:
	@mkdir -p ~/.aidos/piper
	@echo "Piper kk_KZ-issai-medium жүктелуде..."
	wget -q -O ~/.aidos/piper/kk_KZ-issai-medium.onnx \
		"https://huggingface.co/rhasspy/piper-voices/resolve/main/kk/kk_KZ/issai/medium/kk_KZ-issai-medium.onnx"
	wget -q -O ~/.aidos/piper/kk_KZ-issai-medium.onnx.json \
		"https://huggingface.co/rhasspy/piper-voices/resolve/main/kk/kk_KZ/issai/medium/kk_KZ-issai-medium.onnx.json"
	@echo "✓ Piper қазақ дауысы жүктелді: ~/.aidos/piper/"

clean:
	rm -rf $(VENV)
	@echo "✓ Тазаланды"
