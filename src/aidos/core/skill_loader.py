"""SkillLoader — skills/ қалтасынан .py және .md дағдыларды автоматты жүктейді."""

from __future__ import annotations

import importlib
import logging
import pkgutil
import re
from pathlib import Path

logger = logging.getLogger("aidos.skill_loader")


class Skill:
    def __init__(self, name: str, triggers: list[re.Pattern], handler) -> None:
        self.name = name
        self.triggers = triggers
        self.handler = handler

    def matches(self, text: str) -> bool:
        return any(p.search(text) for p in self.triggers)

    def handle(self, query: str) -> str:
        return self.handler(query)


def _parse_md_frontmatter(text: str) -> tuple[dict, str]:
    """YAML-like frontmatter мен дене бөлігін бөліп алу."""
    meta: dict = {}
    body = text

    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            fm_text = text[3:end].strip()
            body = text[end + 3:].strip()
            current_key = None
            for line in fm_text.splitlines():
                if line.startswith("  - "):          # list item
                    meta.setdefault(current_key, []).append(line[4:].strip())
                elif ":" in line:
                    key, _, val = line.partition(":")
                    current_key = key.strip()
                    val = val.strip()
                    if val:
                        meta[current_key] = val
                    else:
                        meta.setdefault(current_key, [])

    return meta, body


def _make_md_handler(system_prompt: str, ai_client):
    def handler(query: str) -> str:
        try:
            messages = [{"role": "user", "content": query}]
            return ai_client.chat(messages, system=system_prompt)
        except Exception as exc:
            logger.error("MD skill AI қатесі: %s", exc)
            return "Кешіріңіз, жауап беру мүмкін болмады."
    return handler


class SkillLoader:
    def __init__(self) -> None:
        self._skills: list[Skill] = []
        self._ai_client = None

    def set_ai_client(self, client) -> None:
        """MD skills үшін AI клиентін беру."""
        self._ai_client = client

    def load_all(self) -> None:
        """skills/ қалтасындағы барлық .py және .md файлдарды жүктейді."""
        import aidos.skills as skills_pkg
        skills_path = Path(skills_pkg.__path__[0])

        # .py skills
        for _, module_name, _ in pkgutil.iter_modules([str(skills_path)]):
            self._load_py_skill(module_name)

        # .md skills
        for md_file in skills_path.glob("*.md"):
            self._load_md_skill(md_file)

        logger.info("Барлығы %d skill жүктелді", len(self._skills))

    def _load_py_skill(self, module_name: str) -> None:
        full_name = f"aidos.skills.{module_name}"
        try:
            module = importlib.import_module(full_name)
        except Exception as exc:
            logger.error("Skill жүктеу қатесі '%s': %s", module_name, exc)
            return

        triggers_raw = getattr(module, "triggers", [])
        handler = getattr(module, "handle", None)

        if not triggers_raw or handler is None:
            logger.warning("Skill '%s': triggers немесе handle жоқ", module_name)
            return

        if not callable(handler):
            logger.warning("Skill '%s': handle callable емес", module_name)
            return

        compiled = [re.compile(p, re.IGNORECASE) for p in triggers_raw]
        self._skills.append(Skill(name=module_name, triggers=compiled, handler=handler))
        logger.info("Skill (.py) жүктелді: '%s' (%d триггер)", module_name, len(compiled))

    def _load_md_skill(self, md_file: Path) -> None:
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("MD skill оқу қатесі '%s': %s", md_file.name, exc)
            return

        meta, body = _parse_md_frontmatter(text)
        triggers_raw = meta.get("triggers", [])

        if not triggers_raw:
            logger.warning("MD skill '%s': triggers жоқ", md_file.name)
            return

        if self._ai_client is None:
            logger.warning("MD skill '%s': AI клиент берілмеген", md_file.name)
            return

        compiled = [re.compile(p, re.IGNORECASE) for p in triggers_raw]
        handler = _make_md_handler(system_prompt=body, ai_client=self._ai_client)
        name = md_file.stem
        self._skills.append(Skill(name=name, triggers=compiled, handler=handler))
        logger.info("Skill (.md) жүктелді: '%s' (%d триггер)", name, len(compiled))

    def match(self, text: str) -> Skill | None:
        for skill in self._skills:
            if skill.matches(text):
                logger.debug("Skill матч: '%s'", skill.name)
                return skill
        return None

    @property
    def skills(self) -> list[Skill]:
        return list(self._skills)
