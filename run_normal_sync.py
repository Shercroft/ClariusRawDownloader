"""Run ClariusRawDownloader NORMAL SYNC directly from Python source.

This does NOT use patient-range mode.
It reads the existing last_sync state and, after a completely successful run,
updates that state exactly like the GUI's Normal Sync mode.

Keep this file in the same folder as clarius_downloader_core.py.
"""

from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import sys

import clarius_downloader_core as core


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Clarius RAW Downloader normal sync from source."
    )
    parser.add_argument(
        "output_folder",
        help="Folder where downloaded patient/study folders are stored.",
    )
    parser.add_argument(
        "--state",
        default=None,
        help=(
            "Path to the existing last-sync JSON. If omitted, automatically "
            "looks for <output_folder>/_ClariusDownloader/last_sync.json and "
            "last_sync_active.json."
        ),
    )
    parser.add_argument("--institution", default="10870")
    parser.add_argument("--study-code", default="REB16236")
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Show the Chromium window while the sync runs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    output_folder = Path(args.output_folder).expanduser().resolve()
    runtime_folder = output_folder / "_ClariusDownloader"
    if args.state:
        state_file = Path(args.state).expanduser().resolve()
    else:
        legacy_state = runtime_folder / "last_sync.json"
        active_state = runtime_folder / "last_sync_active.json"
        existing = [p for p in (legacy_state, active_state) if p.is_file()]
        if len(existing) == 1:
            state_file = existing[0]
        elif len(existing) == 2:
            # Never guess between two state files; they may contain different
            # sync boundaries. Force an explicit --state in this rare case.
            raise SystemExit(
                "ERROR: both last_sync.json and last_sync_active.json exist.\n"
                "Choose the intended one explicitly with --state."
            )
        else:
            state_file = legacy_state

    log_folder = runtime_folder / "logs"

    # Do not silently create a 2000-01-01 state file during a test run.
    # We want to be certain this run is using the last_sync file you expect.
    if not state_file.is_file():
        raise SystemExit(
            "ERROR: no last_sync state file was found under:\n"
            f"  {runtime_folder}\n\n"
            "Expected last_sync.json or last_sync_active.json. If your state "
            "file is somewhere else, rerun with --state."
        )

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        last_sync = state["last_sync"]
    except Exception as exc:
        raise SystemExit(f"ERROR: Could not read {state_file}: {exc}") from exc

    canonical_keys = list(getattr(core, "EXAM_CLINICAL_DATE_KEYS", []))
    if not canonical_keys or canonical_keys[0] != "start_datetime":
        raise SystemExit(
            "ERROR: This runner is not using the v11 date-source core.\n"
            f"Loaded core: {getattr(core, '__file__', 'unknown')}\n"
            f"EXAM_CLINICAL_DATE_KEYS starts with: {canonical_keys[:5]}\n"
            "Replace clarius_downloader_core.py with the v11 file and retry."
        )

    print("\n=== Clarius NORMAL SYNC (source mode) ===")
    print(f"Core file     : {getattr(core, '__file__', 'unknown')}")
    print("Exam Date src : API start_datetime (canonical)")
    print(f"Output folder : {output_folder}")
    print(f"State file    : {state_file}")
    print(f"last_sync     : {last_sync}")
    print(f"Logs          : {log_folder}")
    print("Mode          : NORMAL SYNC (patient range OFF)")
    print("Archived      : False")
    print()

    email = input("Clarius email: ").strip()
    password = getpass.getpass("Clarius password: ")
    if not email or not password:
        raise SystemExit("ERROR: email and password are required.")

    # Match the GUI's active Normal Sync configuration.
    core.EMAIL = email
    core.PASSWORD = password
    core.INSTITUTION_ID = str(args.institution).strip()
    core.STUDY_CODE_FILTER = str(args.study_code).strip()

    core.MASTER_FOLDER = str(output_folder)
    core.STATE_FILE = str(state_file)
    core.LOG_FOLDER = str(log_folder)

    core.ARCHIVED = False
    core.EXAM_ENUMERATION_MODE = "auto"
    core.SHOW_BROWSER = bool(args.show_browser)

    # NORMAL MODE: absolutely no patient-range override.
    core.PATIENT_RANGE_START = None
    core.PATIENT_RANGE_END = None
    core.FORCE_PATIENT_RANGE = False

    # This is a real normal sync, not a date-only audit.
    core.DATE_AUDIT_ONLY = False

    # Preserve existing downloads and resume capture-by-capture.
    core.SKIP_EXISTING_STUDY_FOLDER = False
    core.OVERWRITE_EXISTING_RAW = False
    core.DEBUG_DATE_RESOLUTION = True

    core.reset_cancel_request()

    print("Starting normal sync...\n")
    core.main()

    # Show the state after the run so it is obvious whether it advanced.
    try:
        new_state = json.loads(state_file.read_text(encoding="utf-8"))
        print(f"\nState after run: {new_state.get('last_sync')}")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user. Check the log; do not manually advance last_sync.")
        sys.exit(130)
