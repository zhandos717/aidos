"""Aidos UI пакеті."""

from aidos.ui.app import AidosUI


def run_ui(router, tts=None, ai_client=None) -> None:
    app = AidosUI(router=router, tts=tts, ai_client=ai_client)
    app.mainloop()


__all__ = ["AidosUI", "run_ui"]
