.DEFAULT_GOAL := help
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help install run run-voice run-both run-ui run-wake \
        ollama-start ollama-pull ollama-pull-sherkala \
        use-qwen use-sherkala use-openrouter use-agentrouter \
        piper-download wake-install lint clean

help:
	@echo "Aidos — қазақ AI көмекші"
	@echo ""
	@echo "  Іске қосу:"
	@echo "  make run                  — мәтін режимінде іске қосу"
	@echo "  make run-voice            — дауыс режимінде іске қосу"
	@echo "  make run-both             — аралас режимде іске қосу"
	@echo "  make run-ui               — iOS UI графикалық интерфейс"
	@echo "  make run-wake             — колонка режимі ('Айдос' триггері + TTS)"
	@echo ""
	@echo "  Орнату:"
	@echo "  make install              — тәуелділіктерді орнату"
	@echo "  make piper-download       — Piper қазақ дауысын жүктеу (kk_KZ-issai-high)
	@echo "  make wake-install         — openWakeWord орнату (жылдам триггер)""
	@echo ""
	@echo "  AI провайдер:"
	@echo "  make use-qwen             — Ollama + Qwen3.5:4b"
	@echo "  make use-sherkala         — Ollama + Sherkala-8B (қазақша)"
	@echo "  make use-openrouter       — OpenRouter API"
	@echo "  make use-agentrouter      — AgentRouter + deepseek-v3.2"
	@echo ""
	@echo "  Ollama:"
	@echo "  make ollama-start         — Ollama серверін іске қосу"
	@echo "  make ollama-pull          — Qwen3.5:4b жүктеу"
	@echo "  make ollama-pull-sherkala — Sherkala-8B жүктеу"
	@echo ""
	@echo "  make lint                 — ruff тексеруі"
	@echo "  make clean                — venv тазалау"

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip -q
	$(PIP) install -e . -q
	@echo "✓ Тәуелділіктер орнатылды"
	@[ -f .env ] || (cp .env.example .env && echo "✓ .env файлы жасалды — API кілттерін қосыңыз")

# ── Іске қосу ─────────────────────────────────────────────────────────────────

run:
	$(PYTHON) -m aidos.main

run-voice:
	$(PYTHON) -m aidos.main --voice

run-both:
	$(PYTHON) -m aidos.main --both

run-ui:
	$(PYTHON) -m aidos.main --ui

run-wake:
	$(PYTHON) -m aidos.main --wake

# ── Ollama ────────────────────────────────────────────────────────────────────

ollama-start:
	ollama serve &

ollama-pull:
	ollama pull qwen3.5:4b

ollama-pull-sherkala:
	ollama pull hf.co/inceptionai/Llama-3.1-Sherkala-8B-Chat

# ── AI провайдер ──────────────────────────────────────────────────────────────

use-qwen:
	@[ -f .env ] || cp .env.example .env
	@sed -i '' 's|^AI_PROVIDER=.*|AI_PROVIDER=ollama|' .env
	@sed -i '' 's|^OLLAMA_MODEL=.*|OLLAMA_MODEL=qwen3.5:4b|' .env
	@echo "✓ Провайдер: Ollama, модель: qwen3.5:4b"

use-sherkala:
	@[ -f .env ] || cp .env.example .env
	@sed -i '' 's|^AI_PROVIDER=.*|AI_PROVIDER=ollama|' .env
	@sed -i '' 's|^OLLAMA_MODEL=.*|OLLAMA_MODEL=hf.co/inceptionai/Llama-3.1-Sherkala-8B-Chat|' .env
	@echo "✓ Провайдер: Ollama, модель: Sherkala-8B"

use-openrouter:
	@[ -f .env ] || cp .env.example .env
	@sed -i '' 's|^AI_PROVIDER=.*|AI_PROVIDER=openrouter|' .env
	@echo "✓ Провайдер: OpenRouter (OPENROUTER_API_KEY .env файлында болуы керек)"

use-agentrouter:
	@[ -f .env ] || cp .env.example .env
	@sed -i '' 's|^AI_PROVIDER=.*|AI_PROVIDER=agentrouter|' .env
	@echo "✓ Провайдер: AgentRouter (AGENTROUTER_API_KEY .env файлында болуы керек)"

# ── Piper ─────────────────────────────────────────────────────────────────────

piper-download:
	@mkdir -p ~/.aidos/piper
	@echo "Piper kk_KZ-issai-high жүктелуде..."
	wget -q -O ~/.aidos/piper/kk_KZ-issai-high.onnx \
		"https://huggingface.co/rhasspy/piper-voices/resolve/main/kk/kk_KZ/issai/high/kk_KZ-issai-high.onnx"
	wget -q -O ~/.aidos/piper/kk_KZ-issai-high.onnx.json \
		"https://huggingface.co/rhasspy/piper-voices/resolve/main/kk/kk_KZ/issai/high/kk_KZ-issai-high.onnx.json"
	@echo "✓ Piper қазақ дауысы жүктелді: ~/.aidos/piper/"

# ── Wake word ─────────────────────────────────────────────────────────────────

wake-install:
	$(PIP) install openwakeword -q
	$(PYTHON) -c "from openwakeword.model import Model; Model(inference_framework='onnx')"
	@echo "✓ openWakeWord орнатылды"
	@echo ""
	@echo "  Custom 'Айдос' моделін жасау үшін:"
	@echo "  1. pip install openwakeword[training]"
	@echo "  2. python -m openwakeword.train --help"
	@echo "  3. .env файлына: WAKE_WORD_MODEL=~/.aidos/aidos_wake.onnx"

# ── Прочее ────────────────────────────────────────────────────────────────────

lint:
	$(VENV)/bin/ruff check src/

clean:
	rm -rf $(VENV)
	@echo "✓ Тазаланды"
