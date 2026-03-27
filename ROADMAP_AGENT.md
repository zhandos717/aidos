# Aidos — AI Агент Роадмап

Ағымдағы жағдай: `AIAgent` → stateless chat, deque history (10 хабар), ешқандай инструмент жоқ, keyword роутинг.
Мақсат: планлауды, жадты, инструменттерді, мультиагенттікті меңгерген толыққанды AI агент.

---

## Фаза 1 — Негіз: Жад + Инструменттер

### 1.1 Ұзақ мерзімді жад (Long-term Memory)

**Қазір:** `deque(maxlen=10)` — сессия аяқталса бәрі жойылады.

**Жасау керек:** `src/aidos/core/memory.py`

```
Деңгейлер:
  Working memory   → ағымдағы сессия (deque, бар)
  Episodic memory  → өткен сессиялар (SQLite / JSON)
  Semantic memory  → пайдаланушы туралы фактілер (векторлық БД)
```

Мысал:
```
Пайдаланушы: "Менің атым Алибек"
→ semantic memory: {name: "Алибек"}

Келесі сессияда:
Пайдаланушы: "Мені есіңде бар ма?"
Aidos: "Ия, сіздің атыңыз Алибек"
```

Файлдар:
- `core/memory.py` — MemoryStore класы (SQLite)
- `core/embeddings.py` — семантикалық іздеу үшін (sentence-transformers)

---

### 1.2 Function Calling (Инструмент шақыру)

**Қазір:** Роутер keyword арқылы агентке бағыттайды — AI бұл туралы білмейді.

**Мақсат:** AI өзі инструментті таңдасын.

```python
tools = [
    {
        "name": "get_weather",
        "description": "Қаладағы ауа райын алу",
        "parameters": {"city": "string"}
    },
    {
        "name": "play_music",
        "description": "YouTube-тан музыка ойнату",
        "parameters": {"query": "string"}
    },
    {
        "name": "set_reminder",
        "description": "Еске салғышты орнату",
        "parameters": {"text": "string", "minutes": "int"}
    },
    {
        "name": "web_search",
        "description": "Интернеттен іздеу",
        "parameters": {"query": "string"}
    },
]
```

Файлдар:
- `core/tool_registry.py` — инструменттерді тіркеу + диспетчер
- `agents/ai_agent.py` — function calling циклі (OpenAI-compatible format)

---

### 1.3 RAG (Retrieval-Augmented Generation)

Пайдаланушының өз деректерін сұрай алу:

```
Пайдаланушы: "Кешегі кездесу туралы не болды?"
→ episodic memory-дан іздеу → контекстке қосу → AI жауабы
```

```
Пайдаланушы: "Осы PDF-ті оқы" [файл]
→ чанктарға бөлу → векторлық БД → сұраққа қатысты бөліктерді іздеу
```

Стек: `chromadb` (жергілікті векторлық БД) + `sentence-transformers`

Файлдар:
- `core/rag.py` — RAGEngine класы
- `core/chunker.py` — мәтінді чанктарға бөлу

---

## Фаза 2 — Ойлау: Жоспарлау + ReAct

### 2.1 ReAct паттерн (Reason + Act)

**Қазір:** User → AI → жауап (бір қадам).

**ReAct:** User → AI ойланады → инструментті шақырады → нәтижені бағалайды → қайта ойланады → жауап.

```
Сұрақ: "Алматыдағы ауа райына қарай маған не кию керек?"

Ой: "Алматының ауа райын білу керек"
Әрекет: get_weather(city="Алматы")
Нәтиже: "15°C, жаңбыр"

Ой: "15°C жаңбырлы — жылы киім, жаңбыр куртка"
Жауап: "Жылы куртка және жаңбырдан қорғайтын киім киюіңізді ұсынамын"
```

Файлдар:
- `core/react_agent.py` — ReActAgent класы
- `agents/ai_agent.py` → ReActAgent-қа migrate ету

---

### 2.2 Мультиқадамды тапсырмалар (Multi-step Tasks)

```
Пайдаланушы: "Маған ертең 9-да оянуға еске сал, ауа райына қарай не кию керегін айт"

Жоспар:
  1. set_reminder(text="Оян", time="09:00")
  2. get_weather(city=user.city, date="tomorrow")
  3. clothing_advice(weather=result)
  4. Барлығын біріктіріп жауап беру
```

---

### 2.3 AI арқылы Intent анықтау

**Қазір:** Keyword regex → баяу жаңарту, тілге тәуелді.

**Жақсарту:** AI-ға intent classification жүктеу.

```python
# router.py ішінде
# Keyword матч болмаса → AI-дан intent сұрау
# "Осы мәтін қай категорияға жатады: time/weather/music/reminder/general?"
```

