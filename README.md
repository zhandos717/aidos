# Aidos 🤖

**Қазақ тілді дауыстық AI көмекші** — Алиса сияқты, бірақ қазақша.

Офлайн дауыс тану `wav2vec2-large-xlsr-kazakh`, офлайн TTS Piper `kk_KZ-issai-high`, AI — Ollama немесе бұлттық провайдер (OpenRouter / AgentRouter).

---

## Мүмкіндіктер

| Функция | Мысал команда |
|---|---|
| 🕐 Уақыт және күн | «Aidos, қазір сағат нешеде?» |
| 🌤 Ауа райы | «Алматыда ауа райы қалай?» |
| 🎵 YouTube музыка | «Димаш Құдайберген ойна» / «включи музыку» |
| ⏰ Еске салғыш | «10 минуттан кейін еске сал» |
| 🧮 Калькулятор | «2 + 2 * 10 есепте» |
| 💬 AI сұхбат | Кез-келген сұрақ қазақша |
| 🎙 Дауыс кірісі | Микрофон + wav2vec2 |
| 🔊 Дауыс шығысы | Piper TTS / edge-tts |
| 🖥 Графикалық UI | iOS стиліндегі customtkinter |

---

## Стек

| Компонент | Технология |
|---|---|
| Дауыс тану (STT) | `aismlv/wav2vec2-large-xlsr-kazakh` (HuggingFace) |
| Дауыс синтезі (TTS) | Piper `kk_KZ-issai-high` (офлайн) / edge-tts (резерв) |
| AI мозгы | Ollama (Qwen3.5) / OpenRouter / AgentRouter (deepseek-v3.2) |
| Музыка | yt-dlp + ffplay (стриминг, жүктеусіз) |
| Ауа райы | wttr.in (тегін, API кілтісіз) |
| Скил жүйесі | `.py` және `.md` форматтары |
| UI | customtkinter, iOS Dark Mode палитрасы |

---

## Талаптар

- Python 3.12+
- [Ollama](https://ollama.com) (немесе OpenRouter/AgentRouter API кілті)
- `ffplay` (музыка стримингі үшін)
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
# AI_PROVIDER және API кілттерін баптаңыз

# 4. Ollama іске қосу (Ollama провайдері үшін)
make ollama-start
make ollama-pull

# 5. Piper қазақ дауысын жүктеу (офлайн TTS үшін, ~60 МБ)
make piper-download
```

---

## Іске қосу

```bash
make run          # мәтін режимі (терминал)
make run-voice    # дауыс режимі (микрофон + TTS)
make run-both     # мәтін кірісі + дауыс шығысы
make run-ui       # iOS стиліндегі графикалық интерфейс
```

---

## AI провайдер таңдау

`.env` файлында `AI_PROVIDER` мәнін өзгертіңіз:

```env
# Ollama (жергілікті)
AI_PROVIDER=ollama
OLLAMA_MODEL=qwen3.5:4b

# OpenRouter (бұлттық)
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-...
OPENROUTER_MODEL=qwen/qwen3-235b-a22b:free

# AgentRouter (deepseek-v3.2)
AI_PROVIDER=agentrouter
AGENTROUTER_API_KEY=sk-...
AGENTROUTER_MODEL=deepseek-v3.2
```

---

## Скил жүйесі

`src/aidos/skills/` қалтасына жаңа скилдер қосуға болады:

**Python скилі** (`calculator.py`):
```python
triggers = ["есепте", "калькулятор"]

def handle(query: str) -> str:
    ...
```

**Markdown скилі** (`cooking.md`):
```markdown
---
triggers: [рецепт, тағам, асхана]
---
Сен тамақ рецептері бойынша маман боласың...
```

---

## Баптау (.env)

| Айнымалы | Сипаттама | Әдепкі мән |
|---|---|---|
| `AI_PROVIDER` | Провайдер: `ollama` / `openrouter` / `agentrouter` | `ollama` |
| `OLLAMA_BASE_URL` | Ollama сервер мекенжайы | `http://localhost:11434` |
| `OLLAMA_MODEL` | Ollama модель атауы | `qwen3.5:4b` |
| `OPENROUTER_API_KEY` | OpenRouter API кілті | — |
| `AGENTROUTER_API_KEY` | AgentRouter API кілті | — |
| `AGENTROUTER_MODEL` | AgentRouter модель атауы | `deepseek-v3.2` |
| `DEFAULT_CITY` | Әдепкі қала (ауа райы) | `Алматы` |
| `PIPER_MODELS_DIR` | Piper модель қалтасы | `~/.aidos/piper` |
| `LOG_LEVEL` | Лог деңгейі | `INFO` |

---

## Архитектура

```
src/aidos/
├── core/
│   ├── config.py              # баптау, логтау
│   ├── ai_factory.py          # AI провайдер фабрикасы (Strategy паттерн)
│   ├── ollama_client.py       # Ollama клиенті
│   ├── openrouter_client.py   # OpenRouter клиенті
│   ├── agentrouter_client.py  # AgentRouter клиенті (Qwen Code CLI эмуляциясы)
│   ├── router.py              # ниет маршрутизаторы (скилдер → кілт сөздер → AI)
│   ├── skill_loader.py        # .py және .md скилдерін жүктеу
│   ├── voice.py               # STT (wav2vec2-large-xlsr-kazakh)
│   └── tts.py                 # TTS (Piper офлайн → edge-tts резерв)
├── agents/
│   ├── time_agent.py          # уақыт
│   ├── weather_agent.py       # ауа райы (wttr.in, API кілтісіз)
│   ├── music_agent.py         # YouTube музыка (yt-dlp + ffplay стриминг)
│   ├── reminder_agent.py      # еске салғыштар
│   └── ai_agent.py            # жалпы AI сұхбат
├── skills/
│   ├── calculator.py          # қауіпсіз AST калькулятор
│   └── cooking.md             # тағам рецептері скилі
└── ui/
    ├── theme.py               # iOS Dark Mode түстер палитрасы
    ├── session.py             # чат тарихы (JSON)
    ├── sidebar.py             # тарих боковой панелі
    ├── chat.py                # чат аймағы (бабблдар, кіріс)
    ├── app.py                 # негізгі терезе
    └── __init__.py            # run_ui() экспорты
```

**Маршрутизатор басымдылығы:** Скилдер → кілт сөздер → AI fallback.

**TTS басымдылығы:** Piper (офлайн) → edge-tts kk-KZ (онлайн) → edge-tts ru-RU.
