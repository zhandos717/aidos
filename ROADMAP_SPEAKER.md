# Aidos — Колонка режиміне дайындық (Тех. тапсырма)

Мақсат: Aidos-ты толыққанды "Алиса" / "Окей Гугл" сияқты дауыстық колонкаға айналдыру.

---

## 1. Wake Word — Custom "Айдос" моделі

**Ағымдағы жағдай:** STT fallback жұмыс істейді бірақ баяу (~2-3 сек реакция).
**Мақсат:** openWakeWord арқылы <50 мс реакция.

### Не істеу керек:

**1.1 Дауыс деректерін жинау**
- "Айдос" сөзін 100-200 рет жазу (әр түрлі адамдар, ер/әйел, жас/кәрі)
- Фон шуы бар жазбалар: аспаздық, музыка, ТВ
- Формат: WAV, 16kHz, mono
- Ұсынылатын құрал: `scripts/record_wake_word.py` (жасау керек)

**1.2 Модельді үйрету**
```bash
pip install openwakeword[training]
python -m openwakeword.train \
  --positive_clips ~/.aidos/wakeword_data/positive/ \
  --negative_clips ~/.aidos/wakeword_data/negative/ \
  --output_dir ~/.aidos/ \
  --model_name aidos_wake
```

**1.3 .env-ке қосу**
```env
WAKE_WORD_MODEL=~/.aidos/aidos_wake.onnx
```

**Тексеру:** `make run-wake` → "Айдос" деп айт → <100 мс реакция болу керек.

---

## 2. Аппараттық платформа (Hardware)

**Ұсыныс: Raspberry Pi 4 (4GB RAM)**

| Компонент | Модель | Баға |
|---|---|---|
| Компьютер | Raspberry Pi 4 (4GB) | ~$55 |
| Микрофон | ReSpeaker 2-Mics Pi HAT | ~$15 |
| Колонка | USB немесе 3.5mm aux | ~$10 |
| SD карта | 32GB Class 10 | ~$8 |
| Блок питания | USB-C 5V/3A | ~$8 |

**Балама:** Mac Mini / ескі ноутбук + USB микрофон (бірден жұмыс істейді).

### Raspberry Pi орнату:
- Raspbian OS Lite (64-bit)
- Python 3.11+
- `sudo apt install ffmpeg portaudio19-dev`
- Git clone + `make install`

---

## 3. Аудио тізбегін жетілдіру

**3.1 Эхо компенсациясы (AEC)**
Колонка өз дауысын қайта тыңдамас үшін.

```bash
# Linux-та PulseAudio + echo cancellation
sudo apt install pulseaudio pulseaudio-module-echo-cancel
```

Немесе ReSpeaker HAT-тың кіріктірілген AEC-і.

**3.2 VAD (Voice Activity Detection) жақсарту**
Ағымдағы: RMS energy threshold (қарапайым).
Жақсарту: `silero-vad` моделі — шуды дұрыс сүзеді.

```python
# core/vad.py (жасау керек)
# silero-vad арқылы сөйлеу сегменттерін анықтау
```

**3.3 Динамикалық тыңдау**
Сөйлеп болған соң автоматты тоқтату (қазір 5 сек фиксирленген).

```python
# VoiceInput.listen() ішінде:
# VAD → сөйлеу басталды → сөйлеу тоқтады → жазуды аяқтау
```

---

## 4. Колонка режимі (Daemon)

**4.1 Systemd сервисі**
Raspberry Pi жүктелгенде автоматты іске қосу.

```ini
# /etc/systemd/system/aidos.service (жасау керек)
[Unit]
Description=Aidos Voice Assistant
After=sound.target network.target

[Service]
ExecStart=/home/pi/aidos/.venv/bin/python -m aidos.main --wake
WorkingDirectory=/home/pi/aidos
Restart=always
RestartSec=5
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
make install-service  # (Makefile-ге қосу керек)
```

**4.2 Watchdog**
Модель crash болса — автоматты қайта іске қосу (systemd Restart=always жабады бірақ process ішіндегі hang-ды емес).

---

## 5. Жауап сапасын жақсарту

**5.1 Streaming TTS**
Қазір: AI жауабын толық алып, сонан соң TTS → баяу.
Жақсарту: AI stream арқылы сөйлемдерді бөліп, TTS-ке кезекпен жіберу.

```python
# ai_agent.py → streaming response
# tts.py → sentence-by-sentence playback
```

**5.2 Interrupt (үзу)**
Aidos сөйлеп тұрғанда "Тоқта" деп айтса — TTS тоқтату.
Жүзеге асыру: wake word детекторды TTS ойнатып тұрғанда да іске қосу.

**5.3 Контекст сақтау**
"Ол кім?" — алдыңғы сұраққа байланысты жауап.
Ағымдағы AIAgent history бар, wake mode-да session-ды persist ету керек.

---

## 6. Жаңа агенттер / скилдер

| Скил | Сипаттама | Басымдылық |
|---|---|---|
| 🏠 Умный дом | MQTT / Home Assistant интеграциясы | Жоғары |
| 📅 Күнтізбе | Google Calendar / ics файл | Орташа |
| 📰 Жаңалықтар | RSS feed (казақша медиа) | Орташа |
| 🌐 Веб іздеу | DuckDuckGo API | Орташа |
| ⏱ Таймер | `asyncio` негізінде | Төмен |
| 💡 Анекдот/факт | Казақша деректер базасы | Төмен |

---

## 7. Офлайн режим

Қазір AgentRouter / OpenRouter интернет керек.
Толық офлайн үшін:

- **STT:** wav2vec2 ✅ (офлайн)
- **TTS:** Piper ✅ (офлайн)
- **AI:** Ollama + Qwen3.5 ✅ (офлайн, бірақ Raspberry Pi-да баяу)
  - Балама: `llama.cpp` + quantized 4-bit модель (Q4_K_M ~2GB)

```bash
make use-qwen  # офлайн режимге ауысу
```

---

## 8. Makefile тапсырмалары (қосу керек)

```makefile
make install-service   # systemd сервисті орнату
make start-service     # сервисті іске қосу
make stop-service      # сервисті тоқтату
make logs              # journalctl -u aidos -f
make record-wakeword   # 'Айдос' үлгілерін жазу скрипті
```

---

## Орындау кезегі

```
[1] Wake word моделін үйрету    ← ең маңызды, дереу бастауға болады
[2] VAD жақсарту (silero-vad)   ← тыңдау дұрыстығы
[3] Streaming TTS               ← жауап жылдамдығы
[4] Hardware алу (Raspberry Pi) ← физикалық колонка
[5] Systemd daemon              ← автозапуск
[6] Умный дом интеграциясы      ← кеңейтілген функционал
```
