#!/usr/bin/env python
from __future__ import annotations

import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from install_neural_companion import REPO_ROOT, find_python311_executables, get_python_minor_version


POCKETTTS_LOGIN_MISSING_TEXT = "No Hugging Face login detected"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


class NeuralCompanionInstallerGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Neural Companion Installer")
        self.geometry("900x620")
        self.minsize(760, 520)
        self.output_queue: queue.Queue[str | tuple[str, int] | None] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.current_command: list[str] = []
        self.current_output: list[str] = []
        self.last_exit_code: int | None = None

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
        text = ANSI_ESCAPE_RE.sub("", text)
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
        self.current_command = list(command)
        self.current_output = []
        self.last_exit_code = None
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
                    self.install_button.configure(state=tk.NORMAL)
                    self.doctor_button.configure(state=tk.NORMAL)
                    self._handle_command_finished()
                elif isinstance(item, tuple) and item[0] == "done":
                    self.last_exit_code = item[1]
                    self._append_output(f"\nInstaller exited with code {item[1]}.\n")
                else:
                    self._append_output(item)
                    self.current_output.append(item)
        except queue.Empty:
            pass
        self.after(100, self._drain_output_queue)

    def _handle_command_finished(self) -> None:
        if self.last_exit_code != 0 or "--pockettts" not in self.current_command:
            return
        output = "".join(self.current_output)
        if POCKETTTS_LOGIN_MISSING_TEXT not in output:
            return

        should_login = messagebox.askyesno(
            "PocketTTS Hugging Face Login",
            "PocketTTS installed successfully, but voice cloning needs a Hugging Face login.\n\n"
            "Accept the terms at https://huggingface.co/kyutai/pocket-tts, then choose Yes "
            "to open a login window now.\n\n"
            "Choose No to skip this for now.",
        )
        if not should_login:
            self._append_output("\nPocketTTS Hugging Face login skipped for now.\n")
            return
        self._launch_pockettts_hf_login()

    def _launch_pockettts_hf_login(self) -> None:
        hf_exe = REPO_ROOT / ".venvs" / "pockettts" / "Scripts" / "hf.exe"
        if not hf_exe.exists():
            should_install_cli = messagebox.askyesno(
                "PocketTTS Login",
                "The PocketTTS Hugging Face command was not found.\n\n"
                "Do you want the installer to add the Hugging Face CLI to the isolated PocketTTS runtime now?",
            )
            if not should_install_cli:
                self._append_output("\nPocketTTS Hugging Face CLI install skipped.\n")
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
            self._append_output(f"\nOpened Hugging Face login window: {hf_exe} auth login\n")
            messagebox.showinfo(
                "PocketTTS Login",
                "Complete the Hugging Face login in the terminal window.\n\n"
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
        self._append_output("\nInstalling Hugging Face CLI into PocketTTS runtime...\n")
        self._append_output("> " + " ".join(f'"{item}"' if " " in item else item for item in command) + "\n\n")
        try:
            result = subprocess.run(
                command,
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                check=False,
            )
        except Exception as exc:
            self._append_output(f"\nCould not install Hugging Face CLI: {exc}\n")
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
            self._append_output(f"\nCould not recheck Hugging Face login: {exc}\n")
            return

        combined = ((result.stdout or "") + (result.stderr or "")).strip()
        if result.returncode == 0:
            try:
                payload = __import__("json").loads((result.stdout or "").strip())
            except Exception:
                payload = {}
            if payload.get("whoami_ok"):
                identity = payload.get("identity") or "signed-in user"
                self._append_output(f"\nPocketTTS Hugging Face login verified: {identity}\n")
                messagebox.showinfo("PocketTTS Login", "Hugging Face login verified for PocketTTS.")
                return
            if payload.get("has_token"):
                detail = payload.get("identity") or "token present, but account verification failed"
                self._append_output(f"\nPocketTTS Hugging Face token detected: {detail}\n")
                messagebox.showinfo(
                    "PocketTTS Login",
                    "A Hugging Face token was found. PocketTTS is installed, but gated model terms "
                    "may still need to be accepted on Hugging Face.",
                )
                return

            self._append_output("\nPocketTTS Hugging Face login verified.\n")
            if combined:
                self._append_output(combined + "\n")
            messagebox.showinfo("PocketTTS Login", "Hugging Face login verified for PocketTTS.")
        else:
            self._append_output("\nPocketTTS Hugging Face login is still not verified.\n")
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
