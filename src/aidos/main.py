"""Aidos — қазақ тілді AI көмекші, негізгі цикл."""

import argparse
import logging
import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from aidos.core.config import OLLAMA_MODEL, logger, setup_logging
from aidos.core.ollama_client import OllamaClient
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


def _build_router(ollama: OllamaClient, tts_callback) -> IntentRouter:
    router = IntentRouter()
    router.register(Intent.TIME, TimeAgent())
    router.register(Intent.WEATHER, WeatherAgent())
    router.register(Intent.MUSIC, MusicAgent())
    router.register(Intent.REMINDER, ReminderAgent(tts_callback=tts_callback))
    router.register(Intent.AI, AIAgent(client=ollama))
    _log.info("Барлық агенттер тіркелді")
    return router


def _normalize_query(text: str) -> str:
    """'Aidos,' префиксін алып тастау."""
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Aidos — қазақ AI көмекші")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--voice", action="store_true", help="Дауыс режимі (микрофон + TTS)")
    group.add_argument("--both", action="store_true", help="Аралас режим (мәтін кірісі + TTS)")
    args = parser.parse_args()

    _print_banner()

    # TTS жүктеу
    from aidos.core.tts import TTSEngine
    tts = TTSEngine()

    def tts_callback(text: str) -> None:
        console.print(f"[bold cyan]Aidos:[/bold cyan] {text}")
        tts.speak(text)

    # Ollama тексеру
    ollama = OllamaClient()
    if not ollama.is_available():
        console.print(
            "[yellow]⚠ Ollama қосылмаған. AI жауаптары жұмыс істемейді.\n"
            "  Ollama орнату: https://ollama.com[/yellow]"
        )
    else:
        console.print(f"[green]✓ Ollama қосылды, модель: {OLLAMA_MODEL}[/green]")

    router = _build_router(ollama, tts_callback)
    _log.info("Aidos іске қосылды, режим=%s, модель=%s",
               "voice" if args.voice else ("both" if args.both else "text"),
               OLLAMA_MODEL)

    try:
        if args.voice:
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
