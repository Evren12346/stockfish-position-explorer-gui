import random
import shutil
import json
import csv
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
import math
import tkinter as tk
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import chess
import chess.engine
import chess.pgn

from analysis_helpers import confidence_label, move_explanation, profile_params, trap_scan


PIECE_CHOICES = [
    "Empty",
    "White King",
    "White Queen",
    "White Rook",
    "White Bishop",
    "White Knight",
    "White Pawn",
    "Black King",
    "Black Queen",
    "Black Rook",
    "Black Bishop",
    "Black Knight",
    "Black Pawn",
]

PIECE_MAP = {
    "Empty": None,
    "White King": chess.Piece(chess.KING, chess.WHITE),
    "White Queen": chess.Piece(chess.QUEEN, chess.WHITE),
    "White Rook": chess.Piece(chess.ROOK, chess.WHITE),
    "White Bishop": chess.Piece(chess.BISHOP, chess.WHITE),
    "White Knight": chess.Piece(chess.KNIGHT, chess.WHITE),
    "White Pawn": chess.Piece(chess.PAWN, chess.WHITE),
    "Black King": chess.Piece(chess.KING, chess.BLACK),
    "Black Queen": chess.Piece(chess.QUEEN, chess.BLACK),
    "Black Rook": chess.Piece(chess.ROOK, chess.BLACK),
    "Black Bishop": chess.Piece(chess.BISHOP, chess.BLACK),
    "Black Knight": chess.Piece(chess.KNIGHT, chess.BLACK),
    "Black Pawn": chess.Piece(chess.PAWN, chess.BLACK),
}

PIECE_ICON_MAP = {
    "K": "♔",
    "Q": "♕",
    "R": "♖",
    "B": "♗",
    "N": "♘",
    "P": "♙",
    "k": "♚",
    "q": "♛",
    "r": "♜",
    "b": "♝",
    "n": "♞",
    "p": "♟",
}

# Simple built-in opening fallback used before engine search.
# Keys are tuples of UCI moves from the starting position.
OPENING_BOOK = {
    (): ["e2e4", "d2d4", "c2c4", "g1f3"],
    ("e2e4",): ["e7e5", "c7c5", "e7e6", "c7c6"],
    ("d2d4",): ["d7d5", "g8f6", "e7e6"],
    ("c2c4",): ["e7e5", "g8f6", "c7c5"],
    ("g1f3",): ["d7d5", "g8f6", "c7c5"],
    ("e2e4", "e7e5"): ["g1f3", "f1c4", "b1c3"],
    ("e2e4", "c7c5"): ["g1f3", "b1c3", "c2c3"],
    ("d2d4", "d7d5"): ["c2c4", "g1f3", "e2e3"],
    ("d2d4", "g8f6"): ["c2c4", "g1f3", "c1f4"],
}

SETTINGS_FILE = "settings.json"
SETTINGS_DIR = "settings_profiles"


class ToolTip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip_window: tk.Toplevel | None = None
        self.widget.bind("<Enter>", self._show)
        self.widget.bind("<Leave>", self._hide)

    def _show(self, _event: tk.Event | None = None) -> None:
        if self.tip_window is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=self.text,
            justify=tk.LEFT,
            background="#1e2933",
            foreground="#ecf4ff",
            relief=tk.SOLID,
            borderwidth=1,
            padx=6,
            pady=4,
            font=("Segoe UI", 9),
        )
        label.pack()

    def _hide(self, _event: tk.Event | None = None) -> None:
        if self.tip_window is not None:
            self.tip_window.destroy()
            self.tip_window = None


class StockfishGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Stockfish Position Explorer")
        self.root.geometry("1180x760")
        self.root.minsize(1050, 680)

        self.board = chess.Board()
        self.game_start_fen = self.board.fen()
        self.selected_square = None
        self.legal_target_squares = set()
        self.best_move = None
        self.practical_move = None
        self.analysis_log = []
        self.replay_positions = [self.board.copy(stack=False)]
        self.replay_index = 0
        self.latest_lines = []
        self.current_eval_cp = 0
        self.eval_points = {0: 0}
        self.analysis_executor = ThreadPoolExecutor(max_workers=1)
        self.active_analysis_future: Future | None = None
        self.active_batch_future: Future | None = None
        self.analysis_job_id = 0
        self.analysis_running = False
        self.current_engine: chess.engine.SimpleEngine | None = None
        self.current_engine_path = ""
        self.engine_lock = threading.Lock()
        self.cache_lock = threading.Lock()
        self.analysis_cache: dict[tuple[str, int, int], dict] = {}
        self.last_imported_games: list[chess.pgn.Game] = []
        self.current_game_headers: dict[str, str] = {}

        default_engine = shutil.which("stockfish") or ""
        self.engine_path_var = tk.StringVar(value=default_engine)
        self.depth_var = tk.IntVar(value=16)
        self.lines_var = tk.IntVar(value=6)
        self.edit_mode_var = tk.BooleanVar(value=False)
        self.selected_piece_var = tk.StringVar(value="White Pawn")
        self.turn_var = tk.StringVar(value="white")
        self.position_analyze_color_var = tk.StringVar(value="white")
        self.position_analyze_mode_var = tk.StringVar(value="strict")
        self.inconsistency_cp_var = tk.IntVar(value=120)
        self.practical_style_var = tk.StringVar(value="Balanced")
        self.opponent_profile_var = tk.StringVar(value="Club")
        self.style_floor_var = tk.IntVar(value=180)
        self.style_bonus_gap_var = tk.IntVar(value=20)
        self.style_random_top_var = tk.IntVar(value=2)
        self.style_noise_var = tk.DoubleVar(value=0.12)
        self.dev_weight_var = tk.DoubleVar(value=0.35)
        self.castle_weight_var = tk.DoubleVar(value=0.55)
        self.center_pawn_weight_var = tk.DoubleVar(value=0.25)
        self.capture_weight_var = tk.DoubleVar(value=0.22)
        self.check_weight_var = tk.DoubleVar(value=0.18)
        self.retreat_penalty_var = tk.DoubleVar(value=0.30)
        self.conversion_weight_var = tk.DoubleVar(value=0.45)
        self.flip_board_var = tk.BooleanVar(value=False)
        self.jump_ply_var = tk.IntVar(value=0)
        self.current_settings_file = self._settings_path()
        self.settings_file_var = tk.StringVar(value=str(self.current_settings_file))

        self.best_move_var = tk.StringVar(value="Best move: -")
        self.best_score_var = tk.StringVar(value="Eval: -")
        self.confidence_var = tk.StringVar(value="Confidence: -")
        self.explanation_var = tk.StringVar(value="Why this move: -")
        self.trap_var = tk.StringVar(value="Trap scan: -")
        self.practical_move_var = tk.StringVar(value="Practical winning move: -")
        self.position_analyze_result_var = tk.StringVar(value="Position Analyze: -")
        self.info_var = tk.StringVar(value="Ready.")

        self.square_size = 74
        self.board_size = self.square_size * 8

        self._load_settings()

        self._build_ui()
        self._update_move_list()
        self._draw_board()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _add_tooltip(self, widget: tk.Widget, text: str) -> None:
        ToolTip(widget, text)

    def _on_close(self) -> None:
        self._save_settings(silent=True)
        self.cancel_analysis(silent=True)
        self._close_engine()
        self.analysis_executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def _settings_path(self) -> Path:
        return Path(__file__).resolve().parent / SETTINGS_FILE

    def _settings_profiles_dir(self) -> Path:
        path = Path(__file__).resolve().parent / SETTINGS_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _collect_settings_data(self) -> dict:
        return {
            "engine_path": self.engine_path_var.get().strip(),
            "depth": int(self.depth_var.get()),
            "top_lines": int(self.lines_var.get()),
            "inconsistency_cp": int(self.inconsistency_cp_var.get()),
            "practical_style": self.practical_style_var.get(),
            "opponent_profile": self.opponent_profile_var.get(),
            "flip_board": bool(self.flip_board_var.get()),
            "position_threshold": self.position_analyze_mode_var.get(),
            "position_color": self.position_analyze_color_var.get(),
            "style_floor": int(self.style_floor_var.get()),
            "style_bonus_gap": int(self.style_bonus_gap_var.get()),
            "style_random_top": int(self.style_random_top_var.get()),
            "style_noise": float(self.style_noise_var.get()),
            "dev_weight": float(self.dev_weight_var.get()),
            "castle_weight": float(self.castle_weight_var.get()),
            "center_pawn_weight": float(self.center_pawn_weight_var.get()),
            "capture_weight": float(self.capture_weight_var.get()),
            "check_weight": float(self.check_weight_var.get()),
            "retreat_penalty": float(self.retreat_penalty_var.get()),
            "conversion_weight": float(self.conversion_weight_var.get()),
        }

    def _apply_settings_data(self, data: dict) -> None:
        self.engine_path_var.set(data.get("engine_path", self.engine_path_var.get()))
        self.depth_var.set(int(data.get("depth", self.depth_var.get())))
        self.lines_var.set(int(data.get("top_lines", self.lines_var.get())))
        self.inconsistency_cp_var.set(int(data.get("inconsistency_cp", self.inconsistency_cp_var.get())))
        self.practical_style_var.set(data.get("practical_style", self.practical_style_var.get()))
        self.opponent_profile_var.set(data.get("opponent_profile", self.opponent_profile_var.get()))
        self.flip_board_var.set(bool(data.get("flip_board", self.flip_board_var.get())))
        self.position_analyze_mode_var.set(data.get("position_threshold", self.position_analyze_mode_var.get()))
        self.position_analyze_color_var.set(data.get("position_color", self.position_analyze_color_var.get()))
        self.style_floor_var.set(int(data.get("style_floor", self.style_floor_var.get())))
        self.style_bonus_gap_var.set(int(data.get("style_bonus_gap", self.style_bonus_gap_var.get())))
        self.style_random_top_var.set(int(data.get("style_random_top", self.style_random_top_var.get())))
        self.style_noise_var.set(float(data.get("style_noise", self.style_noise_var.get())))
        self.dev_weight_var.set(float(data.get("dev_weight", self.dev_weight_var.get())))
        self.castle_weight_var.set(float(data.get("castle_weight", self.castle_weight_var.get())))
        self.center_pawn_weight_var.set(float(data.get("center_pawn_weight", self.center_pawn_weight_var.get())))
        self.capture_weight_var.set(float(data.get("capture_weight", self.capture_weight_var.get())))
        self.check_weight_var.set(float(data.get("check_weight", self.check_weight_var.get())))
        self.retreat_penalty_var.set(float(data.get("retreat_penalty", self.retreat_penalty_var.get())))
        self.conversion_weight_var.set(float(data.get("conversion_weight", self.conversion_weight_var.get())))

    def _load_settings_from_path(self, path: Path, silent: bool = False) -> bool:
        if not path.exists():
            return False
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            if not silent:
                messagebox.showerror("Settings Error", f"Could not load settings file: {path}")
            return False
        self._apply_settings_data(data)
        self.current_settings_file = path
        self.settings_file_var.set(str(path))
        if not silent:
            self.info_var.set(f"Loaded settings: {path.name}")
        return True

    def _save_settings_to_path(self, path: Path, silent: bool = False) -> bool:
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self._collect_settings_data(), handle, indent=2)
        except OSError:
            if not silent:
                messagebox.showerror("Settings Error", f"Could not save settings file: {path}")
            return False
        self.current_settings_file = path
        self.settings_file_var.set(str(path))
        if not silent:
            self.info_var.set(f"Saved settings: {path.name}")
        return True

    def _load_settings(self) -> None:
        default_path = self._settings_path()
        if self._load_settings_from_path(default_path, silent=True):
            return
        self._sync_playstyle_from_preset()

    def _save_settings(self, silent: bool = False) -> None:
        self._save_settings_to_path(self.current_settings_file, silent=silent)

    def _save_settings_as(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save Settings As",
            defaultextension=".json",
            initialdir=str(self._settings_profiles_dir()),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        self._save_settings_to_path(Path(path), silent=False)

    def _load_settings_dialog(self) -> None:
        path = filedialog.askopenfilename(
            title="Load Settings",
            initialdir=str(self._settings_profiles_dir()),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        self._load_settings_from_path(Path(path), silent=False)
        self._refresh_board_state()

    def _new_settings_file(self) -> None:
        self._sync_playstyle_from_preset()
        target = filedialog.asksaveasfilename(
            title="Create New Settings File",
            defaultextension=".json",
            initialdir=str(self._settings_profiles_dir()),
            initialfile="new_profile.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not target:
            return
        self._save_settings_to_path(Path(target), silent=False)

    def _close_engine(self) -> None:
        with self.engine_lock:
            if self.current_engine is not None:
                try:
                    self.current_engine.quit()
                except Exception:
                    pass
            self.current_engine = None
            self.current_engine_path = ""

    def _ensure_engine(self, engine_path: str) -> chess.engine.SimpleEngine:
        with self.engine_lock:
            if self.current_engine is not None and self.current_engine_path == engine_path:
                return self.current_engine

            if self.current_engine is not None:
                try:
                    self.current_engine.quit()
                except Exception:
                    pass
                self.current_engine = None

            self.current_engine = chess.engine.SimpleEngine.popen_uci(engine_path)
            self.current_engine_path = engine_path
            return self.current_engine

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 11, "bold"))

        container = ttk.Frame(self.root, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=0)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(0, weight=1)

        board_frame = ttk.Frame(container)
        board_frame.grid(row=0, column=0, sticky="n")

        board_shell = ttk.Frame(board_frame)
        board_shell.pack()

        self.eval_canvas = tk.Canvas(
            board_shell,
            width=26,
            height=self.board_size,
            bg="#101820",
            highlightthickness=0,
        )
        self.eval_canvas.pack(side=tk.LEFT, padx=(0, 6))

        self.canvas = tk.Canvas(
            board_shell,
            width=self.board_size,
            height=self.board_size,
            bg="#0f1720",
            highlightthickness=0,
        )
        self.canvas.pack(side=tk.LEFT)
        self.canvas.bind("<Button-1>", self._on_board_click)

        board_controls = ttk.Frame(board_frame)
        board_controls.pack(fill=tk.X, pady=(8, 0))
        board_controls.columnconfigure((0, 1, 2, 3, 4), weight=1)
        ttk.Button(board_controls, text="Start", command=self._goto_replay_start).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(board_controls, text="Prev", command=self._goto_replay_prev).grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Button(board_controls, text="Next", command=self._goto_replay_next).grid(row=0, column=2, sticky="ew", padx=3)
        ttk.Button(board_controls, text="Live", command=self._goto_replay_live).grid(row=0, column=3, sticky="ew", padx=3)
        ttk.Checkbutton(board_controls, text="Flip Board", variable=self.flip_board_var, command=self._draw_board).grid(
            row=0,
            column=4,
            sticky="e",
            padx=(3, 0),
        )

        right = ttk.Frame(container, padding=(12, 0, 0, 0))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        self._engine_panel(right)
        self._position_panel(right)
        self._analysis_panel(right)

        status = ttk.Label(self.root, textvariable=self.info_var, anchor="w", padding=(10, 6))
        status.pack(fill=tk.X)

    def _engine_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Engine", padding=10)
        panel.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        panel.columnconfigure(1, weight=1)

        ttk.Label(panel, text="Stockfish Path").grid(row=0, column=0, sticky="w")
        ttk.Entry(panel, textvariable=self.engine_path_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(panel, text="Browse", command=self._browse_engine).grid(row=0, column=2, sticky="ew")

        ttk.Label(panel, text="Depth").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(panel, from_=6, to=28, textvariable=self.depth_var, width=8).grid(row=1, column=1, sticky="w", pady=(8, 0))

        ttk.Label(panel, text="Top Lines").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Spinbox(panel, from_=2, to=12, textvariable=self.lines_var, width=8).grid(row=1, column=2, sticky="e", pady=(8, 0))

        ttk.Label(panel, text="Practical Style").grid(row=2, column=0, sticky="w", pady=(8, 0))
        style_box = ttk.Combobox(
            panel,
            values=["Safe", "Balanced", "Tricky", "Chaotic"],
            textvariable=self.practical_style_var,
            state="readonly",
            width=12,
        )
        style_box.grid(row=2, column=1, sticky="w", pady=(8, 0))
        style_box.bind("<<ComboboxSelected>>", lambda _e: self._sync_playstyle_from_preset())
        self._add_tooltip(style_box, "Preset baseline for practical move behavior. You can fine-tune below.")

        ttk.Label(panel, text="Opponent Profile").grid(row=2, column=2, sticky="w", pady=(8, 0))
        profile_box = ttk.Combobox(
            panel,
            values=["Beginner", "Club", "Advanced", "Engine-like"],
            textvariable=self.opponent_profile_var,
            state="readonly",
            width=12,
        )
        profile_box.grid(row=2, column=2, sticky="e", pady=(8, 0))
        self._add_tooltip(profile_box, "Adjusts risk tolerance to match expected opponent strength.")

        btn_row = ttk.Frame(panel)
        btn_row.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        btn_row.columnconfigure((0, 1), weight=1)

        self.analyze_best_btn = ttk.Button(btn_row, text="Analyze Best Move", command=self.analyze_best_move)
        self.analyze_best_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.analyze_practical_btn = ttk.Button(btn_row, text="Suggest Practical Winning Move", command=self.analyze_practical_move)
        self.analyze_practical_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        apply_row = ttk.Frame(panel)
        apply_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        apply_row.columnconfigure((0, 1), weight=1)
        ttk.Button(apply_row, text="Play Best Move", command=self.play_best_move).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(apply_row, text="Play Practical Move", command=self.play_practical_move).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        async_row = ttk.Frame(panel)
        async_row.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        async_row.columnconfigure(0, weight=1)
        self.cancel_analysis_btn = ttk.Button(async_row, text="Cancel Analysis", command=self.cancel_analysis, state=tk.DISABLED)
        self.cancel_analysis_btn.grid(row=0, column=0, sticky="ew")

        tune = ttk.LabelFrame(panel, text="Playstyle Tuning", padding=8)
        tune.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        tune.columnconfigure((1, 3), weight=1)

        ttk.Label(tune, text="Winning Floor").grid(row=0, column=0, sticky="w")
        floor_spin = ttk.Spinbox(tune, from_=50, to=500, textvariable=self.style_floor_var, width=8)
        floor_spin.grid(row=0, column=1, sticky="w")
        self._add_tooltip(floor_spin, "Minimum score target for practical winning candidates. Higher is safer.")
        ttk.Label(tune, text="Gap Bonus").grid(row=0, column=2, sticky="w", padx=(12, 0))
        gap_spin = ttk.Spinbox(tune, from_=0, to=300, textvariable=self.style_bonus_gap_var, width=8)
        gap_spin.grid(row=0, column=3, sticky="w")
        self._add_tooltip(gap_spin, "Extra centipawn slack allowed from best move for practical picks.")

        ttk.Label(tune, text="Random Top N").grid(row=1, column=0, sticky="w", pady=(6, 0))
        random_spin = ttk.Spinbox(tune, from_=1, to=8, textvariable=self.style_random_top_var, width=8)
        random_spin.grid(row=1, column=1, sticky="w", pady=(6, 0))
        self._add_tooltip(random_spin, "Choose randomly from the best N human-scored alternatives.")
        ttk.Label(tune, text="Human Noise").grid(row=1, column=2, sticky="w", padx=(12, 0), pady=(6, 0))
        noise_scale = ttk.Scale(tune, from_=0.0, to=0.5, variable=self.style_noise_var, orient=tk.HORIZONTAL)
        noise_scale.grid(row=1, column=3, sticky="ew", pady=(6, 0))
        self._add_tooltip(noise_scale, "Adds randomness to move ranking for less predictable suggestions.")

        ttk.Label(tune, text="Dev Bonus").grid(row=2, column=0, sticky="w", pady=(6, 0))
        dev_scale = ttk.Scale(tune, from_=0.0, to=1.0, variable=self.dev_weight_var, orient=tk.HORIZONTAL)
        dev_scale.grid(row=2, column=1, sticky="ew", pady=(6, 0))
        self._add_tooltip(dev_scale, "Reward early development (knights/bishops).")
        ttk.Label(tune, text="Castle Bonus").grid(row=2, column=2, sticky="w", padx=(12, 0), pady=(6, 0))
        castle_scale = ttk.Scale(tune, from_=0.0, to=1.0, variable=self.castle_weight_var, orient=tk.HORIZONTAL)
        castle_scale.grid(row=2, column=3, sticky="ew", pady=(6, 0))
        self._add_tooltip(castle_scale, "Reward castling to improve king safety.")

        ttk.Label(tune, text="Center Pawn").grid(row=3, column=0, sticky="w", pady=(6, 0))
        center_scale = ttk.Scale(tune, from_=0.0, to=1.0, variable=self.center_pawn_weight_var, orient=tk.HORIZONTAL)
        center_scale.grid(row=3, column=1, sticky="ew", pady=(6, 0))
        self._add_tooltip(center_scale, "Reward central pawn advances (c/d/e/f files).")
        ttk.Label(tune, text="Capture Bonus").grid(row=3, column=2, sticky="w", padx=(12, 0), pady=(6, 0))
        capture_scale = ttk.Scale(tune, from_=0.0, to=1.0, variable=self.capture_weight_var, orient=tk.HORIZONTAL)
        capture_scale.grid(row=3, column=3, sticky="ew", pady=(6, 0))
        self._add_tooltip(capture_scale, "Reward capture moves that simplify or win material.")

        ttk.Label(tune, text="Check Bonus").grid(row=4, column=0, sticky="w", pady=(6, 0))
        check_scale = ttk.Scale(tune, from_=0.0, to=1.0, variable=self.check_weight_var, orient=tk.HORIZONTAL)
        check_scale.grid(row=4, column=1, sticky="ew", pady=(6, 0))
        self._add_tooltip(check_scale, "Reward moves that give check and force responses.")
        ttk.Label(tune, text="Retreat Penalty").grid(row=4, column=2, sticky="w", padx=(12, 0), pady=(6, 0))
        retreat_scale = ttk.Scale(tune, from_=0.0, to=1.0, variable=self.retreat_penalty_var, orient=tk.HORIZONTAL)
        retreat_scale.grid(row=4, column=3, sticky="ew", pady=(6, 0))
        self._add_tooltip(retreat_scale, "Penalty for passive retreat moves that are not tactical.")

        ttk.Label(tune, text="Conversion Bonus").grid(row=5, column=0, sticky="w", pady=(6, 0))
        conversion_scale = ttk.Scale(tune, from_=0.0, to=1.0, variable=self.conversion_weight_var, orient=tk.HORIZONTAL)
        conversion_scale.grid(row=5, column=1, sticky="ew", pady=(6, 0))
        self._add_tooltip(conversion_scale, "Preference for cleanly converting a winning advantage.")

        file_row = ttk.Frame(panel)
        file_row.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        file_row.columnconfigure(1, weight=1)
        ttk.Label(file_row, text="Settings File").grid(row=0, column=0, sticky="w")
        settings_entry = ttk.Entry(file_row, textvariable=self.settings_file_var)
        settings_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self._add_tooltip(settings_entry, "Currently active settings profile path.")

        action_row = ttk.Frame(panel)
        action_row.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        action_row.columnconfigure((0, 1, 2, 3), weight=1)
        new_btn = ttk.Button(action_row, text="New Settings", command=self._new_settings_file)
        new_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._add_tooltip(new_btn, "Start a new settings profile and save it as a new file.")
        load_btn = ttk.Button(action_row, text="Load Settings", command=self._load_settings_dialog)
        load_btn.grid(row=0, column=1, sticky="ew", padx=4)
        self._add_tooltip(load_btn, "Load a saved settings profile from disk.")
        save_btn = ttk.Button(action_row, text="Save", command=self._save_settings)
        save_btn.grid(row=0, column=2, sticky="ew", padx=4)
        self._add_tooltip(save_btn, "Save current values to the active settings file.")
        save_as_btn = ttk.Button(action_row, text="Save As", command=self._save_settings_as)
        save_as_btn.grid(row=0, column=3, sticky="ew", padx=(4, 0))
        self._add_tooltip(save_as_btn, "Save current values to a new settings profile file.")

    def _position_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Position Builder", padding=10)
        panel.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        panel.columnconfigure(1, weight=1)

        ttk.Checkbutton(panel, text="Edit Mode", variable=self.edit_mode_var).grid(row=0, column=0, sticky="w")
        ttk.Label(panel, text="Piece").grid(row=0, column=1, sticky="e")
        piece_box = ttk.Combobox(panel, values=PIECE_CHOICES, textvariable=self.selected_piece_var, state="readonly")
        piece_box.grid(row=0, column=2, sticky="ew", padx=(8, 0))

        ttk.Label(panel, text="Side To Move").grid(row=1, column=0, sticky="w", pady=(8, 0))
        side_row = ttk.Frame(panel)
        side_row.grid(row=1, column=1, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Radiobutton(side_row, text="White", value="white", variable=self.turn_var, command=self._sync_turn).pack(side=tk.LEFT)
        ttk.Radiobutton(side_row, text="Black", value="black", variable=self.turn_var, command=self._sync_turn).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(panel, text="Inconsistency (cp)").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=40, to=260, variable=self.inconsistency_cp_var, orient=tk.HORIZONTAL).grid(
            row=2, column=1, columnspan=2, sticky="ew", pady=(8, 0)
        )

        action_row = ttk.Frame(panel)
        action_row.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        action_row.columnconfigure((0, 1, 2, 3), weight=1)

        ttk.Button(action_row, text="Start Position", command=self._reset_board).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(action_row, text="Clear Board", command=self._clear_board).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(action_row, text="Undo", command=self._undo_move).grid(row=0, column=2, sticky="ew", padx=4)
        ttk.Button(action_row, text="Copy FEN", command=self._copy_fen).grid(row=0, column=3, sticky="ew", padx=(4, 0))

        pgn_row = ttk.Frame(panel)
        pgn_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        pgn_row.columnconfigure((0, 1), weight=1)
        ttk.Button(pgn_row, text="Import PGN", command=self._import_pgn).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(pgn_row, text="Export PGN", command=self._export_pgn).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        fen_row = ttk.Frame(panel)
        fen_row.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        fen_row.columnconfigure(0, weight=1)
        self.fen_entry = ttk.Entry(fen_row)
        self.fen_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(fen_row, text="Load FEN", command=self._load_fen).grid(row=0, column=1, padx=(8, 0))

        analyze_row = ttk.Frame(panel)
        analyze_row.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        analyze_row.columnconfigure(4, weight=1)
        ttk.Label(analyze_row, text="Position Analyze Color").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            analyze_row,
            text="White",
            value="white",
            variable=self.position_analyze_color_var,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Radiobutton(
            analyze_row,
            text="Black",
            value="black",
            variable=self.position_analyze_color_var,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Label(analyze_row, text="Threshold").grid(row=0, column=3, sticky="w", padx=(12, 0))
        ttk.Combobox(
            analyze_row,
            values=["strict", "practical"],
            textvariable=self.position_analyze_mode_var,
            state="readonly",
            width=10,
        ).grid(row=0, column=4, sticky="w", padx=(8, 0))
        ttk.Button(
            analyze_row,
            text="Position Analyze Mode",
            command=self.analyze_position_mode,
        ).grid(row=0, column=5, sticky="e", padx=(8, 0))
        self.batch_analyze_btn = ttk.Button(
            analyze_row,
            text="Batch Analyze FENs",
            command=self.batch_analyze_fens,
        )
        self.batch_analyze_btn.grid(row=0, column=6, sticky="e", padx=(8, 0))

        ttk.Label(panel, textvariable=self.position_analyze_result_var, wraplength=640).grid(
            row=7,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(8, 0),
        )

        self.fen_entry.insert(0, self.board.fen())

    def _analysis_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Analysis", padding=10)
        panel.grid(row=2, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(11, weight=2)
        panel.rowconfigure(13, weight=1)

        ttk.Label(panel, textvariable=self.best_move_var, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(panel, textvariable=self.best_score_var).grid(row=1, column=0, sticky="w", pady=(2, 6))
        ttk.Label(panel, textvariable=self.confidence_var).grid(row=2, column=0, sticky="w")
        ttk.Label(panel, textvariable=self.practical_move_var, wraplength=560).grid(row=3, column=0, sticky="w", pady=(0, 2))
        ttk.Label(panel, textvariable=self.explanation_var, wraplength=560).grid(row=4, column=0, sticky="w", pady=(0, 2))
        ttk.Label(panel, textvariable=self.trap_var, wraplength=560).grid(row=5, column=0, sticky="w", pady=(0, 8))

        ttk.Label(panel, text="Eval Graph", style="Title.TLabel").grid(row=6, column=0, sticky="w", pady=(4, 4))
        self.eval_graph_canvas = tk.Canvas(panel, height=80, bg="#0e1520", highlightthickness=0)
        self.eval_graph_canvas.grid(row=7, column=0, sticky="nsew")

        ttk.Label(panel, text="Top Engine Lines", style="Title.TLabel").grid(row=8, column=0, sticky="w", pady=(8, 4))
        self.top_lines_text = tk.Text(panel, height=6, wrap="word", bg="#101a24", fg="#f6dba8", relief=tk.FLAT)
        self.top_lines_text.grid(row=9, column=0, sticky="nsew")

        ttk.Label(panel, text="Moves (click to jump)", style="Title.TLabel").grid(row=10, column=0, sticky="w", pady=(8, 4))
        self.move_listbox = tk.Listbox(panel, height=10, bg="#101a24", fg="#d6e7ff", activestyle="none")
        self.move_listbox.grid(row=11, column=0, sticky="nsew")
        self.move_listbox.bind("<<ListboxSelect>>", self._on_move_list_select)

        jump_row = ttk.Frame(panel)
        jump_row.grid(row=12, column=0, sticky="ew", pady=(6, 2))
        ttk.Label(jump_row, text="Jump to ply").pack(side=tk.LEFT)
        ttk.Spinbox(jump_row, from_=0, to=600, textvariable=self.jump_ply_var, width=8).pack(side=tk.LEFT, padx=(8, 6))
        ttk.Button(jump_row, text="Go", command=self._jump_to_ply).pack(side=tk.LEFT)

        ttk.Label(panel, text="Analysis History", style="Title.TLabel").grid(row=13, column=0, sticky="w", pady=(8, 4))
        self.history_list = tk.Text(panel, height=8, wrap="word", bg="#0f1a21", fg="#bfe8d4", relief=tk.FLAT)
        self.history_list.grid(row=14, column=0, sticky="nsew")

        ttk.Label(panel, text="PGN Headers", style="Title.TLabel").grid(row=15, column=0, sticky="w", pady=(8, 4))
        self.headers_text = tk.Text(panel, height=4, wrap="word", bg="#111922", fg="#d7dff3", relief=tk.FLAT)
        self.headers_text.grid(row=16, column=0, sticky="nsew")

    def _browse_engine(self) -> None:
        path = filedialog.askopenfilename(title="Select Stockfish Binary")
        if path:
            self.engine_path_var.set(path)

    def _reset_board(self) -> None:
        self.board.reset()
        self.game_start_fen = self.board.fen()
        self.current_game_headers = {}
        self.eval_points = {0: 0}
        self.selected_square = None
        self.legal_target_squares.clear()
        self._clear_suggestions()
        self.turn_var.set("white")
        self.info_var.set("Position reset to start.")
        self._refresh_board_state()

    def _clear_board(self) -> None:
        self.board.clear()
        self.board.turn = chess.WHITE
        self.game_start_fen = self.board.fen()
        self.current_game_headers = {}
        self.eval_points = {0: 0}
        self.selected_square = None
        self.legal_target_squares.clear()
        self._clear_suggestions()
        self.turn_var.set("white")
        self.info_var.set("Board cleared. Use Edit Mode to place pieces.")
        self._refresh_board_state()

    def _undo_move(self) -> None:
        self._goto_replay_live()
        if not self.board.move_stack:
            self.info_var.set("No move to undo.")
            return
        self.board.pop()
        self.selected_square = None
        self.legal_target_squares.clear()
        self._clear_suggestions()
        self.info_var.set("Last move undone.")
        self._refresh_board_state()

    def _copy_fen(self) -> None:
        fen = self.board.fen()
        self.root.clipboard_clear()
        self.root.clipboard_append(fen)
        self.info_var.set("FEN copied to clipboard.")

    def _load_fen(self) -> None:
        fen = self.fen_entry.get().strip()
        try:
            self.board = chess.Board(fen)
        except ValueError:
            messagebox.showerror("Invalid FEN", "Could not parse FEN string.")
            return
        self.game_start_fen = self.board.fen()
        self.current_game_headers = {}
        self.eval_points = {0: 0}
        self.selected_square = None
        self.legal_target_squares.clear()
        self._clear_suggestions()
        self.turn_var.set("white" if self.board.turn == chess.WHITE else "black")
        self.info_var.set("FEN loaded.")
        self._refresh_board_state()

    def _sync_turn(self) -> None:
        self.board.turn = self.turn_var.get() == "white"
        self._refresh_board_state()

    def _on_board_click(self, event: tk.Event) -> None:
        if self.replay_index != len(self.replay_positions) - 1:
            self._goto_replay_live()

        col = event.x // self.square_size
        row = event.y // self.square_size
        if not (0 <= col <= 7 and 0 <= row <= 7):
            return

        square = self._coords_to_square(col, row)
        if self.edit_mode_var.get():
            self._place_piece(square)
        else:
            self._play_move_click(square)

        self._refresh_board_state()

    def _place_piece(self, square: chess.Square) -> None:
        piece = PIECE_MAP[self.selected_piece_var.get()]
        self.board.remove_piece_at(square)
        if piece is not None:
            self.board.set_piece_at(square, piece)
        self.board.clear_stack()
        self.game_start_fen = self.board.fen()
        self.selected_square = None
        self.legal_target_squares.clear()
        self._clear_suggestions()

    def _play_move_click(self, square: chess.Square) -> None:
        if self.selected_square is None:
            piece = self.board.piece_at(square)
            if piece is None or piece.color != self.board.turn:
                self.info_var.set("Select one of your pieces first.")
                return
            self.selected_square = square
            self.legal_target_squares = {
                move.to_square
                for move in self.board.legal_moves
                if move.from_square == self.selected_square
            }
            return

        move = chess.Move(self.selected_square, square)
        piece = self.board.piece_at(self.selected_square)
        if piece and piece.piece_type == chess.PAWN and chess.square_rank(square) in (0, 7):
            move = chess.Move(self.selected_square, square, promotion=chess.QUEEN)

        if move in self.board.legal_moves:
            self.board.push(move)
            self.legal_target_squares.clear()
            self._clear_suggestions()
            self.info_var.set(f"Played move: {move.uci()}")
        else:
            self.info_var.set("Illegal move.")
        self.selected_square = None
        self.legal_target_squares.clear()

    def _clear_suggestions(self) -> None:
        self.best_move = None
        self.practical_move = None

    def _coords_to_square(self, col: int, row: int) -> chess.Square:
        if self.flip_board_var.get():
            return chess.square(7 - col, row)
        return chess.square(col, 7 - row)

    def _square_to_canvas(self, square: chess.Square) -> tuple[float, float]:
        file = chess.square_file(square)
        rank = chess.square_rank(square)
        if self.flip_board_var.get():
            col = 7 - file
            row = rank
        else:
            col = file
            row = 7 - rank
        x = col * self.square_size + self.square_size / 2
        y = row * self.square_size + self.square_size / 2
        return x, y

    def _rebuild_replay_positions(self) -> None:
        temp = chess.Board(self.game_start_fen)
        self.replay_positions = [temp.copy(stack=False)]
        for move in self.board.move_stack:
            temp.push(move)
            self.replay_positions.append(temp.copy(stack=False))
        self.replay_index = len(self.replay_positions) - 1

    def _goto_replay_start(self) -> None:
        self.replay_index = 0
        self.selected_square = None
        self.legal_target_squares.clear()
        self._update_move_list()
        self._draw_board()

    def _goto_replay_prev(self) -> None:
        if self.replay_index > 0:
            self.replay_index -= 1
            self.selected_square = None
            self.legal_target_squares.clear()
            self._update_move_list()
            self._draw_board()

    def _goto_replay_next(self) -> None:
        if self.replay_index < len(self.replay_positions) - 1:
            self.replay_index += 1
            self.selected_square = None
            self.legal_target_squares.clear()
            self._update_move_list()
            self._draw_board()

    def _goto_replay_live(self) -> None:
        self.replay_index = len(self.replay_positions) - 1
        self._update_move_list()
        self._draw_board()

    def _on_move_list_select(self, _event: tk.Event) -> None:
        selection = self.move_listbox.curselection()
        if not selection:
            return
        # List index 0 is the start position entry.
        target = min(selection[0], len(self.replay_positions) - 1)
        self.replay_index = target
        self.selected_square = None
        self.legal_target_squares.clear()
        self._draw_board()

    def _jump_to_ply(self) -> None:
        target = max(0, min(int(self.jump_ply_var.get()), len(self.replay_positions) - 1))
        self.replay_index = target
        self.move_listbox.selection_clear(0, tk.END)
        self.move_listbox.selection_set(target)
        self.move_listbox.see(target)
        self.selected_square = None
        self.legal_target_squares.clear()
        self._draw_board()

    def _update_headers_view(self) -> None:
        self.headers_text.delete("1.0", tk.END)
        if not self.current_game_headers:
            self.headers_text.insert(tk.END, "No PGN headers loaded.\n")
            return
        lines = []
        for key in ("Event", "Site", "Date", "Round", "White", "Black", "Result"):
            value = self.current_game_headers.get(key)
            if value:
                lines.append(f"{key}: {value}")
        if not lines:
            lines.append("Headers present, but no standard fields found.")
        self.headers_text.insert(tk.END, "\n".join(lines) + "\n")

    def _update_top_lines(self) -> None:
        self.top_lines_text.delete("1.0", tk.END)
        if not self.latest_lines:
            self.top_lines_text.insert(tk.END, "No engine lines yet. Analyze a position.\n")
            return
        for idx, line in enumerate(self.latest_lines[:6], start=1):
            self.top_lines_text.insert(
                tk.END,
                f"{idx}. {line['move'].uci()}  eval {line['score_text']}  pv {line['pv']}\n",
            )

    def _update_eval_bar(self) -> None:
        self.eval_canvas.delete("all")
        cp = max(-1500, min(1500, self.current_eval_cp))
        white_ratio = 1.0 / (1.0 + math.exp(-cp / 280))
        white_h = int(self.board_size * white_ratio)
        black_h = self.board_size - white_h
        self.eval_canvas.create_rectangle(0, 0, 26, black_h, fill="#161a22", outline="")
        self.eval_canvas.create_rectangle(0, black_h, 26, self.board_size, fill="#f4f7ff", outline="")
        self.eval_canvas.create_text(13, 10, text="B", fill="#f4f7ff", font=("Segoe UI", 8, "bold"))
        self.eval_canvas.create_text(13, self.board_size - 10, text="W", fill="#101725", font=("Segoe UI", 8, "bold"))

    def _draw_eval_graph(self) -> None:
        self.eval_graph_canvas.delete("all")
        w = max(100, int(self.eval_graph_canvas.winfo_width() or 560))
        h = max(60, int(self.eval_graph_canvas.winfo_height() or 80))

        self.eval_graph_canvas.create_rectangle(0, 0, w, h, fill="#0e1520", outline="")
        mid_y = h / 2
        self.eval_graph_canvas.create_line(0, mid_y, w, mid_y, fill="#33475e", dash=(4, 3))

        total_plies = max(1, len(self.board.move_stack))
        known = sorted((ply, cp) for ply, cp in self.eval_points.items() if 0 <= ply <= len(self.board.move_stack))
        if len(known) < 2:
            cp = self.eval_points.get(len(self.board.move_stack), 0)
            y = mid_y - (max(-1200, min(1200, cp)) / 1200) * (h * 0.45)
            self.eval_graph_canvas.create_line(0, y, w, y, fill="#68d8ff", width=2)
        else:
            points = []
            for ply, cp in known:
                x = (ply / total_plies) * (w - 1)
                y = mid_y - (max(-1200, min(1200, cp)) / 1200) * (h * 0.45)
                points.extend((x, y))
            self.eval_graph_canvas.create_line(*points, fill="#68d8ff", width=2, smooth=True)

        marker_x = (self.replay_index / max(1, len(self.replay_positions) - 1)) * (w - 1)
        self.eval_graph_canvas.create_line(marker_x, 0, marker_x, h, fill="#f7d26a")
        self.eval_graph_canvas.create_text(8, 10, text="+", fill="#f0f7ff", anchor="w", font=("Segoe UI", 8, "bold"))
        self.eval_graph_canvas.create_text(8, h - 10, text="-", fill="#f0f7ff", anchor="w", font=("Segoe UI", 8, "bold"))

    def _record_analysis(self, label: str, move: chess.Move | None, score_text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        move_text = move.uci() if move else "-"
        line = f"[{ts}] {label}: {move_text} ({score_text})"
        self.analysis_log.insert(0, line)
        self.analysis_log = self.analysis_log[:20]

    def _update_history_view(self) -> None:
        self.history_list.delete("1.0", tk.END)
        if not self.analysis_log:
            self.history_list.insert(tk.END, "No analysis yet.\n")
            return
        self.history_list.insert(tk.END, "\n".join(self.analysis_log) + "\n")

    def _score_to_cp(self, score: chess.engine.PovScore) -> int:
        white_view = score.white()
        if white_view.is_mate():
            mate = white_view.mate()
            if mate is None:
                return 0
            return 100000 - abs(mate) if mate > 0 else -100000 + abs(mate)
        cp = white_view.score()
        return 0 if cp is None else cp

    def _format_score(self, score: chess.engine.PovScore) -> str:
        white_view = score.white()
        if white_view.is_mate():
            mate = white_view.mate()
            if mate is None:
                return "Mate unknown"
            return f"Mate in {mate}" if mate > 0 else f"Mated in {abs(mate)}"
        cp = white_view.score()
        if cp is None:
            return "0.00"
        return f"{cp / 100:.2f}"

    def _book_candidates(self, board: chess.Board) -> list[chess.Move]:
        if self.game_start_fen != chess.STARTING_FEN:
            return []

        key = tuple(move.uci() for move in board.move_stack)
        uci_list = OPENING_BOOK.get(key, [])
        candidates = []
        for uci in uci_list:
            move = chess.Move.from_uci(uci)
            if move in board.legal_moves:
                candidates.append(move)
        return candidates

    def _sync_playstyle_from_preset(self) -> None:
        style = self.practical_style_var.get().strip().lower()
        presets = {
            "safe": {
                "style_floor": 260,
                "style_bonus_gap": 0,
                "style_random_top": 1,
                "style_noise": 0.05,
                "dev_weight": 0.30,
                "castle_weight": 0.65,
                "center_pawn_weight": 0.20,
                "capture_weight": 0.18,
                "check_weight": 0.15,
                "retreat_penalty": 0.40,
                "conversion_weight": 0.55,
            },
            "balanced": {
                "style_floor": 180,
                "style_bonus_gap": 20,
                "style_random_top": 2,
                "style_noise": 0.12,
                "dev_weight": 0.35,
                "castle_weight": 0.55,
                "center_pawn_weight": 0.25,
                "capture_weight": 0.22,
                "check_weight": 0.18,
                "retreat_penalty": 0.30,
                "conversion_weight": 0.45,
            },
            "tricky": {
                "style_floor": 120,
                "style_bonus_gap": 40,
                "style_random_top": 3,
                "style_noise": 0.18,
                "dev_weight": 0.40,
                "castle_weight": 0.40,
                "center_pawn_weight": 0.30,
                "capture_weight": 0.28,
                "check_weight": 0.27,
                "retreat_penalty": 0.18,
                "conversion_weight": 0.38,
            },
            "chaotic": {
                "style_floor": 70,
                "style_bonus_gap": 80,
                "style_random_top": 4,
                "style_noise": 0.24,
                "dev_weight": 0.45,
                "castle_weight": 0.30,
                "center_pawn_weight": 0.35,
                "capture_weight": 0.32,
                "check_weight": 0.35,
                "retreat_penalty": 0.10,
                "conversion_weight": 0.30,
            },
        }
        preset = presets.get(style, presets["balanced"])
        self._apply_settings_data(preset)

    def _practical_style_params(self) -> dict:
        base = {
            "floor": int(self.style_floor_var.get()),
            "bonus_gap": int(self.style_bonus_gap_var.get()),
            "random_top": int(self.style_random_top_var.get()),
            "human_noise": float(self.style_noise_var.get()),
            "dev_weight": float(self.dev_weight_var.get()),
            "castle_weight": float(self.castle_weight_var.get()),
            "center_pawn_weight": float(self.center_pawn_weight_var.get()),
            "capture_weight": float(self.capture_weight_var.get()),
            "check_weight": float(self.check_weight_var.get()),
            "retreat_penalty": float(self.retreat_penalty_var.get()),
            "conversion_weight": float(self.conversion_weight_var.get()),
        }
        profile = profile_params(self.opponent_profile_var.get())
        base["floor"] = max(50, base["floor"] - int(profile["risk_bonus"]))
        base["bonus_gap"] = max(0, base["bonus_gap"] + int(profile["risk_bonus"]))
        base["random_top"] = max(1, min(8, base["random_top"]))
        base["human_noise"] = max(0.0, min(0.5, base["human_noise"]))
        return base

    def _side_cp(self, cp_white: int, side_factor: int) -> int:
        return cp_white * side_factor

    def _human_like_move_score(self, board: chess.Board, move: chess.Move, side_cp: int, style: dict) -> float:
        score = 0.0
        piece = board.piece_at(move.from_square)
        if piece is None:
            return -999.0

        phase = len(board.move_stack)
        is_capture = board.is_capture(move)
        gives_check = board.gives_check(move)

        # Human tendencies: development and king safety early, simpler conversion later.
        if phase <= 20:
            if piece.piece_type in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(move.from_square) in (0, 7):
                score += style["dev_weight"]
            if board.is_castling(move):
                score += style["castle_weight"]
            if piece.piece_type == chess.PAWN and chess.square_file(move.to_square) in (2, 3, 4, 5):
                score += style["center_pawn_weight"]

        if is_capture:
            score += style["capture_weight"]
        if gives_check:
            score += style["check_weight"]

        # Avoid very engine-looking backward shuffles unless tactical.
        from_rank = chess.square_rank(move.from_square)
        to_rank = chess.square_rank(move.to_square)
        if piece.color == chess.WHITE:
            retreat = to_rank < from_rank
        else:
            retreat = to_rank > from_rank
        if retreat and not (is_capture or gives_check):
            score -= style["retreat_penalty"]

        # Slight preference for cleaner winning conversion.
        score += min(style["conversion_weight"], max(0.0, (side_cp - style["floor"]) / 900))

        # Human-like imperfections.
        score += random.uniform(-style["human_noise"], style["human_noise"])
        return score

    def _run_analysis_job(self, board_fen: str, engine_path: str, depth: int, multipv: int) -> dict:
        board = chess.Board(board_fen)
        side_factor = 1 if board.turn == chess.WHITE else -1
        cache_key = (board_fen, depth, multipv)

        with self.cache_lock:
            cached = self.analysis_cache.get(cache_key)
        if cached is not None:
            result = dict(cached)
            result["source"] = "cache"
            return result

        book_moves = self._book_candidates(board)
        if book_moves:
            lines = []
            for i, move in enumerate(book_moves[:6]):
                cp = 40 - (i * 8)
                lines.append({
                    "move": move,
                    "score_text": "Book",
                    "cp": cp,
                    "pv": move.uci(),
                })
            lines.sort(key=lambda x: self._side_cp(x["cp"], side_factor), reverse=True)
            result = {"source": "book", "lines": lines, "side_factor": side_factor}
            with self.cache_lock:
                self.analysis_cache[cache_key] = dict(result)
            return result

        try:
            engine = self._ensure_engine(engine_path)
            info = engine.analyse(board, chess.engine.Limit(depth=depth), multipv=multipv)
        except chess.engine.EngineTerminatedError as exc:
            raise RuntimeError("Analysis canceled.") from exc

        if isinstance(info, dict):
            info = [info]

        lines = []
        for item in info:
            pv = item.get("pv") or []
            score = item.get("score")
            if not pv or score is None:
                continue
            line = {
                "move": pv[0],
                "score_text": self._format_score(score),
                "cp": self._score_to_cp(score),
                "pv": " ".join(m.uci() for m in pv[:10]),
            }
            lines.append(line)

        if not lines:
            raise RuntimeError("Engine did not return usable lines for this position.")

        lines.sort(key=lambda x: self._side_cp(x["cp"], side_factor), reverse=True)
        result = {"source": "engine", "lines": lines, "side_factor": side_factor}
        with self.cache_lock:
            self.analysis_cache[cache_key] = dict(result)
        return result

    def _set_analysis_running(self, running: bool) -> None:
        self.analysis_running = running
        if running:
            self.analyze_best_btn.state(["disabled"])
            self.analyze_practical_btn.state(["disabled"])
            self.batch_analyze_btn.state(["disabled"])
            self.cancel_analysis_btn.state(["!disabled"])
        else:
            self.analyze_best_btn.state(["!disabled"])
            self.analyze_practical_btn.state(["!disabled"])
            self.batch_analyze_btn.state(["!disabled"])
            self.cancel_analysis_btn.state(["disabled"])

    def _start_analysis(self, mode: str, board_for_eval: chess.Board | None = None, context: dict | None = None) -> None:
        if self.analysis_running:
            self.info_var.set("Analysis already running. Cancel or wait.")
            return

        engine_path = self.engine_path_var.get().strip()
        if not engine_path:
            messagebox.showerror("Analysis Error", "Please set Stockfish path first.")
            return
        board_obj = board_for_eval.copy(stack=False) if board_for_eval is not None else self.board
        if not board_obj.king(chess.WHITE) or not board_obj.king(chess.BLACK):
            messagebox.showerror("Analysis Error", "Position must contain both kings.")
            return

        self._goto_replay_live()
        self.analysis_job_id += 1
        job_id = self.analysis_job_id
        depth = int(self.depth_var.get())
        multipv = max(2, int(self.lines_var.get()))
        if mode == "position":
            multipv = max(multipv, 8)
        board_fen = board_obj.fen()
        analysis_context = context or {}

        self._set_analysis_running(True)
        self.info_var.set("Analyzing position...")
        self.active_analysis_future = self.analysis_executor.submit(
            self._run_analysis_job,
            board_fen,
            engine_path,
            depth,
            multipv,
        )
        self.root.after(120, lambda: self._poll_analysis(job_id, mode, analysis_context))

    def _poll_analysis(self, job_id: int, mode: str, context: dict) -> None:
        if not self.active_analysis_future:
            self._set_analysis_running(False)
            return
        if job_id != self.analysis_job_id:
            self._set_analysis_running(False)
            return
        if not self.active_analysis_future.done():
            self.root.after(120, lambda: self._poll_analysis(job_id, mode, context))
            return

        future = self.active_analysis_future
        self.active_analysis_future = None
        self._set_analysis_running(False)

        try:
            result = future.result()
        except Exception as exc:
            messagebox.showerror("Analysis Error", str(exc))
            return

        self._apply_analysis_result(mode, result, context)

    def cancel_analysis(self, silent: bool = False) -> None:
        if not self.analysis_running:
            if not silent:
                self.info_var.set("No analysis to cancel.")
            return

        self._close_engine()
        self.analysis_job_id += 1
        self.active_analysis_future = None
        self.active_batch_future = None
        self._set_analysis_running(False)
        if not silent:
            self.info_var.set("Analysis canceled.")

    def _apply_analysis_result(self, mode: str, result: dict, context: dict) -> None:
        lines = result.get("lines", [])
        source = result.get("source", "engine")
        side_factor = int(result.get("side_factor", 1))
        if not lines:
            self.info_var.set("No analysis lines available.")
            return

        best = lines[0]
        self.latest_lines = lines
        self.current_eval_cp = best["cp"]
        self.eval_points[len(self.board.move_stack)] = self.current_eval_cp
        self.best_move = best["move"]
        self.best_move_var.set(f"Best move: {best['move'].uci()}")
        self.best_score_var.set(f"Eval: {best['score_text']}")
        best_side_cp = self._side_cp(best["cp"], side_factor)
        self.confidence_var.set(
            f"Confidence: {confidence_label(best_side_cp, self.opponent_profile_var.get())}"
        )

        if mode == "position":
            color_label = context.get("color_label", "Selected color")
            threshold_label = context.get("threshold_label", "strict")
            winning_floor = int(context.get("winning_floor", 150))
            winning_lines = [
                line for line in lines if self._side_cp(line["cp"], side_factor) >= winning_floor
            ]

            if winning_lines:
                choice = winning_lines[0]
                self.best_move = choice["move"]
                self.practical_move = None
                self.best_move_var.set(f"Best winning move: {choice['move'].uci()}")
                self.best_score_var.set(f"Winning eval: {choice['score_text']}")
                choice_side_cp = self._side_cp(choice["cp"], side_factor)
                self.confidence_var.set(
                    f"Confidence: {confidence_label(choice_side_cp, self.opponent_profile_var.get())}"
                )
                self.practical_move_var.set(f"PV: {choice['pv']}")
                self.explanation_var.set("Why this move: Position mode focuses on direct winning conversion.")
                self.trap_var.set(f"Trap scan: {trap_scan(lines, side_factor)}")
                count = len(winning_lines)
                self.position_analyze_result_var.set(
                    f"{color_label} has winning moves ({count} found, {threshold_label} mode). Play {choice['move'].uci()}."
                )
                self._record_analysis("Position", choice["move"], choice["score_text"])
                self.info_var.set(f"Position Analyze complete: {color_label} can force a winning path.")
            else:
                self.practical_move = None
                self.position_analyze_result_var.set(
                    f"{color_label} has no clear winning move in this position (at current depth, {threshold_label} mode)."
                )
                self.explanation_var.set("Why this move: No line crossed the selected winning threshold.")
                self.trap_var.set("Trap scan: N/A")
                self._record_analysis("Position", None, "No winning move found")
                self.info_var.set(f"Position Analyze complete: no winning move found for {color_label}.")

            self._refresh_board_state()
            return

        if mode == "best":
            self.practical_move = None
            self.practical_move_var.set(f"PV: {best['pv']}")
            self.explanation_var.set(
                f"Why this move: {move_explanation(self.board, best['move'], best_side_cp)}"
            )
            self.trap_var.set(f"Trap scan: {trap_scan(lines, side_factor)}")
            self._record_analysis("Best", best["move"], best["score_text"])
            src = "opening book" if source == "book" else ("cache" if source == "cache" else "engine")
            self.info_var.set(f"Best move analysis complete ({src}).")
            self._refresh_board_state()
            return

        practical = self._choose_practical_winning_move(lines, source, side_factor)
        if practical is None:
            # Always keep a winning plan by falling back to the strongest line.
            practical = best

        self.practical_move = practical["move"]
        practical_side_cp = self._side_cp(practical["cp"], side_factor)
        self.confidence_var.set(
            f"Confidence: {confidence_label(practical_side_cp, self.opponent_profile_var.get())}"
        )
        if practical["move"] == best["move"]:
            self.practical_move_var.set(
                f"Practical winning move: {practical['move'].uci()} | Eval: {practical['score_text']} | PV: {practical['pv']}"
            )
            self.explanation_var.set(
                f"Why this move: {move_explanation(self.board, practical['move'], practical_side_cp)}"
            )
            self.trap_var.set(f"Trap scan: {trap_scan(lines, side_factor)}")
            self._record_analysis("Practical", practical["move"], f"{practical['score_text']} (best fallback)")
            self.info_var.set("Practical mode complete: best move used to preserve winning path.")
            self._refresh_board_state()
            return

        self.practical_move_var.set(
            f"Practical winning move: {practical['move'].uci()} | Eval: {practical['score_text']} | PV: {practical['pv']}"
        )
        self.explanation_var.set(
            f"Why this move: {move_explanation(self.board, practical['move'], practical_side_cp)}"
        )
        self.trap_var.set(f"Trap scan: {trap_scan(lines, side_factor)}")
        self._record_analysis("Practical", practical["move"], practical["score_text"])
        src = "opening book" if source == "book" else ("cache" if source == "cache" else "engine")
        self.info_var.set(f"Practical mode complete ({src}): suggested a less consistent winning move.")
        self._refresh_board_state()

    def analyze_best_move(self) -> None:
        self._start_analysis("best")

    def _choose_practical_winning_move(self, lines: list[dict], source: str, side_factor: int) -> dict | None:
        if source == "book":
            if len(lines) == 1:
                return lines[0]
            return random.choice(lines[1: min(4, len(lines))])

        best_cp_side = self._side_cp(lines[0]["cp"], side_factor)
        inconsistency = int(self.inconsistency_cp_var.get())
        style = self._practical_style_params()

        winning_floor = style["floor"]
        allowed_gap = inconsistency + style["bonus_gap"]
        candidates = [
            line
            for line in lines[1:]
            if self._side_cp(line["cp"], side_factor) >= winning_floor
            and (best_cp_side - self._side_cp(line["cp"], side_factor)) <= allowed_gap
        ]

        if candidates:
            board_now = self.board
            scored = []
            for line in candidates:
                sc = self._human_like_move_score(
                    board_now,
                    line["move"],
                    self._side_cp(line["cp"], side_factor),
                    style,
                )
                scored.append((sc, line))
            scored.sort(key=lambda x: x[0], reverse=True)
            top_n = max(1, min(style["random_top"], len(scored)))
            return random.choice([line for _, line in scored[:top_n]])

        safe_alternatives = [
            line
            for line in lines[1:]
            if self._side_cp(line["cp"], side_factor) >= max(80, winning_floor - 70)
            and (best_cp_side - self._side_cp(line["cp"], side_factor)) <= max(220, allowed_gap)
        ]
        if safe_alternatives:
            board_now = self.board
            scored = []
            for line in safe_alternatives:
                sc = self._human_like_move_score(
                    board_now,
                    line["move"],
                    self._side_cp(line["cp"], side_factor),
                    style,
                )
                scored.append((sc, line))
            scored.sort(key=lambda x: x[0], reverse=True)
            top_n = max(1, min(style["random_top"] + 1, len(scored)))
            return random.choice([line for _, line in scored[:top_n]])

        return None

    def analyze_practical_move(self) -> None:
        self._start_analysis("practical")

    def analyze_position_mode(self) -> None:
        color = self.position_analyze_color_var.get().strip().lower()
        if color not in ("white", "black"):
            self.position_analyze_result_var.set("Position Analyze: choose White or Black.")
            return

        threshold_mode = self.position_analyze_mode_var.get().strip().lower()
        if threshold_mode not in ("strict", "practical"):
            threshold_mode = "strict"
        winning_floor = 220 if threshold_mode == "strict" else 90

        board_eval = self.board.copy(stack=False)
        board_eval.turn = chess.WHITE if color == "white" else chess.BLACK
        color_label = "White" if color == "white" else "Black"

        self.position_analyze_result_var.set(
            f"Position Analyze: checking winning moves for {color_label} ({threshold_mode} mode)..."
        )
        self._start_analysis(
            "position",
            board_for_eval=board_eval,
            context={
                "color_label": color_label,
                "threshold_label": threshold_mode,
                "winning_floor": winning_floor,
            },
        )

    def _load_fens_from_file(self, path: str) -> list[str]:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = handle.read()
        except OSError as exc:
            raise RuntimeError(f"Could not read file: {exc}") from exc

        if path.lower().endswith(".csv"):
            fens = []
            with open(path, "r", encoding="utf-8") as csv_file:
                reader = csv.reader(csv_file)
                for row in reader:
                    if not row:
                        continue
                    fens.append(row[0].strip())
            return [fen for fen in fens if fen]

        return [line.strip() for line in raw.splitlines() if line.strip()]

    def _run_batch_analysis_job(
        self,
        fens: list[str],
        engine_path: str,
        depth: int,
        multipv: int,
        color: str,
        winning_floor: int,
    ) -> list[dict]:
        rows = []
        side = chess.WHITE if color == "white" else chess.BLACK
        side_factor = 1 if side == chess.WHITE else -1
        for fen in fens:
            try:
                board = chess.Board(fen)
                if not board.king(chess.WHITE) or not board.king(chess.BLACK):
                    rows.append({"fen": fen, "status": "invalid (missing king)"})
                    continue
                board.turn = side
                result = self._run_analysis_job(board.fen(), engine_path, depth, multipv)
                lines = result.get("lines", [])
                winning = [line for line in lines if self._side_cp(line["cp"], side_factor) >= winning_floor]
                best = winning[0] if winning else lines[0]
                side_cp = self._side_cp(best["cp"], side_factor)
                rows.append(
                    {
                        "fen": fen,
                        "status": "winning" if winning else "not-winning",
                        "recommended_move": best["move"].uci(),
                        "eval": best["score_text"],
                        "confidence": confidence_label(side_cp, self.opponent_profile_var.get()),
                    }
                )
            except Exception as exc:
                rows.append({"fen": fen, "status": f"error: {exc}"})
        return rows

    def _poll_batch_analysis(self, job_id: int) -> None:
        if not self.active_batch_future:
            self._set_analysis_running(False)
            return
        if job_id != self.analysis_job_id:
            self._set_analysis_running(False)
            return
        if not self.active_batch_future.done():
            self.root.after(120, lambda: self._poll_batch_analysis(job_id))
            return

        future = self.active_batch_future
        self.active_batch_future = None
        self._set_analysis_running(False)

        try:
            rows = future.result()
        except Exception as exc:
            messagebox.showerror("Batch Analyze Error", str(exc))
            return

        if not rows:
            self.info_var.set("Batch analysis finished with no rows.")
            return

        path = filedialog.asksaveasfilename(
            title="Save Batch Analysis",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            self.info_var.set("Batch analysis completed, but export was canceled.")
            return

        try:
            if path.lower().endswith(".json"):
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(rows, handle, indent=2)
            else:
                keys = sorted({k for row in rows for k in row.keys()})
                with open(path, "w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=keys)
                    writer.writeheader()
                    writer.writerows(rows)
        except OSError as exc:
            messagebox.showerror("Batch Analyze Error", f"Could not save results: {exc}")
            return

        self.info_var.set(f"Batch analysis completed and exported: {path}")

    def batch_analyze_fens(self) -> None:
        if self.analysis_running:
            self.info_var.set("Analysis already running. Cancel or wait.")
            return
        engine_path = self.engine_path_var.get().strip()
        if not engine_path:
            messagebox.showerror("Batch Analyze Error", "Please set Stockfish path first.")
            return

        source_path = filedialog.askopenfilename(
            title="Select FEN List",
            filetypes=[("Text/CSV", "*.txt *.fen *.csv"), ("All files", "*.*")],
        )
        if not source_path:
            return

        try:
            fens = self._load_fens_from_file(source_path)
        except RuntimeError as exc:
            messagebox.showerror("Batch Analyze Error", str(exc))
            return

        if not fens:
            messagebox.showerror("Batch Analyze Error", "No FEN entries found in file.")
            return

        color = self.position_analyze_color_var.get().strip().lower()
        if color not in ("white", "black"):
            color = "white"
        threshold_mode = self.position_analyze_mode_var.get().strip().lower()
        if threshold_mode not in ("strict", "practical"):
            threshold_mode = "strict"
        winning_floor = 220 if threshold_mode == "strict" else 90

        self.analysis_job_id += 1
        job_id = self.analysis_job_id
        self._set_analysis_running(True)
        self.info_var.set(f"Batch analyzing {len(fens)} FEN positions...")
        self.active_batch_future = self.analysis_executor.submit(
            self._run_batch_analysis_job,
            fens,
            engine_path,
            int(self.depth_var.get()),
            max(4, int(self.lines_var.get())),
            color,
            winning_floor,
        )
        self.root.after(120, lambda: self._poll_batch_analysis(job_id))

    def _play_suggested_move(self, move: chess.Move | None, label: str) -> None:
        self._goto_replay_live()
        if move is None:
            self.info_var.set(f"No {label.lower()} move available yet. Analyze first.")
            return
        if move not in self.board.legal_moves:
            self.info_var.set(f"{label} move is no longer legal in this position.")
            return
        self.board.push(move)
        self.selected_square = None
        self._clear_suggestions()
        self.info_var.set(f"Played {label.lower()} move: {move.uci()}")
        self._refresh_board_state()

    def play_best_move(self) -> None:
        self._play_suggested_move(self.best_move, "Best")

    def play_practical_move(self) -> None:
        self._play_suggested_move(self.practical_move, "Practical")

    def _import_pgn(self) -> None:
        path = filedialog.askopenfilename(
            title="Import PGN",
            filetypes=[("PGN files", "*.pgn"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                games = []
                while True:
                    game = chess.pgn.read_game(handle)
                    if game is None:
                        break
                    games.append(game)
        except OSError as exc:
            messagebox.showerror("Import Error", f"Could not read file: {exc}")
            return

        if not games:
            messagebox.showerror("Import Error", "No PGN game found in file.")
            return

        self.last_imported_games = games

        if len(games) == 1:
            self._load_game_from_pgn(games[0])
            self.info_var.set("PGN imported.")
            return

        index = self._choose_pgn_game_index(games)
        if index is None:
            self.info_var.set("PGN import canceled.")
            return

        self._load_game_from_pgn(games[index])
        self.info_var.set(f"PGN imported (game {index + 1}/{len(games)}).")

    def _choose_pgn_game_index(self, games: list[chess.pgn.Game]) -> int | None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Choose PGN Game")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("720x360")

        frame = ttk.Frame(dialog, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Select a game to load", style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        search_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=search_var).pack(fill=tk.X, pady=(0, 6))
        listbox = tk.Listbox(frame, bg="#101a24", fg="#d6e7ff", activestyle="none")
        listbox.pack(fill=tk.BOTH, expand=True)

        visible_indices: list[int] = []

        def fill_list() -> None:
            listbox.delete(0, tk.END)
            visible_indices.clear()
            needle = search_var.get().strip().lower()
            for i, game in enumerate(games, start=1):
                white = game.headers.get("White", "?")
                black = game.headers.get("Black", "?")
                event = game.headers.get("Event", "?")
                result = game.headers.get("Result", "*")
                text = f"{i}. {white} vs {black} | {event} | {result}"
                if needle and needle not in text.lower():
                    continue
                visible_indices.append(i - 1)
                listbox.insert(tk.END, text)
            if listbox.size() > 0:
                listbox.selection_set(0)

        fill_list()
        search_var.trace_add("write", lambda *_: fill_list())

        selected = {"index": None}

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X, pady=(8, 0))

        def choose() -> None:
            sel = listbox.curselection()
            if not sel:
                return
            if sel[0] >= len(visible_indices):
                return
            selected["index"] = int(visible_indices[sel[0]])
            dialog.destroy()

        def cancel() -> None:
            dialog.destroy()

        ttk.Button(btn_row, text="Load Selected", command=choose).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Cancel", command=cancel).pack(side=tk.LEFT, padx=(8, 0))
        dialog.bind("<Double-Button-1>", lambda _e: choose())
        dialog.wait_window()
        return selected["index"]

    def _load_game_from_pgn(self, game: chess.pgn.Game) -> None:
        root_board = game.board()
        self.board = root_board.copy()
        for move in game.mainline_moves():
            self.board.push(move)

        self.current_game_headers = dict(game.headers)
        self.game_start_fen = root_board.fen()
        self.eval_points = {0: 0}
        self.selected_square = None
        self.legal_target_squares.clear()
        self._clear_suggestions()
        self.turn_var.set("white" if self.board.turn == chess.WHITE else "black")
        self._refresh_board_state()

    def _export_pgn(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Export PGN",
            defaultextension=".pgn",
            filetypes=[("PGN files", "*.pgn"), ("All files", "*.*")],
        )
        if not path:
            return

        game = chess.pgn.Game()
        headers = dict(self.current_game_headers)
        headers.setdefault("Event", "Stockfish Position Explorer")
        headers.setdefault("Date", datetime.now().strftime("%Y.%m.%d"))
        for key, value in headers.items():
            game.headers[key] = value

        start_board = chess.Board(self.game_start_fen)
        if self.game_start_fen != chess.STARTING_FEN:
            game.headers["SetUp"] = "1"
            game.headers["FEN"] = self.game_start_fen
        game.setup(start_board)

        node = game
        for move in self.board.move_stack:
            node = node.add_variation(move)

        with open(path, "w", encoding="utf-8") as handle:
            exporter = chess.pgn.FileExporter(handle)
            game.accept(exporter)

        self.info_var.set("PGN exported.")

    def _update_move_list(self) -> None:
        self.move_listbox.delete(0, tk.END)
        self.move_listbox.insert(tk.END, "0. [start position]")
        temp = chess.Board(self.game_start_fen)
        for i, move in enumerate(self.board.move_stack, start=1):
            san = temp.san(move)
            temp.push(move)
            turn = "W" if i % 2 == 1 else "B"
            self.move_listbox.insert(tk.END, f"{i}. {turn}: {san}")

        if self.replay_index < self.move_listbox.size():
            self.move_listbox.selection_clear(0, tk.END)
            self.move_listbox.selection_set(self.replay_index)
            self.move_listbox.see(self.replay_index)
            self.jump_ply_var.set(self.replay_index)

        self._update_history_view()

    def _draw_suggestion_arrow(self, move: chess.Move, color: str) -> None:
        sx, sy = self._square_to_canvas(move.from_square)
        ex, ey = self._square_to_canvas(move.to_square)
        self.canvas.create_line(
            sx,
            sy,
            ex,
            ey,
            fill=color,
            width=4,
            arrow=tk.LAST,
            arrowshape=(12, 14, 5),
            smooth=True,
        )

    def _draw_board(self) -> None:
        self.canvas.delete("all")

        light = "#d7edf8"
        dark = "#5d90a6"
        selected = "#f6d66e"
        replay_tint = "#90d5ff"

        view_board = self.replay_positions[self.replay_index] if self.replay_positions else self.board

        for rank in range(8):
            for file in range(8):
                x1 = file * self.square_size
                y1 = rank * self.square_size
                x2 = x1 + self.square_size
                y2 = y1 + self.square_size
                square = self._coords_to_square(file, rank)

                color = light if (rank + file) % 2 == 0 else dark
                if self.replay_index != len(self.replay_positions) - 1:
                    color = replay_tint if (rank + file) % 2 == 0 else "#6eaecb"
                if self.selected_square == square:
                    color = selected

                self.canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline="#223746")

                if square in self.legal_target_squares:
                    cx = x1 + self.square_size / 2
                    cy = y1 + self.square_size / 2
                    self.canvas.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, fill="#2f9b55", outline="")

                piece = view_board.piece_at(square)
                if piece:
                    icon = PIECE_ICON_MAP.get(piece.symbol(), piece.symbol())
                    if piece.color == chess.WHITE:
                        badge_fill = "#f6fbff"
                        badge_outline = "#9cb9cc"
                        text_color = "#1a2c3d"
                    else:
                        badge_fill = "#0f1d2a"
                        badge_outline = "#88a3bb"
                        text_color = "#f5f9ff"

                    cx = x1 + self.square_size / 2
                    cy = y1 + self.square_size / 2
                    r = self.square_size * 0.33
                    self.canvas.create_oval(
                        cx - r,
                        cy - r,
                        cx + r,
                        cy + r,
                        fill=badge_fill,
                        outline=badge_outline,
                        width=2,
                    )
                    self.canvas.create_text(
                        cx + 1,
                        cy + 1,
                        text=icon,
                        fill="#000000",
                        font=("DejaVu Sans", 32, "bold"),
                    )
                    self.canvas.create_text(
                        cx,
                        cy,
                        text=icon,
                        fill=text_color,
                        font=("DejaVu Sans", 32, "bold"),
                    )

        files = "abcdefgh"
        ranks = "87654321"
        if self.flip_board_var.get():
            files = files[::-1]
            ranks = ranks[::-1]

        for i, file_char in enumerate(files):
            self.canvas.create_text(
                i * self.square_size + 8,
                self.board_size - 8,
                text=file_char,
                anchor="sw",
                fill="#0c1f2f",
                font=("Segoe UI", 9, "bold"),
            )

        for i, rank_char in enumerate(ranks):
            self.canvas.create_text(
                4,
                i * self.square_size + 10,
                text=rank_char,
                anchor="nw",
                fill="#0c1f2f",
                font=("Segoe UI", 9, "bold"),
            )

        if self.best_move:
            self._draw_suggestion_arrow(self.best_move, "#ff5c5c")
        if self.practical_move:
            self._draw_suggestion_arrow(self.practical_move, "#41e08c")

        self._update_eval_bar()
        self._draw_eval_graph()

    def _refresh_board_state(self) -> None:
        self._rebuild_replay_positions()
        self.fen_entry.delete(0, tk.END)
        self.fen_entry.insert(0, self.board.fen())
        self.turn_var.set("white" if self.board.turn == chess.WHITE else "black")
        self._update_move_list()
        self._update_headers_view()
        self._update_top_lines()
        self._draw_board()


def main() -> None:
    root = tk.Tk()
    app = StockfishGUI(root)
    app.info_var.set("Load or build a position, then run analysis.")
    root.mainloop()


if __name__ == "__main__":
    main()
