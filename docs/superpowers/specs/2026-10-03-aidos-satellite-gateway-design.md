# Aidos: шлюз для колонок ESP32-S3-BOX-3 (Rust) + gRPC-мозг (Python)

Дата: 2026-10-03 · Статус: дизайн согласован по секциям, ждёт ревью спеки

## 1. Цель и рамки

**Зачем.** Сделать из aidos «колонку»: BOX-3 в комнате, фраза «Айдос, …» → ответ голосом на казахском. Проект развивается ради обучения и портфолио, поэтому важны чистые границы компонентов, тесты, CI и демо-видео, а не скорость выхода на рынок.

**Критерии успеха v1:**
- py-xiaozhi на Mac, а затем реальный BOX-3, ведут диалог через шлюз и мозг; от конца фразы до первого звука ответа ≤ 4 с (медиана) на Mac.
- Напоминание, созданное с колонки, звучит на этой же колонке, в том числе после перезапуска любого процесса.
- «Димаш ойна» играет музыку на колонке, а wake word ставит её на паузу.
- Шлюз безопасно работает на VPS: привязка по коду, токены, TLS.
- CI зелёный; есть интеграционный тест шлюза без железа и без моделей.

**Не входит в v1:** стриминг ответа LLM; подавление эха сверх `abort`; несколько шлюзов; OTA-обновления прошивки; своя модель wake word (используется MultiNet в xiaozhi); mTLS между шлюзом и мозгом.

## 2. Принятые решения

