import chess

from analysis_helpers import confidence_label, move_explanation, profile_params, trap_scan


def test_profile_params_defaults_to_club() -> None:
    params = profile_params("unknown")
    assert params["confidence_shift"] == 0
    assert params["risk_bonus"] == 20


def test_confidence_label_thresholds() -> None:
    assert confidence_label(600, "club") == "Very High"
    assert confidence_label(280, "club") == "High"
    assert confidence_label(150, "club") == "Medium"
    assert confidence_label(10, "club") == "Low"
    assert confidence_label(-10, "club") == "Critical"


def test_move_explanation_mentions_capture() -> None:
    board = chess.Board("4k3/8/8/4p3/4P3/8/8/4K3 w - - 0 1")
    move = chess.Move.from_uci("e4e5")
    text = move_explanation(board, move, 150)
    assert "stable practical edge" in text.lower()


def test_trap_scan_reports_large_drop() -> None:
    lines = [
        {"move": chess.Move.from_uci("e2e4"), "cp": 260},
        {"move": chess.Move.from_uci("a2a3"), "cp": 20},
    ]
    text = trap_scan(lines, 1)
    assert "avoid a2a3" in text.lower()
