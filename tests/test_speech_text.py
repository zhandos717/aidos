import pytest

from aidos.core.speech_text import clean_for_speech


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Бағасы **20 400 теңге** болады.", "Бағасы 20 400 теңге болады."),
        ("Бұл *өте* `маңызды` ~~емес~~.", "Бұл өте маңызды емес."),
        ("Толығырақ: [сайт](https://example.kz) қараңыз.", "Толығырақ: сайт қараңыз."),
        ("Сілтеме https://example.kz/path?a=1 мұнда.", "Сілтеме мұнда."),
        ("Сәлем! 👋 Көмек керек пе? 😊", "Сәлем! Көмек керек пе?"),
        ("## Кеңестер\n- Ерте жат\n- Кофе ішпе", "Кеңестер. Ерте жат. Кофе ішпе."),
        ("1. Бірінші қадам\n2. Екінші қадам", "1. Бірінші қадам. 2. Екінші қадам."),
        ("user_name кілті", "user_name кілті."),
    ],
)
def test_clean_for_speech(raw, expected):
    assert clean_for_speech(raw) == expected


def test_only_emoji_becomes_empty():
    assert clean_for_speech("🎉🎬") == ""
