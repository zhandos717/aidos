"""AI ядросы — анимацияланған шаңырақ.

Шеңбер — шаңырақ құрсауы, ішіндегі айқас доғалар — күлдіреуіш, сыртқы сәулелер — уықтар.
Күйлер: idle (тыныс алу), listening (толқын), thinking (айналу), speaking (уықтар — эквалайзер).
"""

from __future__ import annotations

import math
import random
import tkinter as tk

from aidos.ui.theme import ACCENT, ACCENT2, BG, mix

IDLE, LISTENING, THINKING, SPEAKING = "idle", "listening", "thinking", "speaking"

_FRAME_MS = 33
_BOOT_FRAMES = 40
_SPOKES = 36
_ROT_SPEED = {IDLE: 0.12, LISTENING: 0.25, THINKING: 1.6, SPEAKING: 0.35}


def _ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


class AICore(tk.Canvas):
    def __init__(self, master, size: int = 220, bg: str = BG, detail: bool = True) -> None:
        super().__init__(master, width=size, height=size, bg=bg, highlightthickness=0)
        self._size = size
        self._bg = bg
        self._detail = detail
        self._state = IDLE
        self._frame = 0
        self._angle = 0.0
        self._rot = _ROT_SPEED[IDLE]
        self._tint = 0.0
        self._levels = [0.0] * _SPOKES
        self._ripples: list[float] = []
        self._tick()

    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        if state == LISTENING and self._state != LISTENING:
            self._ripples = [0.0]
        self._state = state

    # ── Цикл ──────────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if self.winfo_ismapped():
            self._frame += 1
            self._rot += (_ROT_SPEED[self._state] - self._rot) * 0.06
            self._angle = (self._angle + self._rot) % 360
            self._tint += ((1.0 if self._state == LISTENING else 0.0) - self._tint) * 0.12
            self._update_levels()
            self._ripples = [r + 0.018 for r in self._ripples if r < 1.0]
            if self._state == LISTENING and self._frame % 22 == 0:
                self._ripples.append(0.0)
            self._draw()
        self.after(_FRAME_MS, self._tick)

    def _update_levels(self) -> None:
        f = self._frame
        for i in range(_SPOKES):
            if self._state == SPEAKING:
                # Нақты дыбыс деңгейі жоқ — тегістелген кездейсоқтық сөйлеуге ұқсайды
                env = 0.55 + 0.45 * math.sin(f * 0.23 + i * 0.4) * math.sin(f * 0.05)
                target, k = random.uniform(0.2, 1.0) * env, 0.35
            elif self._state == LISTENING:
                target, k = 0.25 + 0.25 * math.sin(f * 0.18 - i * 0.7), 0.25
            elif self._state == THINKING:
                head = (f * 0.6) % _SPOKES
                dist = min(abs(i - head), _SPOKES - abs(i - head))
                target, k = max(0.0, 0.6 - dist * 0.12), 0.3
            else:
                target, k = 0.08 + 0.06 * math.sin(f * 0.05 + i * 0.35), 0.08
            self._levels[i] += (target - self._levels[i]) * k

    # ── Сурет ─────────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        self.delete("all")
        boot = _ease_out(min(1.0, self._frame / _BOOT_FRAMES))
        c = self._size / 2
        R = self._size / 2 - 2
        color = mix(ACCENT, ACCENT2, self._tint)
        breath = (math.sin(self._frame * 0.05) + 1) / 2

        if self._detail:
            self._draw_halo(c, R, color, breath)
            for r in self._ripples:
                rr = R * (0.48 + 0.5 * r)
                self.create_oval(c - rr, c - rr, c + rr, c + rr,
                                 outline=mix(color, self._bg, 0.35 + 0.65 * r), width=1)

        rim = R * 0.44
        self._draw_spokes(c, R, rim, color, boot)

        extent = 359.9 * boot
        self.create_arc(c - rim, c - rim, c + rim, c + rim, start=90, extent=-extent,
                        style="arc", outline=color, width=max(2, self._size // 70))
        inner = rim * 0.86
        if self._detail:
            self.create_oval(c - inner, c - inner, c + inner, c + inner,
                             outline=mix(color, self._bg, 0.6), width=1)
        if boot > 0.5:
            self._draw_lattice(c, inner, color, (boot - 0.5) * 2)

    def _draw_halo(self, c: float, R: float, color: str, breath: float) -> None:
        for k in range(5, 0, -1):
            rr = R * (0.40 + k * 0.07 + breath * 0.02)
            self.create_oval(c - rr, c - rr, c + rr, c + rr,
                             fill=mix(self._bg, color, 0.035 * (6 - k)), outline="")

    def _draw_spokes(self, c: float, R: float, rim: float, color: str, boot: float) -> None:
        dim = mix(color, self._bg, 0.55)
        shown = int(_SPOKES * boot)
        width = max(2, self._size // 90)
        for i in range(shown):
            ang = math.radians(self._angle + i * 360 / _SPOKES)
            lvl = self._levels[i]
            r0 = rim * 1.12
            r1 = r0 + R * (0.06 + 0.40 * lvl)
            cos, sin = math.cos(ang), math.sin(ang)
            self.create_line(c + r0 * cos, c - r0 * sin, c + r1 * cos, c - r1 * sin,
                             fill=mix(dim, color, min(1.0, lvl * 1.6)), width=width, capstyle="round")

    def _draw_lattice(self, c: float, rr: float, color: str, appear: float) -> None:
        """Күлдіреуіш: екі бағытта үш-үштен иілген доға."""
        rot = math.radians(-self._angle * 0.5)
        cos_r, sin_r = math.cos(rot), math.sin(rot)
        width = max(2, self._size // 80)
        line_color = mix(self._bg, color, appear)

        def rotate(x: float, y: float) -> tuple[float, float]:
            return c + x * cos_r - y * sin_r, c + x * sin_r + y * cos_r

        for vertical in (True, False):
            for d in (-0.38, 0.0, 0.38):
                off = d * rr
                h = math.sqrt(max(rr * rr - off * off, 0)) * 0.97
                bow = 0.16 * rr * (1 if d >= 0 else -1) if d else 0.0
                pts = [(off, -h), (off + bow, 0.0), (off, h)]
                if not vertical:
                    pts = [(y, x) for x, y in pts]
                flat = [v for p in pts for v in rotate(*p)]
                self.create_line(*flat, fill=line_color, width=width, smooth=True, capstyle="round")
