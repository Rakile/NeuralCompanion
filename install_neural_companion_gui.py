#!/usr/bin/env python
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from install_neural_companion import REPO_ROOT, find_python311_executables, get_python_minor_version


class NeuralCompanionInstallerGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Neural Companion Installer")
        self.geometry("900x620")
        self.minsize(760, 520)
        self.output_queue: queue.Queue[str | None] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None

        self.python_path = tk.StringVar(value="")
        self.install_main = tk.BooleanVar(value=True)
        self.install_musetalk = tk.BooleanVar(value=True)
        self.install_pockettts = tk.BooleanVar(value=True)
        self.skip_main_torch = tk.BooleanVar(value=False)

        self._build_ui()
        self._auto_detect_python()
        self.after(100, self._drain_output_queue)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(outer, text="Neural Companion Installer", font=("Segoe UI", 16, "bold"))
        title.pack(anchor=tk.W)

        subtitle = ttk.Label(
            outer,
            text="Select the runtimes to install. MuseTalk and PocketTTS are isolated so their dependencies do not collide with the main app.",
        )
        subtitle.pack(anchor=tk.W, pady=(2, 14))

        python_frame = ttk.LabelFrame(outer, text="Python 3.11")
        python_frame.pack(fill=tk.X, pady=(0, 12))
        python_row = ttk.Frame(python_frame, padding=8)
        python_row.pack(fill=tk.X)
        ttk.Entry(python_row, textvariable=self.python_path).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(python_row, text="Detect", command=self._auto_detect_python).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(python_row, text="Browse...", command=self._browse_python).pack(side=tk.LEFT, padx=(8, 0))
        self.python_status = ttk.Label(python_frame, text="", padding=(8, 0, 8, 8))
        self.python_status.pack(anchor=tk.W)

        options = ttk.LabelFrame(outer, text="Install")
        options.pack(fill=tk.X, pady=(0, 12))
        option_inner = ttk.Frame(options, padding=8)
        option_inner.pack(fill=tk.X)
        ttk.Checkbutton(option_inner, text="Main Neural Companion runtime", variable=self.install_main).grid(row=0, column=0, sticky=tk.W, padx=(0, 24), pady=2)
        ttk.Checkbutton(option_inner, text="Isolated MuseTalk runtime", variable=self.install_musetalk).grid(row=0, column=1, sticky=tk.W, padx=(0, 24), pady=2)
        ttk.Checkbutton(option_inner, text="Isolated PocketTTS runtime", variable=self.install_pockettts).grid(row=0, column=2, sticky=tk.W, pady=2)
        ttk.Checkbutton(option_inner, text="Skip main-app torch install", variable=self.skip_main_torch).grid(row=1, column=0, sticky=tk.W, pady=(8, 2))

        actions = ttk.Frame(outer)
        actions.pack(fill=tk.X, pady=(0, 10))
        self.install_button = ttk.Button(actions, text="Install Selected", command=self._install_selected)
        self.install_button.pack(side=tk.LEFT)
        self.doctor_button = ttk.Button(actions, text="Run Preflight Only", command=self._run_doctor)
        self.doctor_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Clear Output", command=self._clear_output).pack(side=tk.RIGHT)

        output_frame = ttk.LabelFrame(outer, text="Installer Output")
        output_frame.pack(fill=tk.BOTH, expand=True)
        self.output = tk.Text(output_frame, wrap=tk.WORD, height=18)
        self.output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(output_frame, orient=tk.VERTICAL, command=self.output.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.output.configure(yscrollcommand=scrollbar.set)

    def _append_output(self, text: str) -> None:
        self.output.insert(tk.END, text)
        self.output.see(tk.END)

    def _clear_output(self) -> None:
        self.output.delete("1.0", tk.END)

    def _auto_detect_python(self) -> None:
        candidates = find_python311_executables()
        if candidates:
            self.python_path.set(candidates[0])
            self.python_status.configure(text=f"Detected Python 3.11: {candidates[0]}")
        else:
            self.python_path.set("")
            self.python_status.configure(text="No Python 3.11 executable detected. The installer will still try the Windows py launcher.")

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
            self.python_status.configure(text=f"Selected Python 3.11: {selected}")
        else:
            self.python_status.configure(text=f"Selected file reports Python {version or 'unknown'}; install will stop unless this is Python 3.11.")

    def _installer_base_command(self) -> list[str]:
        command = [sys.executable, str(REPO_ROOT / "install_neural_companion.py")]
        python_path = self.python_path.get().strip()
        if python_path:
            command.extend(["--python-exe", python_path])
        command.append("--non-interactive")
        if self.skip_main_torch.get():
            command.append("--skip-main-torch")
        return command

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
        if not any((self.install_main.get(), self.install_musetalk.get(), self.install_pockettts.get())):
            messagebox.showwarning("Nothing selected", "Choose at least one runtime to install.")
            return
        self._start_command(command)

    def _start_command(self, command: list[str]) -> None:
        if self.process is not None:
            messagebox.showinfo("Installer running", "An installer process is already running.")
            return
        self.install_button.configure(state=tk.DISABLED)
        self.doctor_button.configure(state=tk.DISABLED)
        self._append_output("\n> " + " ".join(f'"{item}"' if " " in item else item for item in command) + "\n\n")
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
            self.output_queue.put(f"\nInstaller exited with code {code}.\n")
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
                    self.install_button.configure(state=tk.NORMAL)
                    self.doctor_button.configure(state=tk.NORMAL)
                else:
                    self._append_output(item)
        except queue.Empty:
            pass
        self.after(100, self._drain_output_queue)


def main() -> int:
    app = NeuralCompanionInstallerGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