---

## Фаза 3 — Жеке бейімделу (Personalization)

### 3.1 Пайдаланушы профилі

```python
# core/user_profile.py
profile = {
    "name": "Алибек",
    "city": "Астана",
    "language_pref": "kk",      # kk / ru / en
    "wake_time": "08:00",
    "music_taste": ["Dimash", "казақ поп"],
    "interests": ["спорт", "технология"],
}
```

Профиль автоматты жиналады сөйлесулерден.

---

### 3.2 Адаптивті жауап стилі

- Формальды / бейресми сөйлесу стилін анықтау
- Егер пайдаланушы орысша жазса → орысша жауап
- Егер қазақша → қазақша

---

### 3.3 Proactive Notifications

Пайдаланушы сұрамай-ақ хабарлама беру:
```
Таңертең 8:00: "Қайырлы таң! Бүгін Астанада -10°C, жылы киіңіз"
Еске салғыш мерзімі: "Кездесуге 15 минут қалды"
Музыка тоқтаса: "Тізім аяқталды, жалғастырайын ба?"
```

Файлдар:
- `core/scheduler.py` — APScheduler негізінде
- `agents/proactive_agent.py`

---

## Фаза 4 — Мультиагент Архитектура

### 4.1 Supervisor + Sub-agents

```
SupervisorAgent
├── PlannerAgent      → тапсырманы бөліктерге бөлу
├── ResearchAgent     → веб іздеу + RAG
├── ExecutorAgent     → инструменттерді шақыру
└── CriticAgent       → жауапты тексеру, сапаны бағалау
```

### 4.2 Параллельді орындау

```python
# Бірнеше агент қатар жұмыс істейді
results = await asyncio.gather(
    weather_agent.handle(city),
    calendar_agent.today_events(),
    news_agent.latest_kz(),
)
# SupervisorAgent барлығын біріктіреді
```

---

## Фаза 5 — Модель жетілдіру

### 5.1 Казақша fine-tuning датасеті

Жинау керек:
- Қазақша Q&A жұптары (домен: тұрмыс, технология, тарих)
- Диалог трейстері (пайдаланушы ↔ Aidos)
- Инструкция жұптары (instruction → output)

Ұсынылатын базалар:
- [KazNLP](https://github.com/kaznlp) корпустары
- Common Crawl қазақша сегменті
- Wikipedia қазақша (kk.wikipedia.org)

### 5.2 LoRA Fine-tuning

```bash
# unsloth арқылы жылдам fine-tuning (4x жылдам, 60% аз жад)
pip install unsloth
python scripts/finetune_lora.py \
  --base_model Qwen/Qwen2.5-7B \
  --dataset ~/.aidos/finetune_data/ \
  --output ~/.aidos/aidos-lora
```

### 5.3 Бағалау (Evaluation)

```python
# scripts/eval_agent.py (жасау керек)
# Тест сұрақтар → агент жауабы → метрикалар
metrics = {
    "intent_accuracy": 0.0,   # дұрыс агентке бағыттау %
    "response_quality": 0.0,  # BLEU / LLM-as-judge
    "latency_p95": 0.0,       # мс
    "kazakh_ratio": 0.0,       # қазақша жауап %
}
```

---

## Орындау кезегі

```
Фаза 1 (1-2 апта)
  [1.1] core/memory.py — SQLite episodic memory
  [1.2] core/tool_registry.py — function calling
  [1.3] agents/ai_agent.py — ReAct loop (қарапайым)

Фаза 2 (1 апта)
  [2.1] RAG — chromadb + sentence-transformers
  [2.2] AI intent classification (keyword backup сақтай отырып)

Фаза 3 (1 апта)
  [3.1] Пайдаланушы профилі
  [3.2] core/scheduler.py — proactive notifications

Фаза 4 (2+ апта)
  [4.1] Мультиагент архитектурасы
  [4.2] Параллельді орындау (asyncio)

Фаза 5 (жалғасымды)
  [5.1] Датасет жинау
  [5.2] LoRA fine-tuning
  [5.3] Автоматты бағалау
```

---

## Ағымдағы vs Мақсатты архитектура

```
ҚАЗІР:
User → Router (keyword) → Agent.handle() → LLM → жауап

МАҚСАТ:
User
  → SupervisorAgent
      → PlannerAgent (не істеу керек?)
      → ToolRegistry (инструменттерді шақыру)
      → MemoryStore (контекст + жад)
      → RAGEngine (жеке деректер)
      → LLM (финальды жауап)
      → CriticAgent (сапаны тексеру)
  → User
```
