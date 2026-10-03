from aidos.brain.sentences import split_sentences


def test_splits_on_terminal_punctuation():
    text = "Абай — қазақтың ұлы ақыны. Ол ойшыл болған! Сіз білесіз бе?"
    assert split_sentences(text) == ["Абай — қазақтың ұлы ақыны.", "Ол ойшыл болған!", "Сіз білесіз бе?"]


def test_short_piece_is_merged_with_next():
    assert split_sentences("Иә. Қазір сағат он екі.") == ["Иә. Қазір сағат он екі."]


def test_decimal_point_is_not_a_boundary():
    assert split_sentences("Температура 17.5 градус болады.") == ["Температура 17.5 градус болады."]


def test_trailing_short_piece_is_kept():
    assert split_sentences("Бұл ұзын бірінші сөйлем. Иә.") == ["Бұл ұзын бірінші сөйлем.", "Иә."]


def test_empty():
    assert split_sentences("   ") == []
