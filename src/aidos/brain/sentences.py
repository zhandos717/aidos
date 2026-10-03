"""Жауапты сөйлемдерге бөлу — бірінші сөйлем қалғандары синтезделгенше ойнай береді."""

import re

_BOUNDARY_RE = re.compile(r"(?<=[.!?…])\s+")


def split_sentences(text: str, min_len: int = 12) -> list[str]:
    pieces = [p.strip() for p in _BOUNDARY_RE.split(text) if p.strip()]
    result: list[str] = []
    carry = ""
    for piece in pieces:
        piece = f"{carry} {piece}".strip() if carry else piece
        if len(piece) < min_len:
            carry = piece
            continue
        result.append(piece)
        carry = ""
    if carry:
        result.append(carry)
    return result
