"""Aidos UI пакеті."""

from aidos.ui.app import AidosUI


def run_ui(router, tts=None) -> None:
    app = AidosUI(router=router, tts=tts)
    app.mainloop()


__all__ = ["AidosUI", "run_ui"]
