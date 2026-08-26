"""Desktop GUI for the Clarius RAW Data Downloader.

The interface is intentionally built with tkinter so the packaged Windows app
does not depend on a separate GUI runtime. Playwright and Chromium are bundled
by the accompanying PyInstaller build.
"""

from __future__ import annotations

import ast
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import traceback
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any


APP_NAME = "Clarius RAW Data Downloader"
APP_VERSION = "1.1.0"
SETTINGS_FILENAME = "settings.json"


def application_data_dir() -> Path:
    """Return a per-user, writable folder for non-sensitive app settings."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "UnityHealth" / "ClariusRawDownloader"


def default_output_folder() -> str:
    documents = Path.home() / "Documents"
    return str(documents / "Clarius Raw Downloads")


@dataclass
class AppSettings:
    """Persisted operator settings. Passwords are deliberately excluded."""

    email: str = ""
    institution_id: str = "10870"
    study_code: str = "REB16236"
    output_folder: str = ""
    run_mode: str = "normal"
    range_start: str = ""
    range_end: str = ""
    show_browser: bool = True
    archived: bool = False
    skip_existing_study_folder: bool = False
    overwrite_existing_raw: bool = False
    debug_date_resolution: bool = False

    def __post_init__(self) -> None:
        if not self.output_folder:
            self.output_folder = default_output_folder()


def load_settings(path: Path | None = None) -> AppSettings:
    settings_path = path or (application_data_dir() / SETTINGS_FILENAME)
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
        allowed = {item.name for item in fields(AppSettings)}
        clean = {key: value for key, value in raw.items() if key in allowed}
        return AppSettings(**clean)
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        return AppSettings()


def save_settings(settings: AppSettings, path: Path | None = None) -> Path:
    """Save settings atomically. The dataclass has no password field."""
    settings_path = path or (application_data_dir() / SETTINGS_FILENAME)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = settings_path.with_suffix(settings_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(asdict(settings), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temporary_path, settings_path)
    return settings_path


def runtime_state_paths(output_folder: str, archived: bool = False) -> tuple[Path, Path]:
    """Keep state and logs next to the downloaded studies as one portable set."""
    runtime_folder = Path(output_folder) / "_ClariusDownloader"
    state_name = "last_sync_archived.json" if archived else "last_sync_active.json"
    return runtime_folder / state_name, runtime_folder / "logs"


def configure_bundled_browser() -> None:
    """Point Playwright at the Chromium folder included by PyInstaller."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    bundled_browser = bundle_root / "ms-playwright"
    if bundled_browser.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled_browser)
        os.environ["PLAYWRIGHT_SKIP_BROWSER_GC"] = "1"


def apply_engine_settings(core: Any, settings: AppSettings, password: str) -> None:
    """Map validated GUI values to the legacy downloader's runtime controls."""
    state_file, log_folder = runtime_state_paths(settings.output_folder, settings.archived)
    core.EMAIL = settings.email.strip()
    core.PASSWORD = password
    core.INSTITUTION_ID = settings.institution_id.strip()
    core.STUDY_CODE_FILTER = settings.study_code.strip()
    core.MASTER_FOLDER = settings.output_folder
    core.STATE_FILE = str(state_file)
    core.LOG_FOLDER = str(log_folder)
    core.SHOW_BROWSER = settings.show_browser
    core.ARCHIVED = settings.archived
    core.SKIP_EXISTING_STUDY_FOLDER = settings.skip_existing_study_folder
    core.OVERWRITE_EXISTING_RAW = settings.overwrite_existing_raw
    core.DEBUG_DATE_RESOLUTION = settings.debug_date_resolution
    core.EXAM_ENUMERATION_MODE = "auto"

    if settings.run_mode == "range":
        core.PATIENT_RANGE_START = int(settings.range_start)
        core.PATIENT_RANGE_END = int(settings.range_end)
        core.FORCE_PATIENT_RANGE = True
    else:
        core.PATIENT_RANGE_START = None
        core.PATIENT_RANGE_END = None
        core.FORCE_PATIENT_RANGE = False

    core.reset_cancel_request()


