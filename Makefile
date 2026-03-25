.DEFAULT_GOAL := help
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help install run run-voice run-both ollama-start ollama-pull clean

help:
	@echo "Айдой — қазақ AI көмекші"
	@echo ""
	@echo "  make install      — тәуелділіктерді орнату"
	@echo "  make run          — мәтін режимінде іске қосу"
	@echo "  make run-voice    — дауыс режимінде іске қосу"
	@echo "  make run-both     — аралас режимде іске қосу"
	@echo "  make ollama-start — Ollama серверін іске қосу"
	@echo "  make ollama-pull  — Qwen моделін жүктеу"
	@echo "  make clean        — venv тазалау"

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip -q
	$(PIP) install -e . -q
	@echo "✓ Тәуелділіктер орнатылды"
	@[ -f .env ] || (cp .env.example .env && echo "✓ .env файлы жасалды — WEATHER_API_KEY қосыңыз")

run:
	$(PYTHON) -m aidos.main

run-voice:
	$(PYTHON) -m aidos.main --voice

run-both:
	$(PYTHON) -m aidos.main --both

ollama-start:
	ollama serve &

ollama-pull:
	ollama pull qwen2.5:7b

clean:
	rm -rf $(VENV)
	@echo "✓ Тазаланды"
