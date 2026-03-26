# Aidos 🤖

**Қазақ тілді дауыстық AI көмекші** — Алиса сияқты, бірақ қазақша.

Толықтай офлайн жұмыс істейді: дауыс кірісі Whisper арқылы, дауыс шығысы Microsoft Edge TTS (`kk-KZ-AigrimNeural`) арқылы, AI мозгы — Ollama арқылы Qwen.

---

## Мүмкіндіктер

| Функция | Мысал команда |
|---|---|
| 🕐 Уақыт және күн | «Aidos, қазір сағат нешеде?» |
| 🌤 Ауа райы | «Алматыда ауа райы қалай?» |
| 🎵 Музыка | «Музыка ойна» / «Тоқтат» |
| ⏰ Еске салғыш | «10 минуттан кейін еске сал» |
| 💬 AI сұхбат | Кез-келген сұрақ қазақша |

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
```

```bash
# 4. Ollama іске қосу (бөлек терминалда)
make ollama-start

# 5. Моделді жүктеу (бір рет, ~4 GB)
make ollama-pull
```

---

## Іске қосу

```bash
make run          # мәтін режимі
make run-voice    # дауыс режимі (микрофон + TTS)
make run-both     # мәтін кірісі + дауыс шығысы
```

---

## Демо

```
Сіз:   Aidos, қазір сағат нешеде?
Aidos: Қазір сағат 14:30, 2026 жылдың 26 наурызы, бейсенбі.

Сіз:   Алматыда ауа райы қалай?
Aidos: Алматы қаласының ауа райы: Ашық аспан. Температура 18°C, сезіну 17°C.

Сіз:   10 минуттан кейін кездесуге еске сал
Aidos: Жарайды, 10 минуттан кейін ескертемін: кездесуге

Сіз:   музыка ойна
Aidos: Ойнатылуда: Abai - Kozimnin Karasy

Сіз:   сау бол
Aidos: Сау болыңыз!
```

---

## Конфигурация

Барлық баптаулар `.env` файлы арқылы:

| Айнымалы | Сипаттама | Әдепкі мән |
|---|---|---|
| `OLLAMA_BASE_URL` | Ollama сервер мекенжайы | `http://localhost:11434` |
| `OLLAMA_MODEL` | Модель атауы | `qwen2.5:7b` |
| `WEATHER_API_KEY` | OpenWeatherMap API кілті | — |
| `DEFAULT_CITY` | Әдепкі қала | `Алматы` |
| `MUSIC_DIR` | Музыка қалтасы | `~/Music` |
| `LOG_LEVEL` | Лог деңгейі | `INFO` |

---

## Архитектура

```
src/aidos/
├── core/
│   ├── config.py         # конфигурация, logging
│   ├── ollama_client.py  # Qwen/Ollama клиенті
│   ├── router.py         # ниет маршрутизаторы
│   ├── voice.py          # STT (Whisper)
│   └── tts.py            # TTS (edge-tts)
└── agents/
    ├── time_agent.py
    ├── weather_agent.py
    ├── music_agent.py
    ├── reminder_agent.py
    └── ai_agent.py
```

**Роутер** — гибридті: алдымен keyword матчинг, сосын AI fallback.