class ClariusDownloaderApp:
    def __init__(self, root: Any) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.core: Any | None = None
        self.stop_requested = threading.Event()
        self.close_requested = False
        self.settings = load_settings()

        self._configure_window()
        self._create_variables()
        self._build_interface()
        self._set_range_state()
        self._refresh_last_sync_label()
        self.root.after(100, self._drain_events)

    def _configure_window(self) -> None:
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("940x790")
        self.root.minsize(820, 690)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        style = self.ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("Subtitle.TLabel", foreground="#4b5563")
        style.configure("Section.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 7))
        style.configure("Status.TLabel", padding=(8, 5))

    def _create_variables(self) -> None:
        tk = self.tk
        s = self.settings
        self.email_var = tk.StringVar(value=s.email)
        self.password_var = tk.StringVar(value="")
        self.show_password_var = tk.BooleanVar(value=False)
        self.institution_var = tk.StringVar(value=s.institution_id)
        self.study_var = tk.StringVar(value=s.study_code)
        self.output_var = tk.StringVar(value=s.output_folder)
        self.run_mode_var = tk.StringVar(value=s.run_mode)
        self.range_start_var = tk.StringVar(value=s.range_start)
        self.range_end_var = tk.StringVar(value=s.range_end)
        self.show_browser_var = tk.BooleanVar(value=s.show_browser)
        self.archived_var = tk.BooleanVar(value=s.archived)
        self.skip_existing_var = tk.BooleanVar(value=s.skip_existing_study_folder)
        self.overwrite_var = tk.BooleanVar(value=s.overwrite_existing_raw)
        self.debug_date_var = tk.BooleanVar(value=s.debug_date_resolution)
        self.status_var = tk.StringVar(value="Ready")
        self.last_sync_var = tk.StringVar(value="Last successful sync: not found")

    def _build_interface(self) -> None:
        tk = self.tk
        ttk = self.ttk

        outer = ttk.Frame(self.root, padding=(18, 14, 18, 14))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(6, weight=1)

        ttk.Label(outer, text=APP_NAME, style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            outer,
            text="Download and track Clarius RAW archives without editing Python code.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))

        credentials = ttk.LabelFrame(
            outer, text="Clarius sign-in", style="Section.TLabelframe", padding=10
        )
        credentials.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        credentials.columnconfigure(1, weight=1)
        credentials.columnconfigure(3, weight=1)

        ttk.Label(credentials, text="Email").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.email_entry = ttk.Entry(credentials, textvariable=self.email_var)
        self.email_entry.grid(row=0, column=1, sticky="ew", padx=(0, 14))
        ttk.Label(credentials, text="Password").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.password_entry = ttk.Entry(
            credentials, textvariable=self.password_var, show="•"
        )
        self.password_entry.grid(row=0, column=3, sticky="ew", padx=(0, 8))
        ttk.Checkbutton(
            credentials,
            text="Show",
            variable=self.show_password_var,
            command=self._toggle_password,
        ).grid(row=0, column=4, sticky="w")
        ttk.Label(
            credentials,
            text="The password is used only for this run and is never saved.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))

        destination = ttk.LabelFrame(
            outer, text="Study and destination", style="Section.TLabelframe", padding=10
        )
        destination.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        destination.columnconfigure(1, weight=1)
        destination.columnconfigure(3, weight=1)

        ttk.Label(destination, text="Institution ID").grid(row=0, column=0, sticky="w")
        self.institution_entry = ttk.Entry(
            destination, textvariable=self.institution_var, width=16
        )
        self.institution_entry.grid(row=0, column=1, sticky="ew", padx=(8, 16))
        ttk.Label(destination, text="Study code").grid(row=0, column=2, sticky="w")
        self.study_entry = ttk.Entry(destination, textvariable=self.study_var, width=18)
        self.study_entry.grid(row=0, column=3, sticky="ew", padx=(8, 0))

        ttk.Label(destination, text="Download folder").grid(
            row=1, column=0, sticky="w", pady=(9, 0)
        )
        self.output_entry = ttk.Entry(destination, textvariable=self.output_var)
        self.output_entry.grid(
            row=1, column=1, columnspan=3, sticky="ew", padx=(8, 8), pady=(9, 0)
        )
        self.browse_button = ttk.Button(destination, text="Browse…", command=self._browse_output)
        self.browse_button.grid(row=1, column=4, sticky="e", pady=(9, 0))

        run_frame = ttk.LabelFrame(
            outer, text="Run mode", style="Section.TLabelframe", padding=10
        )
        run_frame.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        run_frame.columnconfigure(5, weight=1)
        self.normal_mode_button = ttk.Radiobutton(
            run_frame,
            text="Normal sync (new exams since last successful run)",
            variable=self.run_mode_var,
            value="normal",
            command=self._set_range_state,
        )
        self.normal_mode_button.grid(row=0, column=0, columnspan=6, sticky="w")
        self.range_mode_button = ttk.Radiobutton(
            run_frame,
            text="Patient range rerun",
            variable=self.run_mode_var,
            value="range",
            command=self._set_range_state,
        )
        self.range_mode_button.grid(row=1, column=0, sticky="w", pady=(7, 0))
        ttk.Label(run_frame, text="From P").grid(row=1, column=1, padx=(16, 4), pady=(7, 0))
        self.range_start_entry = ttk.Entry(
            run_frame, textvariable=self.range_start_var, width=8
        )
        self.range_start_entry.grid(row=1, column=2, pady=(7, 0))
        ttk.Label(run_frame, text="to P").grid(row=1, column=3, padx=(10, 4), pady=(7, 0))
        self.range_end_entry = ttk.Entry(run_frame, textvariable=self.range_end_var, width=8)
        self.range_end_entry.grid(row=1, column=4, pady=(7, 0))
        ttk.Label(run_frame, textvariable=self.last_sync_var, style="Subtitle.TLabel").grid(
            row=2, column=0, columnspan=5, sticky="w", pady=(8, 0)
        )
        self.import_state_button = ttk.Button(
            run_frame, text="Import prior state…", command=self._import_sync_state
        )
        self.import_state_button.grid(row=2, column=5, sticky="e", pady=(8, 0))

        options = ttk.LabelFrame(
            outer, text="Options", style="Section.TLabelframe", padding=10
        )
        options.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        for column in range(3):
            options.columnconfigure(column, weight=1)
        self.show_browser_check = ttk.Checkbutton(
            options, text="Show browser (recommended for first test)", variable=self.show_browser_var
        )
        self.show_browser_check.grid(row=0, column=0, sticky="w")
        self.archived_check = ttk.Checkbutton(
            options,
            text="Download archived exams",
            variable=self.archived_var,
            command=self._refresh_last_sync_label,
        )
        self.archived_check.grid(row=0, column=1, sticky="w")
        self.debug_check = ttk.Checkbutton(
            options, text="Detailed date-resolution log", variable=self.debug_date_var
        )
        self.debug_check.grid(row=0, column=2, sticky="w")
        self.skip_check = ttk.Checkbutton(
            options,
            text="Skip a study folder if it already contains any files",
            variable=self.skip_existing_var,
        )
        self.skip_check.grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.overwrite_check = ttk.Checkbutton(
            options,
            text="Replace existing RAW archives (dangerous)",
            variable=self.overwrite_var,
        )
        self.overwrite_check.grid(row=1, column=1, sticky="w", pady=(5, 0))

        log_frame = ttk.LabelFrame(
            outer, text="Run log", style="Section.TLabelframe", padding=(8, 6)
        )
        log_frame.grid(row=6, column=0, sticky="nsew", pady=(0, 8))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_frame,
            height=11,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
            background="#111827",
            foreground="#e5e7eb",
            insertbackground="#ffffff",
            relief="flat",
            padx=8,
            pady=7,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.tag_configure("warn", foreground="#fbbf24")
        self.log_text.tag_configure("error", foreground="#fca5a5")
        self.log_text.tag_configure("success", foreground="#86efac")
        self.log_text.tag_configure("muted", foreground="#9ca3af")

        actions = ttk.Frame(outer)
        actions.grid(row=7, column=0, sticky="ew")
        actions.columnconfigure(2, weight=1)
        self.start_button = ttk.Button(
            actions, text="Start download", style="Primary.TButton", command=self._start
        )
        self.start_button.grid(row=0, column=0, padx=(0, 7))
        self.stop_button = ttk.Button(
            actions, text="Stop safely", command=self._stop, state="disabled"
        )
        self.stop_button.grid(row=0, column=1, padx=(0, 7))
        ttk.Label(actions, textvariable=self.status_var, style="Status.TLabel").grid(
            row=0, column=2, sticky="ew"
        )
        self.open_button = ttk.Button(
            actions, text="Open download folder", command=self._open_output
        )
        self.open_button.grid(row=0, column=3)

        self.input_widgets = [
            self.email_entry,
            self.password_entry,
            self.institution_entry,
            self.study_entry,
            self.output_entry,
            self.browse_button,
            self.normal_mode_button,
            self.range_mode_button,
            self.range_start_entry,
            self.range_end_entry,
            self.import_state_button,
            self.show_browser_check,
            self.archived_check,
            self.debug_check,
            self.skip_check,
            self.overwrite_check,
        ]

    def _toggle_password(self) -> None:
        self.password_entry.configure(show="" if self.show_password_var.get() else "•")

    def _browse_output(self) -> None:
        from tkinter import filedialog

        selected = filedialog.askdirectory(
            parent=self.root,
            title="Choose the folder that will contain downloaded studies",
            initialdir=self.output_var.get() or str(Path.home()),
            mustexist=False,
        )
        if selected:
            self.output_var.set(selected)
            self._refresh_last_sync_label()

    def _import_sync_state(self) -> None:
        from tkinter import filedialog, messagebox

        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Choose an existing Clarius last_sync JSON file",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not selected:
            return
        try:
            payload = json.loads(Path(selected).read_text(encoding="utf-8"))
            value = str(payload["last_sync"])
            datetime.fromisoformat(value)
        except (OSError, KeyError, ValueError, json.JSONDecodeError, TypeError) as exc:
            messagebox.showerror(
                APP_NAME,
                f"That file is not a valid Clarius synchronization-state file:\n{exc}",
                parent=self.root,
            )
            return

        target, _ = runtime_state_paths(self.output_var.get(), self.archived_var.get())
        if target.exists() and not messagebox.askyesno(
            "Replace synchronization state",
            f"A state file already exists for the selected active/archived mode.\n\n"
            f"Current: {self.last_sync_var.get()}\n"
            f"Imported: {value}\n\nReplace it?",
            icon="warning",
            parent=self.root,
        ):
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_text(
                json.dumps({"last_sync": value}, indent=2), encoding="utf-8"
            )
            os.replace(temporary, target)
            self._refresh_last_sync_label()
            messagebox.showinfo(
                APP_NAME,
                "The prior successful-sync timestamp was imported for the selected "
                "active/archived mode.",
                parent=self.root,
            )
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not import the state file:\n{exc}", parent=self.root)

    def _set_range_state(self) -> None:
        state = "normal" if self.run_mode_var.get() == "range" else "disabled"
        if self.worker and self.worker.is_alive():
            state = "disabled"
        self.range_start_entry.configure(state=state)
        self.range_end_entry.configure(state=state)

    def _collect_settings(self) -> AppSettings:
        return AppSettings(
            email=self.email_var.get().strip(),
            institution_id=self.institution_var.get().strip(),
            study_code=self.study_var.get().strip(),
            output_folder=self.output_var.get().strip(),
            run_mode=self.run_mode_var.get(),
            range_start=self.range_start_var.get().strip(),
            range_end=self.range_end_var.get().strip(),
            show_browser=self.show_browser_var.get(),
            archived=self.archived_var.get(),
            skip_existing_study_folder=self.skip_existing_var.get(),
            overwrite_existing_raw=self.overwrite_var.get(),
            debug_date_resolution=self.debug_date_var.get(),
        )

    def _validate(self, settings: AppSettings, password: str) -> str | None:
        if not settings.email or "@" not in settings.email:
            return "Enter the Clarius account email."
        if not password:
            return "Enter the Clarius password. It will not be saved."
        if not settings.institution_id.isdigit():
            return "Institution ID must contain digits only."
        if not settings.study_code:
            return "Enter the study code used in Clarius patient identifiers."
        if not settings.output_folder:
            return "Choose a download folder."
        if settings.run_mode not in {"normal", "range"}:
            return "Choose a valid run mode."
        if settings.run_mode == "range":
            try:
                start = int(settings.range_start)
                end = int(settings.range_end)
            except ValueError:
                return "Patient range values must be whole numbers."
            if start < 0 or end < 0 or start > end:
                return "Patient range must have non-negative values with From ≤ To."
        return None

    def _start(self) -> None:
        from tkinter import messagebox

        if self.worker and self.worker.is_alive():
            return
        settings = self._collect_settings()
        password = self.password_var.get()
        validation_error = self._validate(settings, password)
        if validation_error:
            messagebox.showerror(APP_NAME, validation_error, parent=self.root)
            return

        output_path = Path(settings.output_folder).expanduser()
        try:
            output_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(
                APP_NAME,
                f"The download folder cannot be created or opened:\n{exc}",
                parent=self.root,
            )
            return
        settings.output_folder = str(output_path.resolve())
        self.output_var.set(settings.output_folder)

        if settings.overwrite_existing_raw:
            approved = messagebox.askyesno(
                "Confirm replacement",
                "Existing non-empty RAW archives may be replaced. Continue?",
                icon="warning",
                parent=self.root,
            )
            if not approved:
                return

        state_file, _ = runtime_state_paths(settings.output_folder, settings.archived)
        if settings.run_mode == "normal" and not state_file.exists():
            approved = messagebox.askyesno(
                "First normal synchronization",
                "No previous successful-sync record exists in this download folder. "
                "The first normal sync may inspect and download every matching study exam.\n\n"
                "For a small test, choose Patient range rerun instead. Continue?",
                icon="warning",
                parent=self.root,
            )
            if not approved:
                return

        try:
            save_settings(settings)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not save settings:\n{exc}", parent=self.root)
            return

        self.settings = settings
        self.close_requested = False
        self.stop_requested.clear()
        self._set_running_state(True)
        self._append_log("Starting downloader…", "muted")
        self.worker = threading.Thread(
            target=self._run_worker,
            args=(settings, password),
            daemon=True,
            name="clarius-download-worker",
        )
        self.worker.start()

    def _run_worker(self, settings: AppSettings, password: str) -> None:
        try:
            configure_bundled_browser()
            import clarius_downloader_core as core

            self.core = core
            apply_engine_settings(core, settings, password)
            if not hasattr(core, "_desktop_original_log"):
                core._desktop_original_log = core.log
            original_log = core._desktop_original_log

            def gui_log(message: str) -> None:
                original_log(message)
                self.events.put(("log", message))

            core.log = gui_log
            if self.stop_requested.is_set():
                core.request_cancel()
            core.main()
            self.events.put(("done", bool(core.CANCEL_REQUESTED)))
        except Exception as exc:
            detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            self.events.put(("error", (str(exc), detail)))
        finally:
            if self.core is not None:
                self.core.PASSWORD = ""
            password = ""

    def _stop(self) -> None:
        self.stop_requested.set()
        if self.core is not None:
            self.core.request_cancel()
        self.stop_button.configure(state="disabled")
        self.status_var.set("Stopping safely after the current network action…")
        self._append_log(
            "Stop requested. The current download will finish before the app stops.", "warn"
        )

    def _set_running_state(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for widget in self.input_widgets:
            widget.configure(state=state)
        self.start_button.configure(state="disabled" if running else "normal")
        self.open_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")
        self.status_var.set("Running…" if running else "Ready")
        if not running:
            self._set_range_state()

    def _append_log(self, message: str, tag: str | None = None) -> None:
        if tag is None:
            upper = message.upper()
            if "[ERROR]" in upper or "FAILED" in upper:
                tag = "error"
            elif "[WARN]" in upper or "[STOP]" in upper:
                tag = "warn"
            elif "[DOWNLOADED]" in upper or "COMPLETE" in upper or "SUCCESS" in upper:
                tag = "success"
            else:
                tag = ""
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {message}\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _drain_events(self) -> None:
        from tkinter import messagebox

        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "done":
                    stopped = bool(payload)
                    self.password_var.set("")
                    self._set_running_state(False)
                    self._refresh_last_sync_label()
                    if stopped:
                        self.status_var.set("Stopped safely; synchronization state was not advanced")
                        self._append_log("Downloader stopped safely.", "warn")
                    else:
                        self.status_var.set("Completed")
                        self._append_log("Run completed.", "success")
                        messagebox.showinfo(
                            APP_NAME,
                            "The Clarius download run completed. Review the run log for warnings.",
                            parent=self.root,
                        )
                    if self.close_requested:
                        self.root.destroy()
                        return
                elif kind == "error":
                    summary, detail = payload
                    self.password_var.set("")
                    self._set_running_state(False)
                    self.status_var.set("Failed — review the error and log")
                    self._append_log(f"ERROR: {summary}", "error")
                    self._write_crash_report(detail)
                    messagebox.showerror(
                        APP_NAME,
                        f"The run could not finish:\n\n{summary}\n\n"
                        "A crash report was saved in the app's log folder.",
                        parent=self.root,
                    )
                    if self.close_requested:
                        self.root.destroy()
                        return
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _write_crash_report(self, detail: str) -> None:
        try:
            _, log_folder = runtime_state_paths(
                self.output_var.get(), self.archived_var.get()
            )
            log_folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            (log_folder / f"crash_{stamp}.txt").write_text(detail, encoding="utf-8")
        except OSError:
            pass

    def _refresh_last_sync_label(self) -> None:
        try:
            state_file, _ = runtime_state_paths(
                self.output_var.get(), self.archived_var.get()
            )
            value = json.loads(state_file.read_text(encoding="utf-8"))["last_sync"]
            parsed = datetime.fromisoformat(value)
            display = parsed.strftime("%Y-%m-%d %H:%M:%S")
            self.last_sync_var.set(f"Last successful sync: {display}")
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            self.last_sync_var.set("Last successful sync: not found for this folder")

    def _open_output(self) -> None:
        from tkinter import messagebox

        path = Path(self.output_var.get()).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not open the folder:\n{exc}", parent=self.root)

    def _on_close(self) -> None:
        from tkinter import messagebox

        if self.worker and self.worker.is_alive():
            approved = messagebox.askyesno(
                "Stop and close",
                "A download run is active. Request a safe stop and close after the current "
                "network action finishes?",
                icon="warning",
                parent=self.root,
            )
            if approved:
                self.close_requested = True
                self._stop()
            return
        self.password_var.set("")
        self.root.destroy()


def self_test() -> int:
    """Run dependency-free checks useful before and after packaging."""
    required = {"main", "request_cancel", "reset_cancel_request", "process_exam"}
    if getattr(sys, "frozen", False):
        configure_bundled_browser()
        import clarius_downloader_core as core

        missing = sorted(name for name in required if not hasattr(core, name))
        if missing:
            raise RuntimeError(f"Packaged downloader engine is missing: {missing}")
        browser_root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
        if not browser_root.is_dir():
            raise RuntimeError("The packaged Chromium folder was not found.")
    else:
        core_path = Path(__file__).resolve().with_name("clarius_downloader_core.py")
        source = core_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(core_path))
        function_names = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        missing = sorted(required - function_names)
        if missing:
            raise RuntimeError(f"Downloader engine is missing required functions: {missing}")

        for node in tree.body:
            if isinstance(node, ast.Assign):
                names = {target.id for target in node.targets if isinstance(target, ast.Name)}
                if "PASSWORD" in names and isinstance(node.value, ast.Constant) and node.value.value:
                    raise RuntimeError("A password literal is embedded in the downloader engine.")

    with tempfile.TemporaryDirectory() as temporary_directory:
        settings_path = Path(temporary_directory) / "settings.json"
        original = AppSettings(email="operator@example.org", output_folder=temporary_directory)
        save_settings(original, settings_path)
        raw = settings_path.read_text(encoding="utf-8")
        if "password" in raw.lower():
            raise RuntimeError("The settings file unexpectedly contains a password field.")
        loaded = load_settings(settings_path)
        if loaded.email != original.email or loaded.output_folder != original.output_folder:
            raise RuntimeError("Settings round-trip failed.")

    print(f"{APP_NAME} {APP_VERSION} self-test: PASS")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    configure_bundled_browser()
    import tkinter as tk
    from tkinter import messagebox

    try:
        root = tk.Tk()
        ClariusDownloaderApp(root)
        root.mainloop()
        return 0
    except Exception as exc:
        try:
            messagebox.showerror(APP_NAME, f"The application could not start:\n{exc}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
