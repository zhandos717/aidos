from aidos.core.tts import find_piper_model


def test_flat_layout(tmp_path):
    model = tmp_path / "kk_KZ-raya-x_low.onnx"
    model.touch()
    assert find_piper_model(tmp_path, "kk_KZ-raya-x_low") == model


def test_nested_huggingface_layout(tmp_path):
    model = tmp_path / "kk" / "kk_KZ" / "issai" / "high" / "kk_KZ-issai-high.onnx"
    model.parent.mkdir(parents=True)
    model.touch()
    assert find_piper_model(tmp_path, "kk_KZ-issai-high") == model


def test_flat_wins_over_nested(tmp_path):
    flat = tmp_path / "kk_KZ-issai-high.onnx"
    nested = tmp_path / "kk" / "kk_KZ" / "issai" / "high" / "kk_KZ-issai-high.onnx"
    nested.parent.mkdir(parents=True)
    flat.touch()
    nested.touch()
    assert find_piper_model(tmp_path, "kk_KZ-issai-high") == flat


def test_missing_model(tmp_path):
    assert find_piper_model(tmp_path, "kk_KZ-issai-high") is None
