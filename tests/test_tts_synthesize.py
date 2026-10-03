from aidos.core.tts import TTSEngine


class FakeVoice:
    def __init__(self):
        self.texts = []

    def synthesize_wav(self, text, wav_file):
        self.texts.append(text)
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x01\x00" * 100)


def _engine(voice):
    engine = TTSEngine.__new__(TTSEngine)
    engine._piper_voice = voice
    return engine


def test_synthesize_returns_pcm_and_rate():
    voice = FakeVoice()
    pcm, rate = _engine(voice).synthesize("**Сәлем!** 👋")
    assert rate == 22050
    assert len(pcm) == 200
    assert voice.texts == ["Сәлем!"]


def test_without_piper_returns_none():
    assert _engine(None).synthesize("Сәлем") is None


def test_empty_after_cleaning_returns_none():
    assert _engine(FakeVoice()).synthesize("🎉") is None
