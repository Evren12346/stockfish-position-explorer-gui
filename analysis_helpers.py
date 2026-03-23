from __future__ import annotations

import chess


def profile_params(profile_name: str) -> dict:
    profile = profile_name.strip().lower()
    mapping = {
        "beginner": {"confidence_shift": -25, "risk_bonus": 45},
        "club": {"confidence_shift": 0, "risk_bonus": 20},
        "advanced": {"confidence_shift": 20, "risk_bonus": 0},
        "engine-like": {"confidence_shift": 40, "risk_bonus": -20},
    }
    return mapping.get(profile, mapping["club"])


def confidence_label(side_cp: int, profile_name: str) -> str:
    shift = profile_params(profile_name)["confidence_shift"]
    cp = side_cp + shift
    if cp >= 500:
        return "Very High"
    if cp >= 260:
        return "High"
    if cp >= 120:
        return "Medium"
    if cp >= 0:
        return "Low"
    return "Critical"


def move_explanation(board: chess.Board, move: chess.Move, side_cp: int) -> str:
    piece = board.piece_at(move.from_square)
    if piece is None:
        return "Move explanation unavailable."

    parts = []
    name = chess.piece_name(piece.piece_type).title()
    if board.is_castling(move):
        parts.append("Improves king safety by castling")
    if board.is_capture(move):
        parts.append("Wins material or simplifies with a capture")
    if board.gives_check(move):
        parts.append("Forces responses by giving check")

    from_rank = chess.square_rank(move.from_square)
    to_rank = chess.square_rank(move.to_square)
    if piece.color == chess.WHITE and to_rank > from_rank:
        parts.append(f"Activates the {name.lower()} forward")
    if piece.color == chess.BLACK and to_rank < from_rank:
        parts.append(f"Activates the {name.lower()} forward")

    if side_cp >= 250:
        parts.append("Keeps a clearly winning advantage")
    elif side_cp >= 120:
        parts.append("Maintains a stable practical edge")
    elif side_cp >= 0:
        parts.append("Playable, but accuracy still matters")
    else:
        parts.append("Position is dangerous; precision required")

    return ". ".join(parts) + "."


def trap_scan(lines: list[dict], side_factor: int, max_items: int = 3) -> str:
    if len(lines) < 2:
        return "No trap scan available (need multiple lines)."

    best_side = lines[0]["cp"] * side_factor
    warnings = []
    for line in lines[1:]:
        line_side = line["cp"] * side_factor
        drop = best_side - line_side
        if drop >= 140:
            warnings.append(f"Avoid {line['move'].uci()} (drops about {drop} cp).")
        if len(warnings) >= max_items:
            break

    if not warnings:
        return "No major immediate blunders among top lines at this depth."
    return " ".join(warnings)
