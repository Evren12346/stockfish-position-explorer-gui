# Stockfish Position Explorer GUI

A clean desktop GUI for building chess positions and asking Stockfish for move suggestions.

## Features

- Clickable chessboard for move play
- Position editing mode (place/remove pieces directly)
- FEN load/copy support
- Play suggested moves with one click
- On-board arrows for suggested best/practical moves
- Evaluation bar for current engine score (white vs black edge)
- Top engine-line panel (MultiPV preview)
- Best-move analysis from Stockfish
- Confidence labels for recommendations (`Very High`, `High`, `Medium`, `Low`, `Critical`)
- Human-readable move explanation text for suggested moves
- Trap/blunder scan showing risky alternatives to avoid
- Practical winning move mode:
  - Suggests a move that is a little inconsistent
  - Still aims to keep winning chances high
- Asynchronous analysis (UI stays responsive while thinking)
- Hard cancel for active searches (terminates current engine session immediately)
- Practical style presets: Safe, Balanced, Tricky, Chaotic
- Opponent profile presets: Beginner, Club, Advanced, Engine-like
- Opening-book fallback before engine search in familiar opening positions
- Analysis cache by position/depth/line count for faster repeated lookups
- Position Analyze Mode:
  - Choose White or Black
  - Choose threshold mode: `strict` or `practical`
  - Checks whether that color has winning moves in the current position
  - Recommends which winning move to play when available
- Batch FEN analysis:
  - Load many positions from `.txt`, `.fen`, or `.csv`
  - Analyze all with the current color/threshold settings
  - Export results to `.csv` or `.json`
- PGN import/export
- Multi-game PGN browser (choose which game to load)
- PGN browser search filter for large files
- PGN headers panel (Event, Players, Result, etc.)
- Replay navigation:
  - Jump to start/previous/next/live
  - Click move list entries to inspect earlier positions
- Jump-to-ply control for direct navigation
- Board flip toggle
- Legal target hints (green markers after selecting a piece)
- Analysis history log
- Eval graph over move history
- Persistent settings (`settings.json`) for engine path, depth, profile, thresholds, and UI preferences

## Requirements

- Python 3.10+
- Stockfish binary installed on your system
- Python package:
  - `python-chess`

## Install From GitHub

```bash
git clone https://github.com/<your-username>/stockfish-position-explorer-gui.git
cd stockfish-position-explorer-gui
```

## Linux Install (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install -y python3 python3-venv stockfish

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional dev tools (tests + packaging)
pip install -r requirements-dev.txt

python app.py
```

## macOS Install (Homebrew)

```bash
brew install python stockfish

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional dev tools (tests + packaging)
pip install -r requirements-dev.txt

python app.py
```

## Windows Install (PowerShell)

```powershell
winget install Python.Python.3
winget install official-stockfish.Stockfish

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Optional dev tools (tests + packaging)
pip install -r requirements-dev.txt

py app.py
```

If Stockfish is not auto-detected, click Browse in the app and select the Stockfish executable manually.

## Generic Install

```bash
pip install -r requirements.txt

# Optional dev tools (tests + packaging)
pip install -r requirements-dev.txt
```

## Run

```bash
python app.py
```

## Test

```bash
pytest -q
```

## Build Desktop Binary

```bash
./build_desktop.sh
```

Output binary is generated at `dist/StockfishPositionExplorer`.

## How To Use

1. Set the Stockfish path (or use auto-detected path if available).
2. Build a position:
   - Normal play mode: click piece, then destination square.
   - Edit mode: choose a piece in the dropdown, then click squares to place it.
3. Set side to move and analysis depth.
4. Optional: choose practical style + opponent profile.
4. Click one of:
   - `Analyze Best Move`
   - `Suggest Practical Winning Move`
  - `Position Analyze Mode` (with `strict` or `practical` threshold)
  - `Batch Analyze FENs` for many positions at once
5. Use `Cancel Analysis` if a deep search is taking too long (hard cancel).
6. Optional helpers:
  - `Play Best Move`
  - `Play Practical Move`
  - `Import PGN` / `Export PGN`
  - Search imported PGN game list before loading
  - Jump directly to a chosen ply number
  - Replay controls: `Start`, `Prev`, `Next`, `Live`
  - `Flip Board` for opposite orientation

## Practical Winning Move Mode

This mode checks top engine lines and tries to pick a move that:

- Is not always the #1 line
- Is slightly lower quality by a configurable centipawn gap
- Still evaluates as winning when possible
- Uses human-like preferences (development, king safety, sensible simplification)
- Falls back to best winning move if no safe human-like alternative exists

If no safe offbeat winning line exists, it tells you to play the best move.

Style presets:

- Safe: small deviation from top engine line
- Balanced: moderate deviation while keeping strong eval
- Tricky: allows sharper practical alternatives
- Chaotic: favors more offbeat winning options when available

## Notes

- Position analysis requires both kings to be present.
- Promotions default to queen in board-click move play.
- Exported PGN preserves custom starting positions via `SetUp` + `FEN` headers.
- Eval values are displayed from White's perspective.
- Opening-book fallback is intentionally lightweight and only used in early standard openings.
- Canceling analysis closes the active engine process and starts a fresh one on next analysis.
- Position Analyze Mode evaluates from the selected color as side to move.
- `strict` requires a stronger winning edge; `practical` allows near-winning practical chances.
- Analysis cache is in-memory and resets when the app is closed.
- Settings auto-save on close and can be saved immediately with `Save Settings`.
