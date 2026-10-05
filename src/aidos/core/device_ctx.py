"""Ағымдағы колонка — gRPC ход кезінде агенттер кімге жауап беретінін біледі."""

from contextvars import ContextVar
from dataclasses import dataclass

current_device: ContextVar[str | None] = ContextVar("current_device", default=None)


@dataclass(frozen=True)
class DeviceAction:
    kind: str
    url: str = ""
    title: str = ""


turn_actions: ContextVar[list[DeviceAction] | None] = ContextVar("turn_actions", default=None)


def emit_action(kind: str, url: str = "", title: str = "") -> bool:
    """Ағымдағы ходқа колонка әрекетін қосады; колонка ходы болмаса False."""
    actions = turn_actions.get()
    if actions is None:
        return False
    actions.append(DeviceAction(kind, url, title))
    return True
