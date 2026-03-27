"""ToolRegistry — AI агентіне инструменттерді тіркеу және шақыру.

AI инструментті шақыру үшін осы JSON форматын пайдаланады:
  {"tool": "tool_name", "args": {"param": "value"}}
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

_log = logging.getLogger("aidos.tools")

# Жауаптан tool call JSON-ын іздеу үшін regex (кірістірілген {} қолдауы)
_TOOL_RE = re.compile(r'"tool"\s*:', re.DOTALL)


@dataclass
class Tool:
    name: str
    description: str
    params: dict[str, str]  # param_name → description
    handler: Callable[..., str]

    def to_prompt_line(self) -> str:
        params_str = ", ".join(f"{k}: {v}" for k, v in self.params.items())
        return f"  - {self.name}({params_str}): {self.description}"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        params: dict[str, str],
        handler: Callable[..., str],
    ) -> None:
        self._tools[name] = Tool(name, description, params, handler)
        _log.debug("Инструмент тіркелді: %s", name)

    def get_system_block(self) -> str:
        """System prompt-қа қосылатын инструменттер сипаттамасы."""
        if not self._tools:
            return ""
        lines = [
            "Сенде мына инструменттер бар, оларды қажет болса пайдалан:",
        ]
        for tool in self._tools.values():
            lines.append(tool.to_prompt_line())
        lines += [
            "",
            "Инструментті шақыру үшін жауапта тек осы JSON жолын жаз:",
            '{"tool": "атауы", "args": {"параметр": "мән"}}',
            "Нәтижені алғаннан кейін қазақша жауап бер.",
            "Егер инструмент керек болмаса — тікелей жауап бер.",
        ]
        return "\n".join(lines)

    def parse_tool_call(self, text: str) -> tuple[str, dict[str, Any]] | None:
        """Мәтіннен tool call JSON-ын табу (кірістірілген {} қолдауы)."""
        if not _TOOL_RE.search(text):
            return None
        # Барлық { позицияларын тауып, тепе-тең } табу
        for i, ch in enumerate(text):
            if ch != "{":
                continue
            depth, j = 0, i
            while j < len(text):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                if depth == 0:
                    candidate = text[i : j + 1]
                    try:
                        data = json.loads(candidate)
                        if isinstance(data, dict) and "tool" in data:
                            return data["tool"], data.get("args", {})
                    except (json.JSONDecodeError, ValueError):
                        pass
                    break
                j += 1
        return None

    def execute(self, name: str, args: dict[str, Any]) -> str:
        """Инструментті іске қосу және нәтижені қайтару."""
        tool = self._tools.get(name)
        if not tool:
            _log.warning("Белгісіз инструмент: %s", name)
            return f"Қате: '{name}' инструменті табылмады"
        _log.info("Инструмент шақырылды: %s(%s)", name, args)
        try:
            result = tool.handler(**args)
            _log.info("Инструмент нәтижесі: %s → %s", name, str(result)[:120])
            return str(result)
        except TypeError as exc:
            return f"Қате: параметр сәйкессіздігі — {exc}"
        except Exception as exc:
            _log.error("Инструмент қатесі (%s): %s", name, exc)
            return f"Қате: {exc}"

    @property
    def names(self) -> list[str]:
        return list(self._tools.keys())
