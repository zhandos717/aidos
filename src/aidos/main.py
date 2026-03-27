"""Aidos — қазақ тілді AI көмекші, негізгі цикл."""

import argparse
import logging
import sys
import threading

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from aidos.core.config import AI_PROVIDER, OLLAMA_MODEL, OPENROUTER_MODEL, AGENTROUTER_MODEL
from aidos.core.ai_factory import create_ai_client
from aidos.core.router import Intent, IntentRouter
from aidos.agents.time_agent import TimeAgent
from aidos.agents.weather_agent import WeatherAgent
from aidos.agents.music_agent import MusicAgent
from aidos.agents.reminder_agent import ReminderAgent
from aidos.agents.ai_agent import AIAgent

console = Console()
_log = logging.getLogger("aidos.main")

_EXIT_WORDS = {"шығу", "сау бол", "қош бол", "жарайды сау бол", "bye", "exit", "quit"}


def _print_banner() -> None:
    banner = Text()
    banner.append("  Сәлем! Мен ", style="white")
    banner.append("Aidos", style="bold cyan")
    banner.append(" — сіздің қазақ AI көмекшіңізмін.\n", style="white")
    banner.append("  'шығу' немесе 'сау бол' деп жазу арқылы шығуға болады.", style="dim")
    console.print(Panel(banner, title="[bold cyan]Aidos[/bold cyan]", border_style="cyan"))


def _build_router(ai_client, tts_callback) -> IntentRouter:
    from aidos.core.memory import MemoryStore
    from aidos.core.tool_registry import ToolRegistry

    memory = MemoryStore()
    registry = ToolRegistry()

    # Агенттер
    time_agent    = TimeAgent()
    weather_agent = WeatherAgent()
    music_agent   = MusicAgent()
    reminder_agent = ReminderAgent(tts_callback=tts_callback)

    # Инструменттерді тіркеу (AI ReAct цикл үшін)
    registry.register(
        name="get_time",
        description="Ағымдағы уақыт пен күнді алу",
        params={},
        handler=lambda: time_agent.handle("уақыт"),
    )
    registry.register(
        name="get_weather",
        description="Қаладағы ауа райын алу",
        params={"city": "қала атауы, мысалы: Астана"},
        handler=lambda city="": weather_agent.handle(city or "ауа райы"),
    )
    registry.register(
        name="play_music",
        description="YouTube-тан музыка іздеп ойнату",
        params={"query": "ән немесе орындаушы атауы"},
        handler=lambda query="": music_agent.handle(f"ойна {query}"),
    )
    registry.register(
        name="stop_music",
        description="Музыканы тоқтату",
        params={},
        handler=lambda: music_agent.handle("тоқтат"),
    )
    registry.register(
        name="set_reminder",
        description="Еске салғыш орнату",
        params={"text": "еске салу мәтіні", "minutes": "минут саны (сан)"},
        handler=lambda text="", minutes=5: reminder_agent.handle(
            f"{minutes} минуттан кейін {text} еске сал"
        ),
    )
    registry.register(
        name="remember_fact",
        description="Пайдаланушы туралы маңызды факт есте сақтау",
        params={"key": "факт кілті", "value": "факт мәні"},
        handler=lambda key="", value="": (
            memory.set_fact(key, value) or f"Есте сақталды: {key} = {value}"
        ),
    )
    registry.register(
        name="recall_fact",
        description="Бұрын сақталған фактіні еске алу",
        params={"key": "факт кілті"},
        handler=lambda key="": str(memory.get_fact(key) or "Табылмады"),
    )

    ai_agent = AIAgent(client=ai_client, memory=memory, registry=registry)

    router = IntentRouter(ai_client=ai_client)
    router.register(Intent.TIME, time_agent)
    router.register(Intent.WEATHER, weather_agent)
    router.register(Intent.MUSIC, music_agent)
    router.register(Intent.REMINDER, reminder_agent)
    router.register(Intent.AI, ai_agent)
    _log.info("Барлық агенттер мен инструменттер тіркелді: %s", registry.names)
    return router


def _normalize_query(text: str) -> str:
    """'Aidos,' префиксін алып тастау және жарамсыз таңбаларды тазалау."""
    # Surrogate таңбаларды алып тастау
    text = text.encode("utf-8", errors="ignore").decode("utf-8")
    prefixes = ["aidos,", "aidos"]
    lower = text.lower().strip()
    for prefix in prefixes:
        if lower.startswith(prefix):
            text = text[len(prefix):].strip(" ,")
            break
    return text


def run_text_mode(router: IntentRouter) -> None:
    """Мәтін режимі — терминалдан кіріс."""
    _log.info("Мәтін режимі іске қосылды")
    while True:
        try:
            user_input = Prompt.ask("[bold cyan]Сіз[/bold cyan]")
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input.strip():
            continue

        query = _normalize_query(user_input)

        if query.lower() in _EXIT_WORDS:
            console.print("[dim]Сау болыңыз![/dim]")
            _log.info("Пайдаланушы шықты (text режимі)")
            break

        _log.info("Кіріс: '%s' (text режимі)", query)
        try:
            response = router.route(query)
            console.print(f"[bold cyan]Aidos:[/bold cyan] {response}")
            _log.info("Жауап берілді (text режимі)")
        except Exception as exc:
            _log.error("Жауап беру қатесі: %s", exc)
            console.print("[red]Қате: жауап беру мүмкін болмады.[/red]")


