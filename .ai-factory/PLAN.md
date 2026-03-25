# Implementation Plan: Айдой — Қазақ AI Көмекшісі

Created: 2026-03-26

## Сипаттама

Алиса сияқты қазақ тілді дауыстық + мәтіндік AI көмекші.
- **Дауыс:** Whisper (STT) + edge-tts kk-KZ (TTS)
- **AI мозг:** Qwen via Ollama (жергілікті)
- **Роутер:** Hybrid (keyword + Qwen) agent router
- **Тіл:** Тек қазақша

## Settings
- Testing: жоқ
- Logging: verbose (LOG_LEVEL env арқылы)

## Архитектура

```
aidos/
├── src/aidos/
│   ├── core/
│   │   ├── config.py      # конфигурация, logging
│   │   ├── router.py      # IntentRouter
│   │   ├── voice.py       # STT (Whisper)
│   │   └── tts.py         # TTS (edge-tts)
│   ├── agents/
│   │   ├── time_agent.py
│   │   ├── weather_agent.py
│   │   ├── music_agent.py
│   │   ├── reminder_agent.py
│   │   └── ai_agent.py
│   └── main.py
├── pyproject.toml
└── .env.example
```

## Commit Plan

- **Commit 1** (1-3 тапсырмадан кейін): `feat: project setup and Ollama client`
- **Commit 2** (4-8 тапсырмадан кейін): `feat: add all agents (time, weather, music, reminder, AI)`
- **Commit 3** (9-11 тапсырмадан кейін): `feat: add voice I/O and main loop`

## Tasks

### Phase 1: Негіз
- [x] Task 1: Жоба структурасын және тәуелділіктерін баптау
- [x] Task 2: Ollama + Qwen байланысын орнату (depends on 1)
- [x] Task 3: Agent Router — ниет анықтаушысын жасау (depends on 2)
<!-- 🔄 Commit checkpoint: tasks 1-3 -->

### Phase 2: Агенттер
- [x] Task 4: Уақыт агентін жазу (TimeAgent) (depends on 1)
- [x] Task 5: Ауа райы агентін жазу (WeatherAgent) (depends on 1)
- [x] Task 6: Музыка агентін жазу (MusicAgent) (depends on 1)
- [x] Task 7: Еске салғыш агентін жазу (ReminderAgent) (depends on 2)
- [x] Task 8: AI агентін жазу (AIAgent — Qwen) (depends on 2)
<!-- 🔄 Commit checkpoint: tasks 4-8 -->

### Phase 3: Дауыс + Интерфейс
- [x] Task 9: Дауыс танудан мәтінге (STT — Whisper) (depends on 1)
- [x] Task 10: Мәтіннен дауысқа (TTS — қазақ тілі) (depends on 1)
- [x] Task 11: Негізгі цикл және CLI интерфейсі (main.py) (depends on 3-10)
<!-- 🔄 Commit checkpoint: tasks 9-11 -->
