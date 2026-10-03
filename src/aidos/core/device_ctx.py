"""Ағымдағы колонка — gRPC ход кезінде агенттер кімге жауап беретінін біледі."""

from contextvars import ContextVar

current_device: ContextVar[str | None] = ContextVar("current_device", default=None)
