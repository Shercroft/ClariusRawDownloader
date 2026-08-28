"""Developer-only clinical date audit for ClariusRawDownloader.

Run this from the source folder to verify Clarius Cloud Exam Date resolution
without building/installing the desktop application and without downloading RAW
archives or changing last_sync.
"""

from pathlib import Path
import getpass

import clarius_downloader_core as core


def prompt_default(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def main() -> None:
    print("ClariusRawDownloader clinical date audit")
    print("NO RAW data will be downloaded. NO study folders will be renamed/created.")
    print("last_sync will NOT be changed.\n")

    core.EMAIL = input("Clarius email: ").strip()
    core.PASSWORD = getpass.getpass("Clarius password: ")
    core.INSTITUTION_ID = prompt_default("Institution ID", "10870")
    core.STUDY_CODE_FILTER = prompt_default("Study code", "REB16236")

    start = int(input("Patient range start (e.g. 47): ").strip())
    end_text = input(f"Patient range end [{start}]: ").strip()
    end = int(end_text) if end_text else start

    workspace = Path(__file__).resolve().parent / "_date_audit"
    core.MASTER_FOLDER = str(workspace / "no_downloads")
    core.STATE_FILE = str(workspace / "last_sync_audit.json")
    core.LOG_FOLDER = str(workspace / "logs")

    core.PATIENT_RANGE_START = min(start, end)
    core.PATIENT_RANGE_END = max(start, end)
    core.FORCE_PATIENT_RANGE = True
    core.DATE_AUDIT_ONLY = True
    core.SHOW_BROWSER = False
    core.DEBUG_DATE_RESOLUTION = True
    core.ARCHIVED = False
    core.SKIP_EXISTING_STUDY_FOLDER = False
    core.OVERWRITE_EXISTING_RAW = False

    print("\nStarting date audit...\n")
    core.main()
    print("\nAudit complete.")
    print(f"Log folder: {core.LOG_FOLDER}")
    print("Look for lines beginning with [DATE AUDIT].")


if __name__ == "__main__":
    main()
