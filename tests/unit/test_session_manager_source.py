from pathlib import Path


def test_session_manager_no_longer_uses_brittle_input_indexes() -> None:
    source = Path("src/session_manager.py").read_text(encoding="utf-8")

    forbidden = [
        "inputs[0]",
        "inputs[1]",
        "inputs[4]",
        "inputs[5]",
        ".css-1czfed0",
    ]

    for token in forbidden:
        assert token not in source
