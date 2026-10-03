"""TTS-ке дейін мәтінді тазалау — markdown, сілтемелер, эмодзи."""

import re

_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_CODE_RE = re.compile(r"`+([^`]*)`+")
# Жалғыз "_" әдейі қамтылмаған: user_name сияқты сөздерді бүлдірмеу үшін.
_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|~~)(?=\S)(.+?)(?<=\S)\1")
_HEADER_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*•]\s+", re.MULTILINE)
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF️‍]"
)
_SPACES_RE = re.compile(r"[ \t]+")


def clean_for_speech(text: str) -> str:
    text = _LINK_RE.sub(r"\1", text)
    text = _URL_RE.sub("", text)
    text = _CODE_RE.sub(r"\1", text)
    text = _EMPHASIS_RE.sub(r"\2", text)
    text = _HEADER_RE.sub("", text)
    text = _BULLET_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)

    sentences = []
    for line in text.splitlines():
        line = _SPACES_RE.sub(" ", line).strip()
        if not line:
            continue
        # Жол соңында тыныс белгісі болмаса, Piper келесі жолмен үзіліссіз жалғастырады.
        if line[-1] not in ".!?…:;,":
            line += "."
        sentences.append(line)
    return " ".join(sentences)
