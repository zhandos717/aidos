import pytest

from aidos.core.wake_word import find_wake_word


@pytest.mark.parametrize(
    ("heard", "command"),
    [
        ("айдос", ""),
        ("Айдос, ауа райы қандай?", "ауа райы қандай"),
        ("айдас сағат неше", "сағат неше"),
        ("aidos музыка қос", "музыка қос"),
        ("эй айдос", ""),
        ("айдоос он минуттан кейін еске сал", "он минуттан кейін еске сал"),
    ],
)
def test_wake_word_found(heard, command):
    assert find_wake_word(heard) == command


@pytest.mark.parametrize(
    "heard",
    [
        "бір айда қайтамын",
        "көлікті айдап келдім",
        "айдана қайда",
        "сен білесің бе айдос деген кім",
        "",
    ],
)
def test_wake_word_not_found(heard):
    assert find_wake_word(heard) is None
