#!/usr/bin/env python
from __future__ import annotations

import json
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import ctypes
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from install_neural_companion import REPO_ROOT, find_python311_executables, get_python_minor_version


POCKETTTS_LOGIN_MISSING_TEXT = "No Hugging Face login detected"
DISCORD_INVITE_URL = "https://discord.gg/UqnwX46rcK"
HF_POCKETTTS_TERMS_URL = "https://huggingface.co/kyutai/pocket-tts"
HF_TOKEN_SETTINGS_URL = "https://huggingface.co/settings/tokens"
PYTHON_WINDOWS_DOWNLOADS_URL = "https://www.python.org/downloads/windows/"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
TORCH_STACK_LABELS = {
    "Auto-detect GPU": "auto",
    "Force default CUDA stack": "default",
    "Force CUDA 12.8 / RTX 50": "cu128",
}


class InstallerAudioController:
    """Small looping MP3 controller for the installer shell."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.alias = f"nc_installer_music_{id(self):x}"
        self.backend = "windows-mci" if sys.platform.startswith("win") else "subprocess"
        self.process: subprocess.Popen[bytes] | None = None
        self._mci_open = False

    def play(self) -> tuple[bool, str]:
        if not self.path.exists():
            return False, f"Music file not found: {self.path}"
        if self.is_playing():
            return True, "Circuit_Saffron.mp3 is already playing."
        if self.backend == "windows-mci":
            return self._play_windows_mci()
        return self._play_subprocess()

    def stop(self) -> None:
        if self.backend == "windows-mci":
            self._mci("stop " + self.alias)
            self._mci("close " + self.alias)
            self._mci_open = False
            return
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def is_playing(self) -> bool:
        if self.backend == "windows-mci":
            if not self._mci_open:
                return False
            ok, status = self._mci("status " + self.alias + " mode")
            return ok and status.strip().lower() == "playing"
        return self.process is not None and self.process.poll() is None

    def _play_windows_mci(self) -> tuple[bool, str]:
        self.stop()
        ok, message = self._mci(f'open "{self.path}" type mpegvideo alias {self.alias}')
        if not ok:
            return False, message
        self._mci_open = True
        ok, message = self._mci("play " + self.alias + " repeat")
        if not ok:
            self.stop()
            return False, message
        return True, "Playing Circuit_Saffron.mp3."

    def _play_subprocess(self) -> tuple[bool, str]:
        player_command = self._fallback_player_command()
        if not player_command:
            return False, "No MP3 player found. Install ffplay, mpg123, or cvlc for audio on this platform."
        try:
            self.process = subprocess.Popen(
                player_command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            return False, f"Could not start music player: {exc}"
        return True, "Playing Circuit_Saffron.mp3."

    def _fallback_player_command(self) -> list[str] | None:
        path = str(self.path)
        if shutil.which("ffplay"):
            return ["ffplay", "-nodisp", "-loglevel", "quiet", "-loop", "0", path]
        if shutil.which("mpg123"):
            return ["mpg123", "-q", "--loop", "-1", path]
        if shutil.which("cvlc"):
            return ["cvlc", "--intf", "dummy", "--loop", "--play-and-exit", path]
        return None

    def _mci(self, command: str) -> tuple[bool, str]:
        buffer = ctypes.create_unicode_buffer(512)
        result = ctypes.windll.winmm.mciSendStringW(command, buffer, len(buffer), None)
        if result == 0:
            return True, buffer.value

        error_buffer = ctypes.create_unicode_buffer(512)
        ctypes.windll.winmm.mciGetErrorStringW(result, error_buffer, len(error_buffer))
        return False, error_buffer.value or f"MCI error {result}"


class NeuralCompanionInstallerGui(tk.Tk):
    """Neural Companion installer shell with an NC-inspired dark UI.

    The installer behavior is intentionally kept close to the original:
    - same installer command generation
    - same isolated runtime choices
    - same PocketTTS Hugging Face login flow
    - same background-process handling

    The rework focuses on layout, readability, status feedback and a darker
    Neon/Neural Companion style.
    """

    BG = "#070A12"
    SURFACE = "#101622"
    SURFACE_2 = "#151D2B"
    SURFACE_3 = "#0C111B"
    BORDER = "#26334A"
    TEXT = "#EAF2FF"
    MUTED = "#91A0B8"
    ACCENT = "#6E7BFF"
    ACCENT_2 = "#36E6C2"
    WARNING = "#FFD166"
    DANGER = "#FF5F7E"
    SUCCESS = "#3EE28F"
    OUTPUT_BG = "#05070C"
    OUTPUT_FG = "#C9D7EF"

    def __init__(self) -> None:
        super().__init__()
        self.title("Neural Companion Installer")
        self._set_initial_window_size()

        self.output_queue: queue.Queue[str | tuple[str, int] | None] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.current_command: list[str] = []
        self.current_output: list[str] = []
        self.last_exit_code: int | None = None

        self.python_path = tk.StringVar(value="")
        self.install_main = tk.BooleanVar(value=True)
        self.install_musetalk = tk.BooleanVar(value=True)
        self.install_pockettts = tk.BooleanVar(value=True)
        self.install_avatar_echo = tk.BooleanVar(value=True)
        self.install_avatar_eon = tk.BooleanVar(value=True)
        self.skip_main_torch = tk.BooleanVar(value=False)
        self.torch_stack_label = tk.StringVar(value="Auto-detect GPU")

        self.status_text = tk.StringVar(value="Ready")
        self.python_status_text = tk.StringVar(value="Detecting Python 3.11...")
        self.command_preview = tk.StringVar(value="Command preview will appear here.")
        self.music_status_text = tk.StringVar(value="Music idle")
        self.audio_controller = InstallerAudioController(REPO_ROOT / "Installer_Music" / "Circuit_Saffron.mp3")
        self._vibe_tick = 0
        self._installer_running = False
        self._feature_status_after_id: str | None = None
        self._feature_status_index = 0
        self._feature_status_messages = [
            "Local realtime chat keeps the companion experience on your machine.",
            "Speech output supports Chatterbox, Gemini TTS Preview, PocketTTS, and addon TTS backends.",
            "Avatar output can run through MuseTalk, VSeeFace, VaM, or no-avatar mode.",
            "MuseTalk adds local talking-head avatar generation with prepared avatar packs.",
            "Visual replies and story visuals can generate image-based responses when enabled.",
            "Sensory addons can use screen, webcam, clipboard, or other local context sources.",
            "Addon-driven workflows let chat, TTS, avatars, visuals, and tools expand independently.",
            "Isolated runtimes keep MuseTalk and PocketTTS dependencies from colliding with the main app.",
        ]
        self.output_backdrops: dict[str, tk.PhotoImage] = {}
        self._active_output_backdrop_key: str | None = None
        self._output_backdrop_item: int | None = None
        self._output_line_y = 12
        self._output_font = ("Consolas", 9)

        self._configure_window()
        self._configure_styles()
        self._load_output_backdrops()
        self._build_ui()
        self._auto_detect_python()
        self.update_idletasks()
        self.after(90, self._animate_cracktro)
        self.after(100, self._drain_output_queue)

    # ---------------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------------

    def _set_initial_window_size(self) -> None:
        """Open at a size that shows the whole UI on normal displays.

        The installer has enough stacked controls that shorter startup sizes
        force users to resize before they can see the whole workflow.
        """
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        preferred_w = 1320
        preferred_h = 1110
        margin_w = 70
        margin_h = 90

        width = min(preferred_w, max(1120, screen_w - margin_w))
        height = min(preferred_h, max(780, screen_h - margin_h))

        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)

        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(1120, width), min(760, height))

        if sys.platform.startswith("win") and (screen_h < preferred_h + margin_h or screen_w < preferred_w + margin_w):
            try:
                self.state("zoomed")
            except tk.TclError:
                pass

    def _configure_window(self) -> None:
        self.configure(bg=self.BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        try:
            self.iconbitmap(default="")
        except Exception:
            pass

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            ".",
            background=self.BG,
            foreground=self.TEXT,
            fieldbackground=self.SURFACE_3,
            bordercolor=self.BORDER,
            lightcolor=self.BORDER,
            darkcolor=self.BORDER,
            troughcolor=self.SURFACE_3,
            font=("Segoe UI", 10),
        )

        style.configure("Root.TFrame", background=self.BG)
        style.configure("Card.TFrame", background=self.SURFACE, borderwidth=1, relief="solid")
        style.configure("CardInner.TFrame", background=self.SURFACE, borderwidth=0, relief="flat")
        style.configure("SoftCard.TFrame", background=self.SURFACE_2, borderwidth=0, relief="flat")
        style.configure("SoftInner.TFrame", background=self.SURFACE_2, borderwidth=0, relief="flat")
        style.configure("Header.TFrame", background=self.BG)
        style.configure("Output.TFrame", background=self.OUTPUT_BG, borderwidth=1, relief="solid")
        style.configure("OutputInner.TFrame", background=self.OUTPUT_BG, borderwidth=0, relief="flat")

        style.configure("Title.TLabel", background=self.BG, foreground=self.TEXT, font=("Segoe UI", 21, "bold"))
        style.configure("Subtitle.TLabel", background=self.BG, foreground=self.MUTED, font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background=self.SURFACE, foreground=self.TEXT, font=("Segoe UI", 12, "bold"))
        style.configure("CardText.TLabel", background=self.SURFACE, foreground=self.MUTED, font=("Segoe UI", 9))
        style.configure("SoftTitle.TLabel", background=self.SURFACE_2, foreground=self.TEXT, font=("Segoe UI", 10, "bold"))
        style.configure("SoftText.TLabel", background=self.SURFACE_2, foreground=self.MUTED, font=("Segoe UI", 9))
        style.configure("Status.TLabel", background=self.SURFACE_3, foreground=self.MUTED, font=("Segoe UI", 9))
        style.configure("Accent.TLabel", background=self.BG, foreground=self.ACCENT_2, font=("Segoe UI", 10, "bold"))

        style.configure(
            "NC.TButton",
            background=self.ACCENT,
            foreground="white",
            borderwidth=0,
            focusthickness=0,
            padding=(14, 9),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "NC.TButton",
            background=[("active", "#818BFF"), ("disabled", "#313A55")],
            foreground=[("disabled", "#8D98AF")],
        )

        style.configure(
            "Ghost.TButton",
            background=self.SURFACE_2,
            foreground=self.TEXT,
            borderwidth=1,
            padding=(12, 8),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Ghost.TButton",
            background=[("active", "#202A3D"), ("disabled", "#101622")],
            foreground=[("disabled", "#6F7890")],
        )

        style.configure(
            "Danger.TButton",
            background="#44202C",
            foreground="#FFDDE5",
            borderwidth=1,
            padding=(12, 8),
            font=("Segoe UI", 10, "bold"),
        )
        style.map("Danger.TButton", background=[("active", "#592A39")])

        style.configure(
            "NC.TEntry",
            fieldbackground=self.SURFACE_3,
            foreground=self.TEXT,
            bordercolor=self.BORDER,
            insertcolor=self.TEXT,
            padding=(8, 7),
        )
        style.configure(
            "NC.TCombobox",
            fieldbackground=self.SURFACE_3,
            background=self.SURFACE_3,
            foreground=self.TEXT,
            bordercolor=self.BORDER,
            arrowcolor=self.TEXT,
            selectbackground=self.SURFACE_3,
            selectforeground=self.TEXT,
            padding=(8, 7),
        )
        style.map(
            "NC.TCombobox",
            fieldbackground=[("readonly", self.SURFACE_3), ("disabled", self.SURFACE_3)],
            background=[("readonly", self.SURFACE_3), ("active", "#202A3D"), ("disabled", self.SURFACE_3)],
            foreground=[("readonly", self.TEXT), ("disabled", self.MUTED)],
            selectbackground=[("readonly", self.SURFACE_3)],
            selectforeground=[("readonly", self.TEXT)],
            arrowcolor=[("readonly", self.TEXT), ("disabled", self.MUTED)],
        )
        self.option_add("*TCombobox*Listbox.background", self.SURFACE_3)
        self.option_add("*TCombobox*Listbox.foreground", self.TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", "#26334A")
        self.option_add("*TCombobox*Listbox.selectForeground", self.TEXT)

        style.configure(
            "NC.TCheckbutton",
            background=self.SURFACE_2,
            foreground=self.TEXT,
            font=("Segoe UI", 10),
            focuscolor=self.SURFACE_2,
        )
        style.map(
            "NC.TCheckbutton",
            background=[("active", self.SURFACE_2)],
            foreground=[("disabled", "#6F7890")],
        )

        style.configure(
            "NC.Horizontal.TProgressbar",
            background=self.ACCENT_2,
            troughcolor=self.SURFACE_3,
            bordercolor=self.SURFACE_3,
            lightcolor=self.ACCENT_2,
            darkcolor=self.ACCENT_2,
        )

    def _build_ui(self) -> None:
        root = ttk.Frame(self, style="Root.TFrame", padding=(14, 12, 14, 10))
        root.pack(fill=tk.BOTH, expand=True)

        self._build_header(root)

        body = ttk.Frame(root, style="Root.TFrame")
        body.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        body.columnconfigure(0, weight=0, minsize=320)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, style="Root.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        left.rowconfigure(1, weight=0)

        right = ttk.Frame(body, style="Root.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)

        left_targets = self._build_left_scroll_area(left)
        left_actions = ttk.Frame(left, style="Root.TFrame")
        left_actions.grid(row=1, column=0, sticky="ew")

        self._build_python_card(left_targets)
        self._build_install_card(left_targets)
        self._build_actions_card(left_actions)

        self._build_community_card(right, grid_row=0, horizontal_buttons=True, wraplength=760)
        self._build_compatibility_card(right, grid_row=1)
        self._build_command_card(right)
        self._build_output_card(right)

        self._build_footer(root)
        self._refresh_command_preview()

    def _build_left_scroll_area(self, parent: ttk.Frame) -> ttk.Frame:
        shell = ttk.Frame(parent, style="Root.TFrame")
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        canvas = tk.Canvas(shell, bg=self.BG, bd=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient=tk.VERTICAL, command=canvas.yview)
        content = ttk.Frame(canvas, style="Root.TFrame")
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")

        def update_scrollbar() -> None:
            bbox = canvas.bbox("all")
            content_height = int((bbox[3] - bbox[1]) if bbox else 0)
            canvas_height = max(1, int(canvas.winfo_height() or 1))
            if content_height > canvas_height + 2:
                scrollbar.grid(row=0, column=1, sticky="ns")
                canvas.configure(yscrollcommand=scrollbar.set)
            else:
                scrollbar.grid_remove()
                canvas.configure(yscrollcommand=None)
                canvas.yview_moveto(0)

        def sync_scroll_region(_event: tk.Event) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.after_idle(update_scrollbar)

        def sync_content_width(event: tk.Event) -> None:
            canvas.itemconfigure(content_window, width=event.width)
            canvas.after_idle(update_scrollbar)

        content.bind("<Configure>", sync_scroll_region)
        canvas.bind("<Configure>", sync_content_width)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.after_idle(update_scrollbar)
        return content

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent, style="Header.TFrame")
        header.pack(fill=tk.X)
        header.columnconfigure(0, weight=0)
        header.columnconfigure(1, weight=1)
        header.columnconfigure(2, weight=0)
        header.columnconfigure(3, weight=0)

        brand = ttk.Frame(header, style="Header.TFrame")
        brand.grid(row=0, column=0, sticky="w")

        ttk.Label(brand, text="Neural Companion", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            brand,
            text="Installer control center · isolated runtimes · safer setup",
            style="Subtitle.TLabel",
        ).pack(anchor=tk.W, pady=(2, 0))

        self.cracktro_canvas = tk.Canvas(
            header,
            width=440,
            height=58,
            bg=self.BG,
            highlightthickness=0,
            bd=0,
        )
        self.cracktro_canvas.grid(row=0, column=1, sticky="ew", padx=(28, 12), pady=(0, 0))

        music = ttk.Frame(header, style="Header.TFrame")
        music.grid(row=0, column=2, sticky="e", padx=(8, 10))
        tk.Label(
            music,
            textvariable=self.music_status_text,
            bg=self.BG,
            fg=self.MUTED,
            anchor="e",
            justify="right",
            font=("Segoe UI", 8),
        ).grid(row=0, column=0, columnspan=2, sticky="e", pady=(0, 3))
        ttk.Button(music, text="Play", style="Ghost.TButton", command=self._play_music).grid(
            row=1,
            column=0,
            sticky="ew",
            padx=(0, 4),
        )
        ttk.Button(music, text="Stop", style="Danger.TButton", command=self._stop_music).grid(
            row=1,
            column=1,
            sticky="ew",
        )

        badge = tk.Label(
            header,
            text="CRACKTRO MODE",
            bg="#101B33",
            fg=self.ACCENT_2,
            bd=1,
            relief="solid",
            padx=10,
            pady=4,
            font=("Segoe UI", 10, "bold"),
        )
        badge.grid(row=0, column=3, sticky="e")

    def _build_python_card(self, parent: ttk.Frame) -> None:
        card = self._card(parent)
        ttk.Label(card, text="Python 3.11", style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            card,
            text="Choose the Python executable used to create and manage the runtimes.",
            style="CardText.TLabel",
            wraplength=275,
        ).pack(anchor=tk.W, pady=(2, 10))

        row = ttk.Frame(card, style="CardInner.TFrame")
        row.pack(fill=tk.X)
        row.columnconfigure(0, weight=1)

        entry = ttk.Entry(row, textvariable=self.python_path, style="NC.TEntry")
        entry.grid(row=0, column=0, columnspan=2, sticky="ew")
        entry.bind("<KeyRelease>", lambda _event: self._refresh_command_preview())

        row.columnconfigure(1, weight=1)
        row.columnconfigure(2, weight=1)
        ttk.Button(row, text="Detect", style="Ghost.TButton", command=self._auto_detect_python).grid(row=1, column=0, sticky="ew", pady=(8, 0), padx=(0, 4))
        ttk.Button(row, text="Browse", style="Ghost.TButton", command=self._browse_python).grid(row=1, column=1, sticky="ew", pady=(8, 0), padx=4)
        ttk.Button(row, text="Get Python 3.11", style="Ghost.TButton", command=self._open_python_downloads).grid(row=1, column=2, sticky="ew", pady=(8, 0), padx=(4, 0))

        status = tk.Label(
            card,
            textvariable=self.python_status_text,
            bg=self.SURFACE,
            fg=self.MUTED,
            anchor="w",
            justify="left",
            wraplength=275,
            font=("Segoe UI", 9),
        )
        status.pack(fill=tk.X, pady=(10, 0))

    def _build_install_card(self, parent: ttk.Frame) -> None:
        card = self._card(parent)
        ttk.Label(card, text="Install targets", style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            card,
            text="MuseTalk and PocketTTS stay isolated to reduce dependency collisions. Avatar packs install into avatar_packs.",
            style="CardText.TLabel",
            wraplength=275,
        ).pack(anchor=tk.W, pady=(2, 10))

        self._runtime_tile(
            card,
            title="Main runtime",
            description="Core Neural Companion app dependencies.",
            variable=self.install_main,
        )
        self._runtime_tile(
            card,
            title="MuseTalk runtime",
            description="Isolated avatar / talking-head dependency set.",
            variable=self.install_musetalk,
        )
        self._runtime_tile(
            card,
            title="PocketTTS runtime",
            description="Isolated voice runtime. May require Hugging Face login.",
            variable=self.install_pockettts,
        )
        self._avatar_pack_tile(
            card,
            (
                ("Echo avatar pack", "Default feminine MuseTalk avatar pack.", self.install_avatar_echo),
                ("Eon avatar pack", "Default masculine MuseTalk avatar pack.", self.install_avatar_eon),
            ),
        )

    def _runtime_tile(self, parent: ttk.Frame, title: str, description: str, variable: tk.BooleanVar) -> None:
        tile = ttk.Frame(parent, style="SoftCard.TFrame", padding=8)
        tile.pack(fill=tk.X, pady=(0, 6))

        top = ttk.Frame(tile, style="SoftInner.TFrame")
        top.pack(fill=tk.X)

        cb = ttk.Checkbutton(
            top,
            text=title,
            variable=variable,
            style="NC.TCheckbutton",
            command=self._refresh_command_preview,
        )
        cb.pack(anchor=tk.W)

        ttk.Label(tile, text=description, style="SoftText.TLabel", wraplength=275).pack(anchor=tk.W, pady=(2, 0))

    def _avatar_pack_tile(self, parent: ttk.Frame, packs: tuple[tuple[str, str, tk.BooleanVar], ...]) -> None:
        tile = ttk.Frame(parent, style="SoftCard.TFrame", padding=8)
        tile.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(tile, text="Default avatar packs", style="SoftTitle.TLabel").pack(anchor=tk.W)
        for title, description, variable in packs:
            row = ttk.Frame(tile, style="SoftInner.TFrame")
            row.pack(fill=tk.X, pady=(5, 0))
            ttk.Checkbutton(
                row,
                text=title,
                variable=variable,
                style="NC.TCheckbutton",
                command=self._refresh_command_preview,
            ).pack(anchor=tk.W)
            ttk.Label(row, text=description, style="SoftText.TLabel", wraplength=275).pack(anchor=tk.W, pady=(1, 0))

    def _build_actions_card(self, parent: ttk.Frame) -> None:
        card = self._card(parent)

        ttk.Label(card, text="Actions", style="CardTitle.TLabel").pack(anchor=tk.W, pady=(0, 10))

        self.install_button = ttk.Button(card, text="Install selected", style="NC.TButton", command=self._install_selected)
        self.install_button.pack(fill=tk.X)

        self.doctor_button = ttk.Button(card, text="Run preflight only", style="Ghost.TButton", command=self._run_doctor)
        self.doctor_button.pack(fill=tk.X, pady=(8, 0))

        clear_button = ttk.Button(card, text="Clear output", style="Ghost.TButton", command=self._clear_output)
        clear_button.pack(fill=tk.X, pady=(8, 0))

        self.progress = ttk.Progressbar(card, mode="indeterminate", style="NC.Horizontal.TProgressbar")
        self.progress.pack(fill=tk.X, pady=(10, 0))

    def _build_community_card(self, parent: ttk.Frame, *, grid_row: int | None = None, horizontal_buttons: bool = False, wraplength: int = 275) -> None:
        if grid_row is None:
            card = self._card(parent)
        else:
            card = ttk.Frame(parent, style="Card.TFrame", padding=12)
            card.grid(row=grid_row, column=0, sticky="ew", pady=(0, 14))
            card.columnconfigure(0, weight=1)
        ttk.Label(card, text="Community & account help", style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            card,
            text="Join the Discord for setup help, or open Hugging Face pages needed by PocketTTS voice cloning.",
            style="CardText.TLabel",
            wraplength=wraplength,
        ).pack(anchor=tk.W, pady=(4, 10))

        if horizontal_buttons:
            row = ttk.Frame(card, style="CardInner.TFrame")
            row.pack(fill=tk.X)
            for index in range(3):
                row.columnconfigure(index, weight=1, uniform="community_buttons")
            ttk.Button(row, text="Join Discord", style="NC.TButton", command=self._open_discord).grid(row=0, column=0, sticky="ew", padx=(0, 6))
            ttk.Button(row, text="PocketTTS model terms", style="Ghost.TButton", command=self._open_hf_pockettts_terms).grid(row=0, column=1, sticky="ew", padx=6)
            ttk.Button(row, text="Create Hugging Face token", style="Ghost.TButton", command=self._open_hf_token_settings).grid(row=0, column=2, sticky="ew", padx=(6, 0))
        else:
            ttk.Button(card, text="Join Discord", style="NC.TButton", command=self._open_discord).pack(fill=tk.X)
            ttk.Button(card, text="PocketTTS model terms", style="Ghost.TButton", command=self._open_hf_pockettts_terms).pack(fill=tk.X, pady=(8, 0))
            ttk.Button(card, text="Create Hugging Face token", style="Ghost.TButton", command=self._open_hf_token_settings).pack(fill=tk.X, pady=(8, 0))

    def _build_help_card(self, parent: ttk.Frame) -> None:
        card = self._card(parent)
        ttk.Label(card, text="Tip", style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            card,
            text="Run preflight first if you only want to verify Python, paths and setup requirements before installing.",
            style="CardText.TLabel",
            wraplength=275,
        ).pack(anchor=tk.W, pady=(4, 0))

    def _build_compatibility_card(self, parent: ttk.Frame, *, grid_row: int) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=12)
        card.grid(row=grid_row, column=0, sticky="ew", pady=(0, 14))
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text="Compatibility", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            card,
            text="Override PyTorch only when GPU detection or an existing Torch setup needs manual control.",
            style="CardText.TLabel",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))

        row = ttk.Frame(card, style="CardInner.TFrame")
        row.grid(row=2, column=0, sticky="ew")
        row.columnconfigure(0, weight=0)
        row.columnconfigure(1, weight=1)
        ttk.Checkbutton(
            row,
            text="Skip main-app Torch install",
            variable=self.skip_main_torch,
            style="NC.TCheckbutton",
            command=self._refresh_command_preview,
        ).grid(row=0, column=0, sticky="w", padx=(0, 14))
        torch_combo = ttk.Combobox(
            row,
            textvariable=self.torch_stack_label,
            values=tuple(TORCH_STACK_LABELS.keys()),
            state="readonly",
            style="NC.TCombobox",
        )
        torch_combo.grid(row=0, column=1, sticky="ew")
        torch_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_command_preview())

    def _build_command_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=12)
        card.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="Command preview", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.command_preview_label = tk.Label(
            card,
            textvariable=self.command_preview,
            bg=self.SURFACE_3,
            fg=self.OUTPUT_FG,
            anchor="w",
            justify="left",
            padx=12,
            pady=6,
            wraplength=700,
            font=("Consolas", 9),
            bd=1,
            relief="solid",
        )
        self.command_preview_label.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.command_preview_label.bind(
            "<Configure>",
            lambda event: self.command_preview_label.configure(wraplength=max(360, event.width - 24)),
        )

    def _build_output_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Output.TFrame", padding=10)
        card.grid(row=3, column=0, sticky="nsew")
        card.rowconfigure(1, weight=1)
        card.columnconfigure(0, weight=1)

        header = ttk.Frame(card, style="OutputInner.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(
            header,
            text="Installer output",
            background=self.OUTPUT_BG,
            foreground=self.TEXT,
            font=("Segoe UI", 12, "bold"),
        ).pack(side=tk.LEFT)

        self.output_state = tk.Label(
            header,
            text="idle",
            bg="#101B33",
            fg=self.MUTED,
            padx=9,
            pady=3,
            font=("Segoe UI", 8, "bold"),
        )
        self.output_state.pack(side=tk.RIGHT)

        output_wrap = ttk.Frame(card, style="OutputInner.TFrame")
        output_wrap.grid(row=1, column=0, sticky="nsew")
        output_wrap.rowconfigure(0, weight=1)
        output_wrap.columnconfigure(0, weight=1)

        self.output = tk.Text(
            output_wrap,
            bg=self.OUTPUT_BG,
            fg=self.OUTPUT_FG,
            bd=0,
            highlightthickness=0,
            relief=tk.FLAT,
            wrap=tk.WORD,
            undo=False,
            font=self._output_font,
            insertbackground=self.TEXT,
            selectbackground="#32496A",
            selectforeground=self.TEXT,
            padx=12,
            pady=10,
        )
        self.output.grid(row=0, column=0, sticky="nsew")
        self.output.configure(state=tk.DISABLED)
        self.output.bind("<Control-a>", self._select_all_output)
        self.output.bind("<Control-A>", self._select_all_output)
        for tag_name in ("command", "error", "success", "warning", "muted"):
            self.output.tag_configure(tag_name, foreground=self._output_color(tag_name))

        scrollbar = ttk.Scrollbar(output_wrap, orient=tk.VERTICAL, command=self.output.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.output.configure(yscrollcommand=scrollbar.set)

        self._append_output("Neural Companion installer ready.\n", tag="success")
        self._append_output("Choose install targets or run preflight.\n\n", tag="muted")

    def _build_footer(self, parent: ttk.Frame) -> None:
        footer = ttk.Frame(parent, style="Root.TFrame")
        footer.pack(fill=tk.X, pady=(8, 0))

        status_bar = tk.Label(
            footer,
            textvariable=self.status_text,
            bg=self.SURFACE_3,
            fg=self.MUTED,
            anchor="center",
            justify="center",
            padx=12,
            pady=6,
            font=("Segoe UI", 9),
            bd=1,
            relief="solid",
        )
        status_bar.pack(fill=tk.X)

    def _card(self, parent: ttk.Frame) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=12)
        card.pack(fill=tk.X, pady=(0, 10))
        return card

    def _animate_cracktro(self) -> None:
        canvas = getattr(self, "cracktro_canvas", None)
        if canvas is None:
            return

        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill=self.SURFACE_3, outline=self.BORDER)

        for y in range(6, height, 8):
            color = "#111827" if (y + self._vibe_tick) % 16 else "#1B2740"
            canvas.create_line(0, y, width, y, fill=color)

        glow = self.ACCENT_2 if self.audio_controller.is_playing() else self.MUTED
        canvas.create_text(
            14,
            12,
            anchor="nw",
            text="CIRCUIT SAFFRON",
            fill=glow,
            font=("Consolas", 11, "bold"),
        )
        canvas.create_text(
            15,
            34,
            anchor="nw",
            text="NEURAL COMPANION INSTALLER",
            fill=self.TEXT,
            font=("Consolas", 8, "bold"),
        )

        bars = 18
        bar_w = 5
        start_x = width - (bars * 9) - 12
        base_y = height - 9
        for index in range(bars):
            phase = (self._vibe_tick + index * 3) % 24
            rise = 7 + abs(12 - phase)
            if not self.audio_controller.is_playing():
                rise = 5 + (index % 3)
            x = start_x + index * 9
            color = self.ACCENT_2 if index % 3 else self.ACCENT
            canvas.create_rectangle(x, base_y - rise, x + bar_w, base_y, fill=color, outline="")

        scan_x = (self._vibe_tick * 7) % (width + 30) - 30
        canvas.create_rectangle(scan_x, 1, scan_x + 24, height - 1, fill="#1E3358", outline="", stipple="gray50")

        self._vibe_tick = (self._vibe_tick + 1) % 240
        self.after(90, self._animate_cracktro)

    def _play_music(self, autoplay: bool = False) -> None:
        ok, message = self.audio_controller.play()
        if ok:
            self.music_status_text.set("Looping Circuit_Saffron.mp3")
            if not autoplay:
                self._append_output("\nMusic started: Circuit_Saffron.mp3\n", tag="command")
            return

        self.music_status_text.set("Music unavailable")
        detail = f"\nMusic could not start: {message}\n"
        self._append_output(detail, tag="warning" if autoplay else "error")
        if not autoplay:
            messagebox.showwarning("Installer Music", message)

    def _stop_music(self) -> None:
        self.audio_controller.stop()
        self.music_status_text.set("Music stopped")
        self._append_output("\nMusic stopped.\n", tag="muted")

    def _stop_music_silent(self) -> None:
        self.audio_controller.stop()
        self.music_status_text.set("Music stopped")

    def _open_url(self, url: str, label: str) -> None:
        try:
            webbrowser.open_new_tab(url)
            self._append_output(f"\nOpened {label}: {url}\n", tag="command")
        except Exception as exc:
            self._append_output(f"\nCould not open {label}: {exc}\n", tag="error")
            messagebox.showwarning(label, f"Could not open:\n{url}\n\n{exc}")

    def _open_discord(self) -> None:
        self._open_url(DISCORD_INVITE_URL, "Neural Companion Discord")

    def _open_hf_pockettts_terms(self) -> None:
        self._open_url(HF_POCKETTTS_TERMS_URL, "PocketTTS Hugging Face model terms")

    def _open_hf_token_settings(self) -> None:
        self._open_url(HF_TOKEN_SETTINGS_URL, "Hugging Face token settings")
        messagebox.showinfo(
            "Create Hugging Face Token",
            "To create a token for PocketTTS:\n\n"
            "1. Sign in to Hugging Face.\n"
            "2. Open Settings -> Access Tokens.\n"
            "3. Choose New token.\n"
            "4. Use a Read token; no Write permission is needed.\n"
            "5. Copy the token when Hugging Face shows it.\n"
            "6. Paste it into the `hf auth login` terminal opened by the installer.\n\n"
            "Also accept the PocketTTS model terms before testing voice cloning.",
        )

    def _open_python_downloads(self) -> None:
        self._open_url(PYTHON_WINDOWS_DOWNLOADS_URL, "Python Windows downloads")
        messagebox.showinfo(
            "Install Python 3.11",
            "Download and install a Python 3.11 Windows installer.\n\n"
            "After installation, press Detect again or browse to python.exe manually.",
        )

    def _on_close(self) -> None:
        if self.process is not None:
            should_close = messagebox.askyesno(
                "Installer running",
                "The installer is still running.\n\n"
                "Close the window and leave the installer process running in the background?",
            )
            if not should_close:
                return
        self._cancel_feature_status_rotation()
        self._stop_music_silent()
        self.destroy()

    # ---------------------------------------------------------------------
    # Output helpers
    # ---------------------------------------------------------------------

    def _load_output_backdrops(self) -> None:
        assets = {
            "echo": REPO_ROOT / "installer_assets" / "echo_output_watermark.png",
            "eon": REPO_ROOT / "installer_assets" / "eon_output_watermark.png",
        }
        for key, path in assets.items():
            if not path.exists():
                continue
            try:
                self.output_backdrops[key] = tk.PhotoImage(file=str(path))
            except tk.TclError:
                continue

    def _set_output_backdrop(self, key: str | None) -> None:
        if key == self._active_output_backdrop_key:
            return
        self._active_output_backdrop_key = key
        image = self.output_backdrops.get(key or "")
        if image is None:
            return
        self.output.configure(state=tk.NORMAL)
        self.output.insert(tk.END, "\n")
        self.output.image_create(tk.END, image=image)
        self.output.insert(tk.END, "\n\n")
        self.output.configure(state=tk.DISABLED)
        self.output.see(tk.END)

    def _sync_output_canvas(self) -> None:
        return None

    def _sync_output_scrollregion(self) -> None:
        return None

    def _scroll_output_canvas(self, event: tk.Event) -> str:
        return ""

    def _select_all_output(self, _event: tk.Event) -> str:
        self.output.tag_add(tk.SEL, "1.0", tk.END)
        self.output.mark_set(tk.INSERT, "1.0")
        self.output.see(tk.INSERT)
        return "break"

    def _output_color(self, tag: str | None) -> str:
        colors = {
            "command": self.ACCENT_2,
            "error": self.DANGER,
            "success": self.SUCCESS,
            "warning": self.WARNING,
            "muted": self.MUTED,
        }
        return colors.get(tag or "", self.OUTPUT_FG)

    def _auto_output_tag(self, text: str) -> str | None:
        lower = text.lower()
        if "error" in lower or "failed" in lower or "traceback" in lower:
            return "error"
        if "success" in lower or "verified" in lower or "installed successfully" in lower:
            return "success"
        if "warning" in lower or "missing" in lower or "skip" in lower:
            return "warning"
        return None

    def _update_output_backdrop_from_text(self, text: str) -> None:
        lower = text.lower()
        if "echo avatar pack" in lower:
            self._set_output_backdrop("echo")
        elif "eon avatar pack" in lower:
            self._set_output_backdrop("eon")
        elif "installer summary" in lower or "installer exited" in lower:
            self._set_output_backdrop(None)

    def _append_output(self, text: str, tag: str | None = None) -> None:
        text = ANSI_ESCAPE_RE.sub("", text).replace("\r", "\n")
        self._update_output_backdrop_from_text(text)
        active_tag = tag or self._auto_output_tag(text)
        self.output.configure(state=tk.NORMAL)
        self.output.insert(tk.END, text, active_tag or ())
        self.output.configure(state=tk.DISABLED)
        self.output.see(tk.END)

    def _clear_output(self) -> None:
        self.output.configure(state=tk.NORMAL)
        self.output.delete("1.0", tk.END)
        self.output.configure(state=tk.DISABLED)
        self._output_line_y = 12
        self._set_output_backdrop(None)
        self._append_output("Output cleared.\n\n", tag="muted")

    def _set_running_ui(self, running: bool) -> None:
        self._installer_running = running
        state = tk.DISABLED if running else tk.NORMAL
        self.install_button.configure(state=state)
        self.doctor_button.configure(state=state)

        if running:
            self._cancel_feature_status_rotation()
            self._feature_status_index = 0
            self._update_running_feature_status()
            self.output_state.configure(text="running", fg=self.ACCENT_2)
            self.progress.start(12)
        else:
            self._cancel_feature_status_rotation()
            self.progress.stop()
            if self.last_exit_code == 0:
                self.status_text.set("Finished successfully")
                self.output_state.configure(text="success", fg=self.SUCCESS)
            elif self.last_exit_code is None:
                self.status_text.set("Ready")
                self.output_state.configure(text="idle", fg=self.MUTED)
            else:
                self.status_text.set(f"Finished with exit code {self.last_exit_code}")
                self.output_state.configure(text="attention", fg=self.WARNING)

    def _update_running_feature_status(self) -> None:
        if not self._installer_running:
            return
        message = self._feature_status_messages[self._feature_status_index % len(self._feature_status_messages)]
        self.status_text.set(f"Installer running... {message}")
        self._feature_status_index += 1
        self._feature_status_after_id = self.after(4500, self._update_running_feature_status)

    def _cancel_feature_status_rotation(self) -> None:
        if self._feature_status_after_id is None:
            return
        try:
            self.after_cancel(self._feature_status_after_id)
        except tk.TclError:
            pass
        self._feature_status_after_id = None

    def _format_command(self, command: list[str]) -> str:
        return " ".join(f'"{item}"' if " " in item else item for item in command)

    def _initial_output_backdrop_for_command(self, command: list[str]) -> str | None:
        if "--avatar-pack-echo" in command or "--avatar-packs" in command:
            return "echo"
        if "--avatar-pack-eon" in command:
            return "eon"
        return None

    def _refresh_command_preview(self) -> None:
        try:
            command = self._installer_base_command()
            selected = []
            if self.install_main.get():
                selected.append("--main")
            if self.install_musetalk.get():
                selected.append("--musetalk")
            if self.install_pockettts.get():
                selected.append("--pockettts")
            if self.install_avatar_echo.get():
                selected.append("--avatar-pack-echo")
            if self.install_avatar_eon.get():
                selected.append("--avatar-pack-eon")
            command.extend(selected or ["<choose at least one target>"])
            self.command_preview.set(self._format_command(command))
        except Exception as exc:
            self.command_preview.set(f"Could not build preview: {exc}")

    # ---------------------------------------------------------------------
    # Original installer behavior
    # ---------------------------------------------------------------------

    def _auto_detect_python(self) -> None:
        candidates = find_python311_executables()
        if candidates:
            self.python_path.set(candidates[0])
            self.python_status_text.set(f"Detected Python 3.11:\n{candidates[0]}")
            self.status_text.set("Python 3.11 detected")
        else:
            self.python_path.set("")
            self.python_status_text.set(
                "No Python 3.11 executable detected. The installer will still try the Windows py launcher."
            )
            self.status_text.set("Python 3.11 not detected automatically")
        self._refresh_command_preview()

    def _browse_python(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select Python 3.11 executable",
            filetypes=[("Python executable", "python.exe"), ("Executables", "*.exe"), ("All files", "*.*")],
        )
        if not selected:
            return
        version = get_python_minor_version([selected])
        self.python_path.set(selected)
        if version == "3.11":
            self.python_status_text.set(f"Selected Python 3.11:\n{selected}")
            self.status_text.set("Python 3.11 selected")
        else:
            self.python_status_text.set(
                f"Selected file reports Python {version or 'unknown'}; install will stop unless this is Python 3.11."
            )
            self.status_text.set("Selected Python version may be incompatible")
        self._refresh_command_preview()

    def _installer_base_command(self) -> list[str]:
        command = [sys.executable, str(REPO_ROOT / "install_neural_companion.py")]
        python_path = self.python_path.get().strip()
        if python_path:
            command.extend(["--python-exe", python_path])
        command.append("--non-interactive")
        torch_stack = self._torch_stack_value()
        if torch_stack != "auto":
            command.extend(["--torch-stack", torch_stack])
        if self.skip_main_torch.get():
            command.append("--skip-main-torch")
        return command

    def _torch_stack_value(self) -> str:
        return str(TORCH_STACK_LABELS.get(self.torch_stack_label.get(), "auto"))

    def _run_doctor(self) -> None:
        command = self._installer_base_command()
        command.append("--doctor-only")
        self._start_command(command)

    def _install_selected(self) -> None:
        command = self._installer_base_command()
        if self.install_main.get():
            command.append("--main")
        if self.install_musetalk.get():
            command.append("--musetalk")
        if self.install_pockettts.get():
            command.append("--pockettts")
        if self.install_avatar_echo.get():
            command.append("--avatar-pack-echo")
        if self.install_avatar_eon.get():
            command.append("--avatar-pack-eon")
        if not any((
            self.install_main.get(),
            self.install_musetalk.get(),
            self.install_pockettts.get(),
            self.install_avatar_echo.get(),
            self.install_avatar_eon.get(),
        )):
            messagebox.showwarning("Nothing selected", "Choose at least one runtime to install.")
            return
        self._start_command(command)

    def _start_command(self, command: list[str]) -> None:
        if self.process is not None:
            messagebox.showinfo("Installer running", "An installer process is already running.")
            return

        self._set_running_ui(True)
        self.current_command = list(command)
        self.current_output = []
        self.last_exit_code = None

        self._append_output("\n> " + self._format_command(command) + "\n\n", tag="command")
        self._set_output_backdrop(self._initial_output_backdrop_for_command(command))

        thread = threading.Thread(target=self._run_command_thread, args=(command,), daemon=True)
        thread.start()

    def _run_command_thread(self, command: list[str]) -> None:
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.output_queue.put(line)
            code = self.process.wait()
            self.output_queue.put(("done", code))
        except Exception as exc:
            self.output_queue.put(f"\nInstaller failed to start: {exc}\n")
        finally:
            self.process = None
            self.output_queue.put(None)

    def _drain_output_queue(self) -> None:
        try:
            while True:
                item = self.output_queue.get_nowait()
                if item is None:
                    self._stop_music_silent()
                    self._set_running_ui(False)
                    self._handle_command_finished()
                elif isinstance(item, tuple) and item[0] == "done":
                    self.last_exit_code = item[1]
                    if item[1] == 0:
                        self._append_output(f"\nInstaller exited with code {item[1]}.\n", tag="success")
                    else:
                        self._append_output(f"\nInstaller exited with code {item[1]}.\n", tag="warning")
                else:
                    self._append_output(item)
                    self.current_output.append(item)
        except queue.Empty:
            pass
        self.after(100, self._drain_output_queue)

    def _handle_command_finished(self) -> None:
        if self.last_exit_code != 0:
            return
        if "--doctor-only" in self.current_command:
            return

        output = "".join(self.current_output)
        if "--pockettts" in self.current_command and POCKETTTS_LOGIN_MISSING_TEXT in output:
            should_login = messagebox.askyesno(
                "PocketTTS Hugging Face Login",
                "PocketTTS installed successfully, but voice cloning needs a Hugging Face login.\n\n"
                "Before login:\n"
                "1. Accept the model terms at https://huggingface.co/kyutai/pocket-tts\n"
                "2. Create a Read token at https://huggingface.co/settings/tokens\n"
                "3. Copy the token. The login terminal will ask you to paste it.\n\n"
                "Choose Yes to open the Hugging Face login window now.\n\n"
                "Choose No to skip this for now.",
            )
            if should_login:
                self._launch_pockettts_hf_login()
            else:
                self._append_output("\nPocketTTS Hugging Face login skipped for now.\n", tag="warning")

        self._offer_launch_after_success()

    def _offer_launch_after_success(self) -> None:
        main_python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
        if "--main" not in self.current_command and not main_python.exists():
            return

        should_launch = messagebox.askyesno(
            "Installation Finished",
            "Installation finished successfully.\n\nDo you want to start Neural Companion now?",
        )
        if not should_launch:
            self._append_output("\nNeural Companion launch skipped.\n", tag="muted")
            return
        self._launch_neural_companion()

    def _launch_neural_companion(self) -> None:
        launcher = REPO_ROOT / "run_neural_companion.bat"
        if not launcher.exists():
            messagebox.showwarning("Launch Neural Companion", f"Launcher not found:\n{launcher}")
            return
        if not sys.platform.startswith("win"):
            messagebox.showinfo(
                "Launch Neural Companion",
                f"Run this launcher on Windows:\n\n{launcher}",
            )
            return

        try:
            subprocess.Popen(
                ["cmd.exe", "/c", str(launcher)],
                cwd=str(REPO_ROOT),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except Exception as exc:
            self._append_output(f"\nCould not launch Neural Companion: {exc}\n", tag="error")
            messagebox.showwarning("Launch Neural Companion", f"Could not launch Neural Companion:\n{exc}")
            return

        self._append_output("\nLaunched Neural Companion.\n", tag="success")

    def _launch_pockettts_hf_login(self) -> None:
        hf_exe = REPO_ROOT / ".venvs" / "pockettts" / "Scripts" / "hf.exe"
        if not hf_exe.exists():
            should_install_cli = messagebox.askyesno(
                "PocketTTS Login",
                "The PocketTTS Hugging Face command was not found.\n\n"
                "Do you want the installer to add the Hugging Face CLI to the isolated PocketTTS runtime now?",
            )
            if not should_install_cli:
                self._append_output("\nPocketTTS Hugging Face CLI install skipped.\n", tag="warning")
                return
            if not self._install_pockettts_hf_cli():
                return
            if not hf_exe.exists():
                messagebox.showwarning(
                    "PocketTTS Login",
                    f"The Hugging Face CLI still was not found at:\n{hf_exe}",
                )
                return

        if sys.platform.startswith("win"):
            command = ["cmd.exe", "/k", "call", str(hf_exe), "auth", "login"]
            subprocess.Popen(command, cwd=str(REPO_ROOT), creationflags=subprocess.CREATE_NEW_CONSOLE)
            self._append_output(f"\nOpened Hugging Face login window: {hf_exe} auth login\n", tag="command")
            messagebox.showinfo(
                "PocketTTS Login",
                "Complete the Hugging Face login in the terminal window.\n\n"
                "If you need a token, open Hugging Face Settings -> Access Tokens, create a Read token, "
                "copy it, and paste it into the terminal.\n\n"
                "After it reports success, close that terminal and press OK here.",
            )
        else:
            messagebox.showinfo(
                "PocketTTS Login",
                f"Run this command in a terminal:\n\n{hf_exe} auth login",
            )
            return

        self._recheck_pockettts_hf_login(hf_exe)

    def _install_pockettts_hf_cli(self) -> bool:
        python_exe = REPO_ROOT / ".venvs" / "pockettts" / "Scripts" / "python.exe"
        if not python_exe.exists():
            messagebox.showwarning(
                "PocketTTS Login",
                f"Could not find the PocketTTS Python runtime at:\n{python_exe}",
            )
            return False

        command = [str(python_exe), "-m", "pip", "install", "--upgrade", "huggingface_hub[cli]"]
        self._append_output("\nInstalling Hugging Face CLI into PocketTTS runtime...\n", tag="command")
        self._append_output("> " + self._format_command(command) + "\n\n", tag="command")
        try:
            result = subprocess.run(
                command,
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                check=False,
            )
        except Exception as exc:
            self._append_output(f"\nCould not install Hugging Face CLI: {exc}\n", tag="error")
            messagebox.showwarning("PocketTTS Login", f"Could not install Hugging Face CLI:\n{exc}")
            return False

        if result.stdout:
            self._append_output(result.stdout)
        if result.stderr:
            self._append_output(result.stderr)
        if result.returncode != 0:
            messagebox.showwarning(
                "PocketTTS Login",
                "The Hugging Face CLI install failed. PocketTTS remains installed, "
                "but login could not be launched automatically.",
            )
            return False
        return True

    def _recheck_pockettts_hf_login(self, hf_exe: Path) -> None:
        python_exe = hf_exe.parent / "python.exe"
        checker = """