def run_voice_mode(router: IntentRouter, tts) -> None:
    """Дауыс режимі — микрофон + TTS."""
    from aidos.core.voice import VoiceInput
    voice = VoiceInput()
    _log.info("Дауыс режимі іске қосылды")
    console.print("[dim]Тыңдауда... ('Ctrl+C' шығу үшін)[/dim]")

    while True:
        try:
            console.print("[dim]🎙 Сөйлеңіз...[/dim]")
            text = voice.listen()
        except KeyboardInterrupt:
            break

        if text is None:
            continue

        console.print(f"[bold cyan]Сіз:[/bold cyan] {text}")
        query = _normalize_query(text)

        if query.lower() in _EXIT_WORDS:
            tts.speak("Сау болыңыз!")
            _log.info("Пайдаланушы шықты (voice режимі)")
            break

        _log.info("Кіріс: '%s' (voice режимі)", query)
        try:
            response = router.route(query)
            console.print(f"[bold cyan]Aidos:[/bold cyan] {response}")
            tts.speak(response)
            _log.info("Жауап берілді (voice режимі)")
        except Exception as exc:
            _log.error("Дауыс режимі қатесі: %s", exc)


def run_both_mode(router: IntentRouter, tts) -> None:
    """Аралас режим — мәтін кірісі + TTS шығысы."""
    _log.info("Аралас режим іске қосылды")
    while True:
        try:
            user_input = Prompt.ask("[bold cyan]Сіз[/bold cyan]")
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input.strip():
            continue

        query = _normalize_query(user_input)

        if query.lower() in _EXIT_WORDS:
            tts.speak("Сау болыңыз!")
            console.print("[dim]Сау болыңыз![/dim]")
            _log.info("Пайдаланушы шықты (both режимі)")
            break

        _log.info("Кіріс: '%s' (both режимі)", query)
        try:
            response = router.route(query)
            console.print(f"[bold cyan]Aidos:[/bold cyan] {response}")
            tts.speak(response)
        except Exception as exc:
            _log.error("Аралас режим қатесі: %s", exc)


def run_wake_mode(router: IntentRouter, tts) -> None:
    """Колонка режимі — 'Айдос' деген сөзден кейін тыңдайды."""
    from aidos.core.voice import VoiceInput
    from aidos.core.wake_word import WakeWordDetector

    voice = VoiceInput()
    _ready = threading.Event()

    def on_wake() -> None:
        tts.speak("Иә?")
        console.print("[bold cyan]Aidos:[/bold cyan] Иә?")
        _ready.set()

    detector = WakeWordDetector(on_detected=on_wake)
    detector.start()
    console.print("[dim]🎙  'Айдос' деп айтыңыз...[/dim]")
    _log.info("Колонка режимі іске қосылды")

    try:
        while True:
            _ready.wait()
            _ready.clear()

            console.print("[dim]Тыңдауда...[/dim]")
            text = voice.listen()
            if not text:
                continue

            console.print(f"[bold cyan]Сіз:[/bold cyan] {text}")
            query = _normalize_query(text)

            if query.lower() in _EXIT_WORDS:
                tts.speak("Сау болыңыз!")
                break

            try:
                response = router.route(query)
                console.print(f"[bold cyan]Aidos:[/bold cyan] {response}")
                tts.speak(response)
            except Exception as exc:
                _log.error("Колонка режимі қатесі: %s", exc)
    finally:
        detector.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Aidos — қазақ AI көмекші")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--voice", action="store_true", help="Дауыс режимі (микрофон + TTS)")
    group.add_argument("--both", action="store_true", help="Аралас режим (мәтін кірісі + TTS)")
    group.add_argument("--ui", action="store_true", help="Графикалық интерфейс (customtkinter)")
    group.add_argument("--wake", action="store_true", help="Колонка режимі ('Айдос' триггері + TTS)")
    args = parser.parse_args()

    _print_banner()

    # TTS жүктеу
    from aidos.core.tts import TTSEngine
    tts = TTSEngine()

    def tts_callback(text: str) -> None:
        console.print(f"[bold cyan]Aidos:[/bold cyan] {text}")
        tts.speak(text)

    # AI провайдерді таңдау (Strategy паттерн)
    try:
        ai_client = create_ai_client()
    except ValueError as exc:
        console.print(f"[red]✗ AI клиент қатесі: {exc}[/red]")
        sys.exit(1)

    if AI_PROVIDER == "openrouter":
        active_model = OPENROUTER_MODEL
    elif AI_PROVIDER == "agentrouter":
        active_model = AGENTROUTER_MODEL
    else:
        active_model = OLLAMA_MODEL
    if ai_client.is_available():
        console.print(f"[green]✓ {AI_PROVIDER} қосылды, модель: {active_model}[/green]")
    else:
        console.print(f"[yellow]⚠ {AI_PROVIDER} қол жетімсіз. AI жауаптары жұмыс істемейді.[/yellow]")

    router = _build_router(ai_client, tts_callback)
    _log.info("Aidos іске қосылды, режим=%s, провайдер=%s, модель=%s",
               "voice" if args.voice else ("both" if args.both else "text"),
               AI_PROVIDER, active_model)

    try:
        if args.ui:
            from aidos.ui import run_ui
            run_ui(router=router, tts=tts)
        elif args.wake:
            run_wake_mode(router, tts)
        elif args.voice:
            run_voice_mode(router, tts)
        elif args.both:
            run_both_mode(router, tts)
        else:
            run_text_mode(router)
    except KeyboardInterrupt:
        console.print("\n[dim]Сау болыңыз![/dim]")
        _log.info("Aidos Ctrl+C арқылы тоқтатылды")
    except Exception as exc:
        _log.error("Күтпеген қате: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
