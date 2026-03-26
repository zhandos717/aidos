# Aidos 🤖

**Қазақ тілді дауыстық AI көмекші** — Алиса сияқты, бірақ қазақша.

Толықтай офлайн жұмыс істейді: дауыс кірісі `wav2vec2-large-xlsr-kazakh` арқылы, дауыс шығысы Piper TTS `kk_KZ-issai-medium` арқылы, AI мозгы — Ollama арқылы Qwen3.5.

---

## Мүмкіндіктер

| Функция | Мысал команда |
|---|---|
| 🕐 Уақыт және күн | «Aidos, қазір сағат нешеде?» |
| 🌤 Ауа райы | «Алматыда ауа райы қалай?» |
| 🎵 YouTube музыка | «Димаш Құдайберген ойна» |
| ⏰ Еске салғыш | «10 минуттан кейін еске сал» |
| 💬 AI сұхбат | Кез-келген сұрақ қазақша |

---

## Стек

| Компонент | Технология |
|---|---|
| STT | `aismlv/wav2vec2-large-xlsr-kazakh` (HuggingFace) |
| TTS | Piper `kk_KZ-issai-medium` (офлайн) / edge-tts (fallback) |
| AI | Qwen3.5:4b via Ollama |
| Музыка | yt-dlp + YouTube |
| Роутер | Keyword + AI hybrid |

---

## Талаптар

- Python 3.12+
- [Ollama](https://ollama.com)
- Микрофон (дауыс режимі үшін)

---

## Орнату

```bash
# 1. Репозиторийді клондау
git clone https://github.com/zhandos717/aidos.git
cd aidos

# 2. Тәуелділіктерді орнату
make install

# 3. .env файлын толтыру
cp .env.example .env
# .env файлын ашып WEATHER_API_KEY қосыңыз (openweathermap.org — тегін)

# 4. Ollama іске қосу (бөлек терминалда)
make ollama-start

# 5. Моделді жүктеу (бір рет, ~3.4 GB)
make ollama-pull

# 6. Piper қазақ дауысын жүктеу (офлайн TTS үшін, ~60 MB)
make piper-download
```

---

## Іске қосу

```bash
make run          # мәтін режимі
make run-voice    # дауыс режимі (микрофон + TTS)
make run-both     # мәтін кірісі + дауыс шығысы
```

---

## AI Модель таңдау

```bash
make use-qwen      # Qwen3.5:4b — жылдам, 201 тіл (әдепкі)
make use-sherkala  # Sherkala-8B — қазақшаға арналған

# Sherkala жүктеу
make ollama-pull-sherkala
```

---

## Демо

```
Сіз:   Aidos, қазір сағат нешеде?
Aidos: Қазір сағат 14:30, 2026 жылдың 26 наурызы, бейсенбі.

Сіз:   Алматыда ауа райы қалай?
Aidos: Алматы қаласының ауа райы: Ашық аспан. Температура 18°C, сезіну 17°C.

Сіз:   Димаш Құдайберген ойна
Aidos: Жүктелуде... Dimash Kudaibergen - Love Of Tired Swans

Сіз:   10 минуттан кейін кездесуге еске сал
Aidos: Жарайды, 10 минуттан кейін ескертемін: кездесуге

Сіз:   сау бол
Aidos: Сау болыңыз!
```

---

## Конфигурация

| Айнымалы | Сипаттама | Әдепкі мән |
|---|---|---|
| `OLLAMA_BASE_URL` | Ollama сервер мекенжайы | `http://localhost:11434` |
| `OLLAMA_MODEL` | Модель атауы | `qwen3.5:4b` |
| `WEATHER_API_KEY` | OpenWeatherMap API кілті | — |
| `DEFAULT_CITY` | Әдепкі қала | `Алматы` |
| `MUSIC_DIR` | Жергілікті музыка қалтасы | `~/Music` |
| `PIPER_MODELS_DIR` | Piper модель қалтасы | `~/.aidos/piper` |
| `LOG_LEVEL` | Лог деңгейі | `INFO` |

---

## Архитектура

```
src/aidos/
├── core/
│   ├── config.py         # конфигурация, logging
│   ├── ollama_client.py  # Qwen/Ollama клиенті
│   ├── router.py         # ниет маршрутизаторы
│   ├── voice.py          # STT (wav2vec2-large-xlsr-kazakh)
│   └── tts.py            # TTS (Piper офлайн → edge-tts fallback)
└── agents/
    ├── time_agent.py     # уақыт
    ├── weather_agent.py  # ауа райы (OpenWeatherMap)
    ├── music_agent.py    # YouTube музыка (yt-dlp)
    ├── reminder_agent.py # еске салғыштар
    └── ai_agent.py       # жалпы AI сұхбат
```

**Роутер** — гибридті: алдымен keyword матчинг, сосын AI fallback.

**TTS приоритет:** Piper (офлайн) → edge-tts kk-KZ (онлайн) → edge-tts ru-RU.