import json
from huggingface_hub import HfApi
from huggingface_hub.utils import get_token

token = get_token()
status = {"has_token": bool(token), "whoami_ok": False, "identity": ""}
if token:
    try:
        who = HfApi().whoami(token=token)
        if isinstance(who, dict):
            status["identity"] = who.get("name") or who.get("fullname") or who.get("email") or ""
        else:
            status["identity"] = str(who)
        status["whoami_ok"] = True
    except Exception as exc:
        status["identity"] = f"token present but whoami failed: {exc}"
print(json.dumps(status))
"""
        try:
            result = subprocess.run(
                [str(python_exe), "-c", checker],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                check=False,
            )
        except Exception as exc:
            self._append_output(f"\nCould not recheck Hugging Face login: {exc}\n", tag="error")
            return

        combined = ((result.stdout or "") + (result.stderr or "")).strip()
        if result.returncode == 0:
            try:
                payload = json.loads((result.stdout or "").strip())
            except Exception:
                payload = {}
            if payload.get("whoami_ok"):
                identity = payload.get("identity") or "signed-in user"
                self._append_output(f"\nPocketTTS Hugging Face login verified: {identity}\n", tag="success")
                messagebox.showinfo("PocketTTS Login", "Hugging Face login verified for PocketTTS.")
                return
            if payload.get("has_token"):
                detail = payload.get("identity") or "token present, but account verification failed"
                self._append_output(f"\nPocketTTS Hugging Face token detected: {detail}\n", tag="warning")
                messagebox.showinfo(
                    "PocketTTS Login",
                    "A Hugging Face token was found. PocketTTS is installed, but gated model terms "
                    "may still need to be accepted on Hugging Face.",
                )
                return

            self._append_output("\nPocketTTS Hugging Face login is still not verified: no token found.\n", tag="warning")
            if combined:
                self._append_output(combined + "\n")
            messagebox.showwarning(
                "PocketTTS Login",
                "No Hugging Face token was found yet. PocketTTS remains installed, "
                "but voice cloning may not work until login and model terms are complete.",
            )
        else:
            self._append_output("\nPocketTTS Hugging Face login is still not verified.\n", tag="warning")
            if combined:
                self._append_output(combined + "\n")
            messagebox.showwarning(
                "PocketTTS Login",
                "Hugging Face login could not be verified yet. PocketTTS remains installed, "
                "but voice cloning may not work until login and model terms are complete.",
            )


def main() -> int:
    app = NeuralCompanionInstallerGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