| Решение | Выбор | Почему |
|---|---|---|
| Прошивка | форк [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) (MIT), меняется только URL сервера и wake word | BOX-3 поддерживается из коробки: AEC, Opus, провижининг, OTA, экран |
| Протокол колонки | [WebSocket-протокол xiaozhi](https://github.com/78/xiaozhi-esp32/blob/main/docs/websocket.md), версия 1 (сырые Opus-кадры) | документирован, есть сторонний клиент для тестов (py-xiaozhi) |
| Шлюз | Rust: `tokio`, `axum`, `audiopus`, `ort` (Silero VAD), `sqlx` (SQLite), `tonic` | сеть, потоковый звук, работа 24/7, один бинарник; учебная цель |
| Мозг | Python, существующий `src/aidos` + новый gRPC-сервис | AI-экосистема: wav2vec2, Piper, агенты, LLM |
| Связь шлюз ↔ мозг | gRPC bidi-stream `Link`, один на шлюз | строгий контракт в `.proto`, оба направления (ход и пуш) в одном стриме |
| LLM | `openai/gpt-6-luna` через OpenRouter | бенчмарк 2026-10-03: чистый казахский, ~2 с, ~$0.06 за 1000 запросов |
| TTS | Piper `kk_KZ-*` (по умолчанию `issai-high`, выбор через `PIPER_VOICE`) | офлайн, ×9–×90 быстрее реального времени на CPU |
| STT | `aismlv/wav2vec2-large-xlsr-kazakh` | уже используется в aidos |
| Развёртывание | разработка на Mac (`ws://` по LAN), потом VPS (Caddy + TLS) | быстрая итерация, тот же код в проде |

## 3. Архитектура

```
BOX-3 (xiaozhi) ──wss: Opus 16k↑ / 24k↓──▶ gateway/ (Rust)
                                            • /ota, /ws, протокол xiaozhi
                                            • Opus ↔ PCM, ресемплинг
                                            • Silero VAD → конец фразы
                                            • реестр колонок, токены, привязка (SQLite)
                                            • автомат состояний колонки
                                            • музыка: ffmpeg → Opus
                                            • очередь пушей (SQLite)
                                                   │ gRPC Link (localhost + LINK_TOKEN)
                                            src/aidos (Python), пакет aidos.brain
                                            • STT wav2vec2-kk
                                            • IntentRouter, агенты, память, LLM
                                            • Piper → PCM по предложениям
                                            • таймеры напоминаний → Push
```

**Граница ответственности.** Шлюз знает о колонках, сети и звуке, но не знает о языке. Мозг знает о тексте, агентах и моделях, но не знает о колонках и Opus: он работает с `device_id` и PCM. VAD находится в шлюзе, чтобы не гонять тишину по сети. Музыку ищет мозг (`MusicAgent` → `Action.play_stream{url,title}`), а играет шлюз.

**Репозиторий (монорепо):**
```
proto/aidos/link/v1/link.proto     # контракт
gateway/                           # Cargo-проект aidos-gateway
  src/{main,config,xiaozhi,audio,vad,device,registry,pairing,link,music,push}.rs
  assets/                          # заготовленные фразы ошибок (WAV, Piper)
  models/silero_vad.onnx
src/aidos/brain/                   # gRPC-сервис мозга
  server.py, turn.py, device_ctx.py, sentences.py, gen/ (код из .proto)
```

## 4. Контракт gRPC

```proto
syntax = "proto3";
package aidos.link.v1;

service Brain {
  rpc Link(stream GatewayEvent) returns (stream BrainEvent);
}

message GatewayEvent {
  oneof kind {
    Utterance   utterance = 1;
    Abort       abort     = 2;
    DeviceState state     = 3;
    PushAck     push_ack  = 4;
  }
}

message Utterance   { string device_id = 1; string turn_id = 2; bytes pcm_s16le = 3; uint32 sample_rate = 4; }
message Abort       { string device_id = 1; string turn_id = 2; }
message DeviceState { string device_id = 1; bool online = 2; }
message PushAck     { string push_id = 1; }

message BrainEvent {
  oneof kind {
    Transcript  transcript = 1;
    SpeechChunk speech     = 2;
    Action      action     = 3;
    TurnEnd     end        = 4;
    Push        push       = 5;
  }
}

message Transcript  { string device_id = 1; string turn_id = 2; string text = 3; }
message SpeechChunk { string device_id = 1; string turn_id = 2; string text = 3; bytes pcm_s16le = 4; uint32 sample_rate = 5; }
message TurnEnd     { string device_id = 1; string turn_id = 2; bool error = 3; }
message Push        { string push_id = 1; string device_id = 2; string text = 3; SpeechChunk speech = 4; int64 created_at_unix = 5; }

message Action {
  string device_id = 1;
  string turn_id   = 2;
  oneof kind {
    PlayStream play   = 3;
    Empty      stop   = 4;
    Empty      pause  = 5;
    Empty      resume = 6;
  }
}
message PlayStream { string url = 1; string title = 2; }
message Empty {}
```

Шлюз — клиент: он подключается к мозгу (`BRAIN_ADDR`, по умолчанию `127.0.0.1:50051`) и передаёт `LINK_TOKEN` в метаданных `authorization: Bearer …`. При обрыве переподключается с паузой 1→2→4…→30 с. Мозг принимает одно активное соединение `Link`; новое соединение заменяет старое.

## 5. Потоки данных

**Подключение колонки.** `POST /ota` (заголовки `Device-Id`, `Client-Id`) → если устройство привязано, ответ содержит `websocket{url, token}`. Колонка открывает `/ws` с `Authorization: Bearer <token>`; шлюз находит устройство по хешу токена, а при несовпадении с `Device-Id` отклоняет соединение. Обмен `hello`: вверх Opus 16 кГц, вниз 24 кГц, кадры по 60 мс. Шлюз шлёт мозгу `DeviceState{online}` и доставляет пуши, накопленные в очереди.

**Ход:**
1. Колонка: wake word (MultiNet) → `listen{detect}` → `listen{start, mode:auto}` → Opus-кадры.
2. Шлюз: Opus → PCM 16 кГц → Silero VAD (кадр 512 сэмплов; порог 0.5; минимум речи 250 мс; конец фразы после 1000 мс тишины; pre-roll 300 мс; максимум 12 с) → `Utterance` целиком.
3. Мозг: wav2vec2 → `Transcript` → `IntentRouter.route()` в `asyncio.to_thread` с `contextvar current_device` → ответ → `clean_for_speech` → деление на предложения → Piper по каждому предложению → `SpeechChunk` → `TurnEnd`. `Action` отправляется, если агент его вернул.
4. Шлюз: `stt{text}` → `tts{start}` → для каждого `SpeechChunk`: `tts{sentence_start,text}` и Opus 24 кГц в темпе реального времени (запас ~120 мс) → `tts{stop}`.
5. Перебивание: `abort` от колонки или новый `listen{detect}` во время ответа → шлюз останавливает отправку и шлёт мозгу `Abort` → мозг отменяет задачу хода.

**Автомат состояний колонки (шлюз):** `idle → listening → thinking → speaking → idle`. Отдельно существует `playing_music` (из `idle`), и на время хода музыка ставится на паузу. Одновременно идёт не больше одного хода на колонку.

**Музыка.** `Action.play_stream{url}` → шлюз запускает `ffmpeg -i <url> -f s16le -ar 24000 -ac 1 -` → Opus → колонка внутри `tts{start}/{stop}`. Wake word во время музыки → пауза (шлюз перестаёт читать stdout ffmpeg) → ход → продолжение, если пришло не `Action.stop`. Новый `play_stream` заменяет текущий поток.

**Напоминания.** `ReminderAgent` при создании запоминает `device_id` из `contextvar`. Таймеры восстанавливаются при старте мозга (исправление бага: сейчас они после перезапуска не срабатывают). Срабатывание → `Push` → шлюз записывает его в SQLite и отвечает `PushAck` → мозг помечает напоминание доставленным. Доставка: колонка `idle` → сразу (`alert` + звук); занята → после возврата в `idle`; офлайн → при следующем `hello`. Пуш старше 12 ч выбрасывается.

**Изменения в существующем Python-коде:**
- `MusicAgent`: если задан `current_device`, вместо `ffplay` возвращает `Action`; без него (текст, UI) работает как раньше.
- `ReminderAgent`: поле `device_id`, восстановление таймеров при старте, колбэк пуша вместо `tts_callback`, если задано устройство.
- `AIAgent`: `session_id` определяется по `device_id`, у каждой колонки свой диалог.
- `TTSEngine`: отдельный метод `synthesize(text) -> (pcm, sample_rate)`; `speak()` использует его для локального воспроизведения.

## 6. Безопасность

- **Привязка.** Неизвестный `Device-Id` на `/ota` → 6-значный код (TTL 10 мин, не больше 10 ожидающих привязки) в `activation{code,message}`; BOX-3 показывает его и произносит. Подтверждение на сервере: `aidos-gateway devices approve <code>`; есть ещё `devices list` и `devices revoke <device_id>`. Перед реализацией нужно сверить точный формат ответа `/ota` с исходниками xiaozhi.
- **Токены.** 32 случайных байта (base64url); в SQLite хранится только SHA-256.
- **TLS.** На VPS шлюз слушает `127.0.0.1`, а Caddy терминирует `wss`. Дома используется `ws://` по LAN.
- **gRPC.** Только `localhost` + `LINK_TOKEN`.
- **Лимиты.** Один активный ход, фраза до 12 с, не больше 20 ходов в минуту на колонку.
- **Приватность.** Звук не сохраняется. Транскрипты попадают в лог только на уровне `debug`.

## 7. Обработка ошибок

Короткие фразы ошибок заранее генерируются скриптом через Piper в `gateway/assets/`: `brain_unavailable.wav` («Кешіріңіз, қазір жауап бере алмаймын»), `not_understood.wav` («Түсінбедім, қайталаңызшы»), `music_failed.wav` («Музыканы ойнату мүмкін болмады»).

| Ситуация | Поведение |
|---|---|
| Мозг недоступен или `Link` оборвался | переподключение с нарастающей паузой; колонке `brain_unavailable` |
| Ход дольше 20 с | `Abort` мозгу, `brain_unavailable` |
| Колонка отключилась посреди хода | `Abort` мозгу; пуши остаются в очереди |
| `TurnEnd{error}` или пустой `Transcript` | `not_understood` |
| Сбой `ffmpeg` | `music_failed`, запись в лог |
| Пуш для колонки, которая офлайн | очередь в SQLite, выбрасывается через 12 ч |

Логи: `tracing` в шлюзе и `logging` в мозге, сквозные поля `device_id` и `turn_id`.

## 8. Тестирование

- **Rust, модульные тесты:** разбор сообщений xiaozhi; сегментатор VAD (порт `UtteranceSegmenter` с теми же кейсами, что в `tests/test_utterance_segmenter.py`); обратимость Opus; переходы автомата состояний; правила очереди пушей; TTL кода привязки и проверка токена.
- **Rust, интеграционный тест:** фейковый мозг (tonic-сервер с заготовленными ответами) и фейковая колонка (WS-клиент, Opus из WAV) → проверка последовательности `stt`, `tts{start}`, `sentence_start`, длительности кадров, `tts{stop}`; плюс сценарий `abort`.
- **Python:** gRPC-сервис мозга с фейковыми STT, TTS и роутером (`Utterance → Transcript → SpeechChunk* → TurnEnd`, отмена через `Abort`, деление на предложения, доставка пушей с ack).
- **Вручную:** py-xiaozhi на Mac против связки шлюз + мозг, потом BOX-3.
- **CI (GitHub Actions):** `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test`, `ruff`, `pytest`, проверка, что код в `src/aidos/brain/gen/` соответствует `.proto`.

## 9. Этапы

| # | Этап | Готово, когда |
|---|---|---|
| M0 | `.proto`, каркасы `gateway/` и `aidos/brain/`, генерация кода, CI | всё собирается, CI зелёный |
| M1 | gRPC-мозг: ход, предложения, `current_device`, `TTSEngine.synthesize` | тестовый клиент отправляет WAV и получает озвученный ответ |
| M2 | Ядро шлюза: xiaozhi WS, Opus, VAD, мост к мозгу, белый список устройств в конфиге | py-xiaozhi на Mac ведёт диалог |
| M3 | Привязка, токены, SQLite, лимиты, фразы ошибок | можно выставлять на VPS |
| M4 | Пуши и `ReminderAgent` с `device_id` и восстановлением таймеров | напоминание звучит на своей колонке после рестарта |
| M5 | Музыка через ffmpeg → Opus, пауза по wake word | «Димаш ойна» играет на колонке |
| M6 | Конфиг прошивки BOX-3, деплой (Caddy, systemd), демо-видео, README | видео в README |

## 10. Открытые вопросы (закрываются в ходе реализации)

1. Точный формат ответа `/ota` и поля `activation` в текущей версии xiaozhi-esp32.
2. Как задать адрес сервера в py-xiaozhi (конфиг или OTA-URL).
3. Работает ли MultiNet-фраза «ai duo si» как wake word для «Айдос» на BOX-3 или нужен другой вариант написания.
4. Версия `ort` и способ поставки `silero_vad.onnx` (в репозитории или скачивание при сборке).
