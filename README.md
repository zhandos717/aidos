# Aidos 🤖

**Казахский голосовой AI-ассистент** — как Алиса, но на казахском языке.

Работает полностью офлайн: голосовой ввод через Whisper, синтез речи через Microsoft Edge TTS (`kk-KZ-AigrimNeural`), AI-мозг — Qwen через Ollama.

---

## Возможности

| Функция | Пример команды |
|---|---|
| 🕐 Время и дата | «Aidos, қазір сағат нешеде?» |
| 🌤 Погода | «Алматыда ауа райы қалай?» |
| 🎵 Музыка | «Музыка ойна» / «Тоқтат» |
| ⏰ Напоминания | «10 минуттан кейін еске сал» |
| 💬 AI-диалог | Любой вопрос на казахском |

---

## Требования

- Python 3.12+
- [Ollama](https://ollama.com)
- Микрофон (для голосового режима)

---

## Установка

```bash
# 1. Клонировать репозиторий
git clone https://github.com/zhandos717/aidos.git
cd aidos

# 2. Установить зависимости
make install

# 3. Заполнить .env
cp .env.example .env
# Открыть .env и вставить WEATHER_API_KEY (бесплатно на openweathermap.org)
```

```bash
# 4. Запустить Ollama (в отдельном терминале)
make ollama-start

# 5. Загрузить модель (один раз, ~4 GB)
make ollama-pull
```

---

## Запуск

```bash
make run          # текстовый режим
make run-voice    # голосовой режим (микрофон + TTS)
make run-both     # текстовый ввод + голосовой вывод
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

Все настройки через `.env` файл:

| Переменная | Описание | По умолчанию |
|---|---|---|
| `OLLAMA_BASE_URL` | Адрес Ollama сервера | `http://localhost:11434` |
| `OLLAMA_MODEL` | Название модели | `qwen2.5:7b` |
| `WEATHER_API_KEY` | Ключ OpenWeatherMap | — |
| `DEFAULT_CITY` | Город по умолчанию | `Алматы` |
| `MUSIC_DIR` | Папка с музыкой | `~/Music` |
| `LOG_LEVEL` | Уровень логов | `INFO` |

---

## Архитектура

```
src/aidos/
├── core/
│   ├── config.py         # конфигурация, logging
│   ├── ollama_client.py  # клиент Qwen/Ollama
│   ├── router.py         # маршрутизатор намерений
│   ├── voice.py          # STT (Whisper)
│   └── tts.py            # TTS (edge-tts)
└── agents/
    ├── time_agent.py
    ├── weather_agent.py
    ├── music_agent.py
    ├── reminder_agent.py
    └── ai_agent.py
```

**Роутер** — гибридный: сначала keyword-matching, при неудаче — AI fallback.
