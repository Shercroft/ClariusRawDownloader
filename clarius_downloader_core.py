"""
CLARIUS RAW DATA AUTOMATED DOWNLOADER
====================================

Purpose
-------
This script logs in to Clarius Cloud, finds exams for one institution and one
study, retrieves each exam's capture UUIDs, and downloads every available RAW
archive into the research drive.

This version intentionally uses Playwright only. It does NOT require the
third-party ``requests`` package.


OUTLINE / HOW THE SCRIPT WORKS
------------------------------

1. Configuration
   - Set the Clarius institution ID, study code, output folders, and run mode.
   - Normal automatic synchronization uses ``last_sync.json``.
   - A patient-range rerun ignores ``last_sync.json`` and is useful for testing,
     recovery, or reprocessing selected patient numbers.

2. Login
   - The script opens the Clarius login page with Playwright.
   - Credentials are read from environment variables when available.
   - Otherwise, the user is prompted in the terminal; the password is hidden.
   - The browser and Playwright API request context share the same cookies.

3. Exam discovery
   - In ``auto`` mode, the script first tries the faster institution-wide JSON
     API: ``/exams/?inst_id=<ID>&archived=false``.
   - If that response is unavailable or has an unrecognized structure, it
     automatically falls back to the HTML exams table.
   - The study filter keeps only patient identifiers containing
     ``STUDY_CODE_FILTER``.

4. Date resolution
   - The API exam list may omit the real exam date.
   - The script first checks nested exam JSON, then tries direct exam-detail
     routes, and finally inspects capture metadata for a plausible acquisition
     or creation timestamp used for folder naming.
   - The obsolete HTML table is attempted only once as a final compatibility
     fallback. Existing ``UNKDATE`` folders are renamed automatically when a
     real date is recovered.

5. New-exam filtering
   - Normal mode processes exams whose resolved date is later than the timestamp
     stored in ``last_sync.json``.
   - Patient-range mode processes only the requested patient numbers and does
     not update ``last_sync.json``.

6. Capture lookup
   - For each selected exam, the script calls
     ``/api/captures/<exam_id>/`` and follows all pagination links.
   - Each capture is identified by its UUID.
   - A UUID marker is stored in each image folder so that image-folder mapping
     remains stable on later runs.

7. RAW download
   - If ``has_raw_data`` is false, the script writes ``_NO_RAW.txt``.
   - Otherwise, it visits ``/raw/<capture_uuid>/`` in the authenticated browser.
   - Clarius redirects the browser to a short-lived S3 URL.
   - Every retry starts from the Clarius URL again, so an expired S3 link is not
     reused.
   - The file is first saved as ``.part`` and is renamed to ``.tar`` only after
     a successful, non-empty download.

8. Resume and overwrite behavior
   - By default, the script resumes capture-by-capture.
   - Existing non-empty TAR files are skipped.
   - Set ``OVERWRITE_EXISTING_RAW = True`` only when intentional replacement is
     required.

9. State update
   - In normal mode, ``last_sync.json`` is updated to the time at which the run
     started, but only when all selected exams complete without errors.
   - If any selected download fails, the state is not advanced, allowing the
     failed work to be retried on the next run.
   - Patient-range mode never changes ``last_sync.json``.




RECOMMENDED RUN MODES
---------------------

A. Small first test (This is an example of only download of certain ranges)

    SHOW_BROWSER = True
    PATIENT_RANGE_START = 149
    PATIENT_RANGE_END = 149
    FORCE_PATIENT_RANGE = True
    SKIP_EXISTING_STUDY_FOLDER = False
    OVERWRITE_EXISTING_RAW = False

This processes only patient 149, preserves existing TAR files, and does not
change ``last_sync.json``.

B. Normal automatic synchronization

    SHOW_BROWSER = False
    PATIENT_RANGE_START = None
    PATIENT_RANGE_END = None
    FORCE_PATIENT_RANGE = False
    SKIP_EXISTING_STUDY_FOLDER = False
    OVERWRITE_EXISTING_RAW = False

This processes study exams later than the timestamp in ``last_sync.json``.

C. Resume an interrupted patient range

    PATIENT_RANGE_START = 100
    PATIENT_RANGE_END = 150
    FORCE_PATIENT_RANGE = True
    SKIP_EXISTING_STUDY_FOLDER = False
    OVERWRITE_EXISTING_RAW = False

Completed TAR files are skipped; missing or failed captures are retried.

D. Re-download and replace existing TAR files

    OVERWRITE_EXISTING_RAW = True

Use this only when replacement is deliberate. Return it to ``False`` after the
special rerun.


IMPORTANT CONFIGURATION FIELDS
------------------------------

``INSTITUTION_ID``
    Clarius organization identifier. It normally matches the number in the
    exams-page URL, for example ``https://cloud.clarius.com/10870/exams/``.

``STUDY_CODE_FILTER``
    Text that must appear in the patient identifier, such as ``REB16236``.

``MASTER_FOLDER``
    Parent folder where dated study folders and image subfolders are created.

``STATE_FILE``
    JSON file storing the last successful normal-sync timestamp.

``ARCHIVED``
    ``False`` retrieves active exams; ``True`` retrieves archived exams.
    Run active and archived exams separately.

``EXAM_ENUMERATION_MODE``
    ``auto`` is recommended. ``api`` requires the JSON API. ``html`` forces the
    slower webpage-table method.

``DEBUG_DUMP_JSON``
    When true, API JSON is written under ``LOG_FOLDER/debug_json`` to help adapt
    the script if Clarius changes field names. Signed S3 URLs are not logged.


OUTPUT STRUCTURE
----------------

A typical result is:

    Automated NEW Exam Downloads/
        P149_TR_02_Aug_07-25-REB16236-149/
            P149_Image_1/
                _CAPTURE_UUID.txt
                <capture-uuid>.tar
            P149_Image_2/
                _CAPTURE_UUID.txt
                _NO_RAW.txt

Marker files:

``_CAPTURE_UUID.txt``
    Records which Clarius capture belongs to an image folder.

``_NO_RAW.txt``
    Clarius reported no RAW data, or a download failed. Read the marker content
    to distinguish the cause.

``_NO_CAPTURES.txt``
    The capture endpoint returned no captures for an exam.

``_CAPTURE_ERROR.txt``
    One or more capture objects were malformed, for example a missing UUID.


SAFETY NOTES
------------

- Do not hard-code or commit Clarius credentials.
- Do not share signed S3 URLs; they function as temporary bearer links.
- Leave ``OVERWRITE_EXISTING_RAW`` false during normal operation.
- Check the daily log after every large run.
- If Clarius changes its website or JSON fields, first set
  ``DEBUG_DUMP_JSON = True`` and test a very small patient range.
- Date strings such as ``08/07/2025`` are interpreted as North American
  ``MM/DD/YYYY`` by the current parser: August 7, 2025.


MAINTENANCE PRINCIPLE
---------------------

The code is divided into clearly labelled sections. Before changing behavior,
identify the relevant section and keep changes local:

- Configuration: constants only.
- Date parser: accepted date formats.
- API helpers: JSON and pagination behavior.
- HTML fallback: webpage selectors and missing-date recovery.
- Capture mapping: stable image-folder assignment.
- RAW download: browser download and retry behavior.
- ``process_exam``: one-exam workflow.
- ``main``: whole-run orchestration and state update.
"""

import getpass
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

# =====================================================================
# 1. USER CONFIGURATION
# =====================================================================
# Most routine handoffs should require edits only in this section and in the
# RANGE RERUN MODE section below. Do not change API field lists or processing
# functions unless Clarius has changed its site/API structure.

# Root address of the Clarius Cloud service.
BASE_URL = "https://cloud.clarius.com"

# Organization/institution identifier. Confirm it from the institution exams
# URL. For example, /10870/exams/ means the institution ID is 10870.
INSTITUTION_ID = "10870"

# Only patient identifiers containing this text are processed. Other studies
# under the same institution are fetched during enumeration but ignored.
STUDY_CODE_FILTER = "REB16236"

# Credentials must never be embedded in source code or in a packaged executable.
# The GUI supplies these values for the current run. Command-line maintainers may
# alternatively provide CLARIUS_EMAIL and CLARIUS_PASSWORD environment variables.
EMAIL = os.environ.get("CLARIUS_EMAIL", "")
PASSWORD = os.environ.get("CLARIUS_PASSWORD", "")


# Output root. One study folder is created per patient/exam/visit. 
MASTER_FOLDER = r"Z:\#POCUS KIDNEY TRIAL DATA\Automated Downloading (Weiyou)\Automated NEW Exam Downloads"

# Normal-mode state file. It contains one key, "last_sync", with an ISO date.
# Do not delete or manually advance it unless intentionally resetting the sync.
STATE_FILE = r"Z:\#POCUS KIDNEY TRIAL DATA\Automated Downloading (Weiyou)\last_sync.json"

# Daily text logs and optional debug JSON files are stored here.
LOG_FOLDER = r"Z:\#POCUS KIDNEY TRIAL DATA\Automated Downloading (Weiyou)\logs"

NO_RAW_MARKER = "_NO_RAW.txt"
NO_CAPTURES_MARKER = "_NO_CAPTURES.txt"
CAPTURE_ERROR_MARKER = "_CAPTURE_ERROR.txt"
CAPTURE_UUID_MARKER = "_CAPTURE_UUID.txt"

# False = active exams. True = archived exams only.
ARCHIVED = False

# "auto": try the fast institution-wide API first, then fall back to the
#         exams webpage if that API response is unavailable or unrecognized.
# "api":  require API enumeration; stop if it fails.
# "html": use only the exams webpage for enumeration.
EXAM_ENUMERATION_MODE = "auto"

# Helpful for checking unknown API response structures. JSON is written to
# LOG_FOLDER/debug_json; signed S3 download URLs are never written there.
DEBUG_DUMP_JSON = False

# Default False is safer: an interrupted study resumes capture-by-capture.
# Set True only to reproduce the old behavior of skipping any non-empty study.
SKIP_EXISTING_STUDY_FOLDER = False

# Keep False for normal use. True deliberately replaces existing RAW archives.
OVERWRITE_EXISTING_RAW = False

# If has_raw_data is missing rather than explicitly false, try /raw/<uuid>/.
TRY_RAW_WHEN_FLAG_MISSING = True

# Safer state behavior: when the exam metadata does not say zero captures,
# an empty capture response is treated as an error and last_sync is not advanced.
EMPTY_CAPTURES_WITH_UNKNOWN_COUNT_IS_ERROR = True

# When the institution-wide exams API omits the date, try to open the exam
# detail page and read "Exam Date". The code first tries a direct URL based on
# exam_id. It only tries the old HTML exams table once as a final fallback.
HTML_DETAIL_DATE_FALLBACK = True

# Optional: paste the current URL pattern from a manually opened exam page.
# Keep {exam_id} literally in the string. Example only:
# EXAM_DETAIL_URL_TEMPLATE = "https://cloud.clarius.com/10870/exams/{exam_id}/"
# Leave as None to let the script try common URL patterns automatically.
EXAM_DETAIL_URL_TEMPLATE = None

# Important safety control for the updated Clarius UI. If the old table cannot
# be found, disable that fallback for the rest of the run instead of waiting
# 10 seconds again for every patient.
DISABLE_HTML_TABLE_FALLBACK_AFTER_FIRST_FAILURE = True

# Rename an existing ..._UNKDATE-... folder after the real date is found.
AUTO_RENAME_UNKDATE_FOLDER = True

# Also repair a uniquely matched study folder whose embedded date is wrong.
# This specifically fixes folders created by older builds that used an
# uploaded_at/download-day timestamp (for example Aug_28) instead of the Cloud
# Exam Date (for example Aug_21). The patient/exam/visit prefix must match
# uniquely; ambiguous multiple folders are never renamed automatically.
AUTO_RENAME_MISMATCHED_DATE_FOLDER = True

# Additional date fallbacks for the updated Clarius UI/API.
# 1) Recursively inspect nested exam JSON fields for date-like values.
# 2) If the exam list still has no trustworthy date, inspect capture metadata.
#
# IMPORTANT: normal sync must NEVER treat an unreadable date as automatically
# new. That behavior can redownload old exams. Nested/capture timestamps with a
# sufficiently specific date key are therefore allowed to decide the
# last_sync boundary when the top-level API/detail page omits its date.
USE_NESTED_JSON_DATE_FALLBACK = True
USE_CAPTURE_DATE_FOR_FOLDER_NAME = True
USE_CAPTURE_DATE_FOR_SYNC_FILTER = True
# Only clinically meaningful keys (performed/study/capture/acquired/exam date)
# may decide normal sync or folder naming when the labelled Cloud Exam Date is
# unavailable. Generic created/uploaded timestamps are intentionally excluded.
MIN_SYNC_DATE_FALLBACK_SCORE = 100
MIN_FOLDER_DATE_FALLBACK_SCORE = 100

# Defense in depth for client-rendered pages. A bad DOM selector can sometimes
# land on the page's live/current timestamp. If that timestamp is within this
# many minutes of the downloader clock but conflicts strongly with a trusted
# JSON date, reject it rather than making an old exam look newly created.
DETAIL_PAGE_CLOCK_GUARD_MINUTES = 5
DETAIL_PAGE_CONFLICT_DAYS = 1

# When True, log which JSON key/path supplied a fallback date. This is useful
# for the first small-range test and can be turned off after validation.
DEBUG_DATE_RESOLUTION = True

# =====================================================================
# 2. BROWSER / PLAYWRIGHT REQUEST CONTROLS
# =====================================================================

# True is recommended during a first test because the operator can watch login,
# navigation, and download behavior. False is faster and suitable for routine use.
SHOW_BROWSER = False

# Optional delay after Playwright actions. Keep at zero unless debugging UI timing.
SLOW_MO_MS = 0

# General webpage selector timeout and separate login timeout, in milliseconds.
DEFAULT_TIMEOUT_MS = 10000
LOGIN_TIMEOUT_MS = 30000

# JSON API calls can take time because institution/capture lists are paginated.
API_TIMEOUT_MS = 120000

# RAW TAR archives may be large. This permits up to ten minutes per browser
# download, matching the approximate lifetime of Clarius's signed S3 URL.
RAW_DOWNLOAD_TIMEOUT_MS = 600000

# Each retry returns to /raw/<uuid>/ to obtain a new signed S3 redirect.
RAW_DOWNLOAD_ATTEMPTS = 3
RAW_RETRY_DELAY_SECONDS = 2

# Retained as a descriptive size constant for maintainers. Browser downloads are
# handled by Playwright rather than manually streamed in Python.
DOWNLOAD_CHUNK_SIZE = 1024 * 1024

# =====================================================================
# 3. RANGE RERUN MODE
# =====================================================================
# NORMAL MODE:
#   Leave both values as None. The script uses last_sync.json and updates it only
#   after a completely successful run.
#
# RANGE MODE:
#   Set both values to patient numbers. Example: 1 through 50. Range mode ignores
#   last_sync.json and never updates it. This is the safest mode for testing or
#   repairing a subset of patients.
PATIENT_RANGE_START = None
PATIENT_RANGE_END = None

# True means "actively inspect/reprocess patients in the selected range." It
# bypasses whole-study-folder skipping, but existing TAR archives are still
# protected unless OVERWRITE_EXISTING_RAW is also True.
FORCE_PATIENT_RANGE = False

# The GUI sets this flag when the operator requests a graceful stop. It is
# checked between exams and captures; an in-progress network download is allowed
# to finish so that a partial TAR is never presented as a completed archive.
CANCEL_REQUESTED = False


def request_cancel():
    global CANCEL_REQUESTED
    CANCEL_REQUESTED = True


def reset_cancel_request():
    global CANCEL_REQUESTED
    CANCEL_REQUESTED = False

# =====================================================================
# API FIELD CANDIDATES
# =====================================================================

EXAM_LIST_ITEM_KEYS = ["results", "exams", "data", "items"]
CAPTURE_LIST_ITEM_KEYS = ["results", "captures", "data", "items"]

EXAM_ID_KEYS = ["id", "exam_id", "pk"]
EXAM_PATIENT_KEYS = [
    "patient_msp",
    "patient_id",
    "patientId",
    "patient_identifier",
    "exam_name",
    "name",
]
EXAM_STATUS_KEYS = ["status", "exam_status"]
EXAM_CAPTURE_COUNT_KEYS = ["number_of_captures", "capture_count", "num_captures"]
# Keep the clinical Exam Date separate from upload/creation timestamps.
# Folder names and the normal-sync boundary should use the clinical exam date
# whenever it is available. Upload/created timestamps are only fallbacks.
EXAM_CLINICAL_DATE_KEYS = [
    "exam_date",
    "examDate",
    "study_date",
    "studyDate",
    "acquired_at",
    "acquiredAt",
    "acquisition_date",
    "acquisitionDate",
    "performed_at",
    "performedAt",
]

EXAM_UPLOAD_DATE_KEYS = [
    "uploaded_at",
    "uploadedAt",
    "upload_date",
    "uploadDate",
    "uploaded",
    "created_at",
    "createdAt",
    "created",
    "date_created",
    "dateCreated",
    "completed_at",
    "completedAt",
]
EXAM_DETAIL_URL_KEYS = ["url", "detail_url", "exam_url", "href"]

CAPTURE_UUID_KEYS = ["uuid", "capture_uuid", "captureUuid"]
CAPTURE_RAW_KEYS = ["has_raw_data", "hasRawData", "has_raw"]

# =====================================================================
# LOGGING / STATE
# =====================================================================


def ensure_directories():
    os.makedirs(MASTER_FOLDER, exist_ok=True)
    os.makedirs(LOG_FOLDER, exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    if sys.stdout is not None:
        print(line)
    with open(
        os.path.join(LOG_FOLDER, f"sync_{datetime.now().strftime('%Y-%m-%d')}.txt"),
        "a",
        encoding="utf-8",
    ) as f:
        f.write(line + "\n")


def ensure_state():
    """Create last_sync.json on the first run using a deliberately old date."""
    if not os.path.exists(STATE_FILE):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_sync": "2000-01-01T00:00:00"}, f)
        log("Created last_sync.json")


def load_last_sync():
    """Return the ISO timestamp stored after the most recent successful run."""
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)["last_sync"]


def save_last_sync(ts):
    """Persist the run-start timestamp after a fully successful normal run."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_sync": ts}, f, indent=2)
    log(f"Updated last_sync.json to {ts}")


def dump_debug_json(name, page_num, payload):
    if not DEBUG_DUMP_JSON:
        return

    debug_folder = os.path.join(LOG_FOLDER, "debug_json")
    os.makedirs(debug_folder, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    path = os.path.join(debug_folder, f"{safe_name}_page_{page_num}.json")

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
        log(f"[DEBUG] Wrote API JSON to {path}")
    except Exception as e:
        log(f"[WARN] Could not write debug JSON {path}: {e}")


# =====================================================================
# DATE PARSER
# =====================================================================


def normalize_clarius_datetime_text(text):
    if not text:
        return None

    text = str(text)
    text = " ".join(text.split())
    text = text.replace("\u00a0", " ").replace("\u2009", " ").replace("\u202f", " ")
    text = re.sub(r"\ba\.?\s*m\.?\b", "AM", text, flags=re.IGNORECASE)
    text = re.sub(r"\bp\.?\s*m\.?\b", "PM", text, flags=re.IGNORECASE)
    text = text.replace(".", "")
    return " ".join(text.split()).strip()


def make_naive_local(dt):
    """Convert an aware datetime to local system time, then remove tzinfo."""
    if dt is not None and dt.tzinfo is not None:
        return dt.astimezone().replace(tzinfo=None)
    return dt


def try_parse_date(text):
    if not text or text == "N/A":
        return None

    raw = str(text).strip()

    # Fast path for JSON ISO-8601 timestamps, including a trailing Z.
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return make_naive_local(parsed)
    except (TypeError, ValueError):
        pass

    text = normalize_clarius_datetime_text(raw)
    if not text or text == "N/A":
        return None

    has_time = any(token in text for token in [":", "AM", "PM"])
    text_with_time = text if has_time else text + " 12:00 PM"

    fmts = [
        "%d %b %Y %I:%M %p",
        "%d %b %Y %H:%M",
        "%b %d %Y %I:%M %p",
        "%b %d %Y %H:%M",
        "%b %d, %Y %I:%M %p",
        "%b %d, %Y %H:%M",
        "%d %b %Y",
        "%b %d, %Y",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y, %I:%M %p",
        "%m/%d/%y %I:%M %p",
        "%m/%d/%y, %I:%M %p",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d %B %Y %I:%M %p",
        "%d %B %Y %H:%M",
        "%B %d %Y %I:%M %p",
        "%B %d %Y %H:%M",
        "%B %d, %Y %I:%M %p",
        "%B %d, %Y %H:%M",
        "%d %B %Y",
        "%B %d, %Y",
        "%b %d, %Y, %I:%M %p",
        "%b %d, %Y, %H:%M",
        "%B %d, %Y, %I:%M %p",
        "%B %d, %Y, %H:%M",
        "%b %d, %Y %I %p",
        "%b %d, %Y, %I %p",
        "%B %d, %Y %I %p",
        "%B %d, %Y, %I %p",
        "%d %b %Y %I %p",
        "%d %B %Y %I %p",
        "%b %d %Y %I %p",
        "%B %d %Y %I %p",
        "%d %b, %Y %I:%M %p",
        "%d %b, %Y %H:%M",
        "%d %B, %Y %I:%M %p",
        "%d %B, %Y %H:%M",
        "%d %b, %Y %I %p",
        "%d %B, %Y %I %p",
        "%m/%d/%Y %H:%M",
    ]

    for candidate in [text, text_with_time]:
        for fmt in fmts:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                pass

    return None


def extract_date_candidates_from_text(text):
    if not text:
        return []

    text = " ".join(str(text).split())
    patterns = [
        r"[A-Za-z]{3,9}\.? \d{1,2}, \d{4},? \d{1,2}:\d{2} ?[ap]\.?m\.?",
        r"[A-Za-z]{3,9}\.? \d{1,2}, \d{4},? \d{1,2} ?[ap]\.?m\.?",
        r"\d{1,2} [A-Za-z]{3,9} \d{4} \d{1,2}:\d{2} ?[APMapm\. ]+",
        r"[A-Za-z]{3,9}\.? \d{1,2}, \d{4}",
        r"\d{1,2} [A-Za-z]{3,9} \d{4}",
        r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?",
        r"\d{1,2}/\d{1,2}/\d{2,4}(?:,? \d{1,2}:\d{2}(?: ?[APMapm]{2})?)?",
    ]

    found = []
    for pattern in patterns:
        found.extend(re.findall(pattern, text))

    output = []
    seen = set()
    for value in found:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def try_parse_any_date_strings(strings):
    for value in strings:
        parsed = try_parse_date(value)
        if parsed is not None:
            return parsed
    return None


# ---------------------------------------------------------------------
# Generic nested-JSON date discovery
# ---------------------------------------------------------------------
# The institution-wide exams endpoint may omit Exam Date at the top level but
# still include it inside a nested object. Capture objects may also contain an
# acquisition/creation timestamp. These helpers inspect only date-like keys and
# reject expiry/signature timestamps so temporary S3 metadata is never used.

_DATE_EXCLUDE_WORDS = {
    "expire", "expires", "expiry", "signature", "signed", "token",
    "amz", "cache", "ttl", "valid_until", "validuntil",
}

_DATE_KEY_WEIGHTS = {
    "exam_date": 120, "examdate": 120,
    "acquired_at": 115, "acquiredat": 115, "acquisition_date": 115,
    "acquisitiondate": 115, "capture_date": 110, "capturedate": 110,
    "captured_at": 110, "capturedat": 110,
    "study_date": 105, "studydate": 105,
    "performed_at": 100, "performedat": 100,
    "created_at": 80, "createdat": 80, "created": 75,
    "uploaded_at": 70, "uploadedat": 70, "upload_date": 70,
    "uploaddate": 70, "uploaded": 65,
    "completed_at": 60, "completedat": 60,
    "timestamp": 50, "datetime": 50, "date": 40, "time": 20,
}


def _date_key_score(path):
    path_text = ".".join(str(part) for part in path).lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", path_text).strip("_")

    if any(word in normalized for word in _DATE_EXCLUDE_WORDS):
        return -1

    score = -1
    for key, weight in _DATE_KEY_WEIGHTS.items():
        if key in normalized:
            score = max(score, weight)
    return score


def _plausible_clinical_date(dt):
    if dt is None:
        return False
    current_year = datetime.now().year
    return 2010 <= dt.year <= current_year + 1


def find_date_candidates_in_json(payload, max_depth=8):
    """Return scored date candidates as (score, datetime, path, raw_value)."""
    candidates = []

    def walk(value, path, depth):
        if depth > max_depth:
            return

        if isinstance(value, dict):
            for key, child in value.items():
                child_path = path + [str(key)]
                score = _date_key_score(child_path)
                if score >= 0 and not isinstance(child, (dict, list, tuple)):
                    parsed = try_parse_date(child)
                    if _plausible_clinical_date(parsed):
                        candidates.append((score, parsed, ".".join(child_path), child))
                walk(child, child_path, depth + 1)
            return

        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                walk(child, path + [str(index)], depth + 1)

    walk(payload, [], 0)
    return candidates


def best_date_from_json(payload, prefer_earliest_on_tie=False):
    """Return (datetime, path, raw_value, score) or (None, None, None, None)."""
    candidates = find_date_candidates_in_json(payload)
    if not candidates:
        return None, None, None, None

    best_score = max(item[0] for item in candidates)
    tied = [item for item in candidates if item[0] == best_score]
    tied.sort(key=lambda item: item[1], reverse=not prefer_earliest_on_tie)
    score, dt, path, raw = tied[0]
    return dt, path, raw, score


def best_date_from_captures(captures):
    """Return the earliest highest-confidence capture date across all captures."""
    combined = []
    for index, capture in enumerate(captures, start=1):
        for score, dt, path, raw in find_date_candidates_in_json(capture):
            combined.append((score, dt, f"capture[{index}].{path}", raw))

    if not combined:
        return None, None, None, None

    best_score = max(item[0] for item in combined)
    tied = [item for item in combined if item[0] == best_score]
    tied.sort(key=lambda item: item[1])
    score, dt, path, raw = tied[0]
    return dt, path, raw, score


# =====================================================================
# FOLDER NAMING / RANGE HELPERS
# =====================================================================

MONTH_MAP = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}


def build_study_folder(patient_id, exam_date_obj):
    """Build the laboratory's expected study-folder name from a patient ID.

    Example patient ID:
        REB16236_149_TR_02

    Example output with a known date:
        P149_TR_02_Aug_07-25-REB16236-149

    When no date is available, UNKDATE is used temporarily and may later be
    replaced by get_or_create_study_path().
    """
    pid = (patient_id or "").strip()

    study_code = "UNK"
    patient_num = "000"
    examtype = "EXAM"
    visit = "00"

    if "_" in pid:
        parts = pid.split("_")
        study_code = parts[0] if len(parts) > 0 else "UNK"
        patient_num = parts[1] if len(parts) > 1 else "000"
        examtype = parts[2] if len(parts) > 2 else "EXAM"
        visit = parts[3] if len(parts) > 3 else "00"
    elif "-" in pid:
        left, right = pid.split("-", 1)
        study_code = left or "UNK"
        patient_num = right or "000"

    patient_num_digits = re.sub(r"\D+", "", patient_num) or patient_num
    visit = visit.zfill(2)
    tail = f"{study_code}-{patient_num_digits}"

    if exam_date_obj is None:
        return f"P{patient_num_digits}_{examtype}_{visit}_UNKDATE-{tail}"

    month = MONTH_MAP[exam_date_obj.month]
    day = f"{exam_date_obj.day:02d}"
    year2 = str(exam_date_obj.year)[-2:]
    return f"P{patient_num_digits}_{examtype}_{visit}_{month}_{day}-{year2}-{tail}"


def range_mode_enabled():
    return PATIENT_RANGE_START is not None and PATIENT_RANGE_END is not None


def extract_patient_num(patient_id):
    if not patient_id:
        return None

    pattern = rf"{re.escape(STUDY_CODE_FILTER)}[_-](\d+)"
    match = re.search(pattern, str(patient_id), flags=re.IGNORECASE)
    if not match:
        return None

    try:
        return int(match.group(1))
    except ValueError:
        return None


def extract_patient_number_text(patient_id):
    number = extract_patient_num(patient_id)
    if number is not None:
        match = re.search(
            rf"{re.escape(STUDY_CODE_FILTER)}[_-](\d+)",
            str(patient_id),
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1)

    parts = re.split(r"[_-]", (patient_id or "").strip())
    if len(parts) >= 2 and parts[1]:
        digits = re.sub(r"\D+", "", parts[1])
        return digits or parts[1]
    return "000"


def in_patient_range(patient_id):
    if not range_mode_enabled():
        return True

    number = extract_patient_num(patient_id)
    if number is None:
        return False

    low = min(PATIENT_RANGE_START, PATIENT_RANGE_END)
    high = max(PATIENT_RANGE_START, PATIENT_RANGE_END)
    return low <= number <= high


def should_force_exam(patient_id):
    return range_mode_enabled() and FORCE_PATIENT_RANGE and in_patient_range(patient_id)


def is_study_patient(patient_id):
    return bool(patient_id) and STUDY_CODE_FILTER.lower() in str(patient_id).lower()


def make_patient_prefix(patient_id):
    pid = (patient_id or "").strip()

    if "_" in pid:
        parts = pid.split("_")
        patient_num = re.sub(r"\D+", "", parts[1]) if len(parts) > 1 else "000"
        examtype = parts[2] if len(parts) > 2 else "EXAM"
        visit = parts[3].zfill(2) if len(parts) > 3 else "00"
        return f"P{patient_num}_{examtype}_{visit}_"

    if "-" in pid:
        _, right = pid.split("-", 1)
        patient_num = re.sub(r"\D+", "", right) or "000"
        return f"P{patient_num}_"

    return None


def find_existing_study_folder(master_folder, patient_id):
    prefix = make_patient_prefix(patient_id)
    if not prefix:
        return None

    try:
        matches = []
        for name in os.listdir(master_folder):
            full_path = os.path.join(master_folder, name)
            if os.path.isdir(full_path) and name.startswith(prefix):
                matches.append(full_path)
        if matches:
            matches.sort()
            return matches[0]
    except Exception as e:
        log(f"[WARN] Could not search existing study folders for {patient_id}: {e}")

    return None


def find_existing_study_folders(master_folder, patient_id):
    prefix = make_patient_prefix(patient_id)
    if not prefix:
        return []

    matches = []
    try:
        for name in os.listdir(master_folder):
            full_path = os.path.join(master_folder, name)
            if os.path.isdir(full_path) and name.startswith(prefix):
                matches.append(full_path)
    except Exception as e:
        log(f"[WARN] Could not search existing study folders for {patient_id}: {e}")
    return sorted(matches)


def get_or_create_study_path(master_folder, patient_id, folder_date):
    """Return the path for one patient/exam/visit, repairing stale date names.

    If a trustworthy clinical date is known, the desired folder name is the
    canonical name. A *single* existing folder with the same patient/exam/visit
    prefix is renamed to that canonical name when necessary. This repairs
    folders produced by older versions that used upload/download timestamps.

    If multiple mismatched folders exist, the function refuses to guess rather
    than silently reusing the wrong folder.
    """
    desired_name = build_study_folder(patient_id, folder_date)
    desired_path = os.path.join(master_folder, desired_name)
    matches = find_existing_study_folders(master_folder, patient_id)

    if os.path.isdir(desired_path):
        return desired_path

    # With a known clinical date, a single same-visit folder is safe to repair.
    if folder_date is not None and len(matches) == 1:
        old_path = matches[0]
        old_name = os.path.basename(old_path)
        is_unkdate = "_UNKDATE-" in old_name
        may_rename = (
            (is_unkdate and AUTO_RENAME_UNKDATE_FOLDER)
            or (not is_unkdate and AUTO_RENAME_MISMATCHED_DATE_FOLDER)
        )
        if may_rename and os.path.normcase(old_path) != os.path.normcase(desired_path):
            try:
                os.rename(old_path, desired_path)
                reason = "UNKDATE" if is_unkdate else "mismatched date"
                log(f"[RENAMED] Corrected {reason} folder: {old_path} -> {desired_path}")
                return desired_path
            except Exception as e:
                raise RuntimeError(
                    f"Found one existing folder for {patient_id}, but it could not "
                    f"be renamed to the verified Exam Date path. Existing={old_path}; "
                    f"desired={desired_path}; error={e}"
                ) from e

    if folder_date is not None and len(matches) > 1:
        raise RuntimeError(
            f"Multiple existing folders match {patient_id}, but none has the "
            f"verified Exam Date name {desired_name}. Refusing to choose or rename "
            f"one automatically: {matches}"
        )

    # When the clinical date is still unknown, reuse a unique existing folder so
    # an interrupted download can resume without creating a second UNKDATE copy.
    if folder_date is None and len(matches) == 1:
        log(f"[INFO] Reusing existing study folder while Exam Date is unknown: {matches[0]}")
        return matches[0]

    if folder_date is None and len(matches) > 1:
        raise RuntimeError(
            f"Multiple existing folders match {patient_id} while the clinical "
            f"Exam Date is unknown; refusing to choose one automatically: {matches}"
        )

    os.makedirs(desired_path, exist_ok=True)
    log(f"Study folder: {desired_path}")
    return desired_path


def folder_has_any_content(study_path):
    if not os.path.isdir(study_path):
        return False

    for _, dirs, files in os.walk(study_path):
        if dirs or files:
            return True
    return False


def remove_marker_if_present(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        log(f"[WARN] Could not remove marker {path}: {e}")


# =====================================================================
# GENERIC API / AUTHENTICATION HELPERS
# =====================================================================


def validate_config():
    """Collect credentials and reject unsupported configuration values early."""
    global EMAIL, PASSWORD

    # Environment variables are preferred, but prompt at runtime when they
    # are absent so no third-party package or hard-coded password is needed.
    if not EMAIL:
        EMAIL = input("Clarius email: ").strip()
    if not PASSWORD:
        PASSWORD = getpass.getpass("Clarius password: ")

    if not EMAIL or not PASSWORD:
        raise RuntimeError("Clarius email and password are required.")

    if EXAM_ENUMERATION_MODE not in {"auto", "api", "html"}:
        raise RuntimeError(
            'EXAM_ENUMERATION_MODE must be one of: "auto", "api", or "html".'
        )


def login_with_browser(page, context):
    """Log in once and return an authenticated Playwright API request context.

    BrowserContext.request shares the same cookie jar as the browser pages. This
    is why API calls and RAW browser downloads remain authenticated without the
    external requests package.
    """
    log("Logging into Clarius...")
    page.goto(f"{BASE_URL}/login")
    page.fill("input[type=email]", EMAIL)
    page.fill("input[type=password]", PASSWORD)
    page.click("button[type=submit]")

    try:
        page.wait_for_load_state("networkidle", timeout=LOGIN_TIMEOUT_MS)
    except PWTimeout:
        log("[WARN] Login did not reach networkidle; verifying the session directly.")

    archived_text = str(bool(ARCHIVED)).lower()
    exams_ui_url = (
        f"{BASE_URL}/{INSTITUTION_ID}/exams/?archived={archived_text}&page=1"
    )
    page.goto(exams_ui_url)

    if "login" in urlparse(page.url).path.lower():
        raise RuntimeError("Clarius redirected back to login. Check the credentials.")

    if page.locator("input[type=password]").count() > 0:
        raise RuntimeError("The login form is still visible after login submission.")

    # BrowserContext.request shares the authenticated browser cookie jar.
    api_ctx = context.request
    probe = api_ctx.get(
        f"{BASE_URL}/exams/",
        params={
            "inst_id": INSTITUTION_ID,
            "archived": archived_text,
        },
        timeout=API_TIMEOUT_MS,
        fail_on_status_code=False,
    )

    if probe.status in (401, 403):
        raise RuntimeError(f"Clarius authentication probe returned HTTP {probe.status}.")
    if probe.status < 200 or probe.status >= 400:
        raise RuntimeError(f"Clarius authentication probe returned HTTP {probe.status}.")
    if "login" in urlparse(probe.url).path.lower():
        raise RuntimeError("The authenticated API probe was redirected to login.")

    log("Login successful and authenticated Playwright request context established.")
    return api_ctx


def request_json(api_ctx, url, params=None):
    response = api_ctx.get(
        url,
        params=params or {},
        timeout=API_TIMEOUT_MS,
        fail_on_status_code=False,
    )

    if response.status in (401, 403):
        raise RuntimeError(f"Authentication failed for API request ({response.status}).")
    if response.status < 200 or response.status >= 300:
        preview = ""
        try:
            preview = response.text()[:250].replace("\n", " ")
        except Exception:
            pass
        raise RuntimeError(
            f"GET {url} returned HTTP {response.status}. Response preview: {preview!r}"
        )

    content_type = response.headers.get("content-type", "").lower()
    final_url = response.url
    final_path = urlparse(final_url).path.lower()

    if "login" in final_path:
        raise RuntimeError("API request was redirected to login; the session expired.")

    try:
        payload = response.json()
    except Exception as exc:
        preview = response.text()[:250].replace("\n", " ")
        raise RuntimeError(
            f"Expected JSON from {url}, but received Content-Type={content_type!r}. "
            f"Response preview: {preview!r}"
        ) from exc

    return payload, final_url

def extract_items_from_payload(payload, possible_keys):
    """Return (items, structure_recognized)."""
    if isinstance(payload, list):
        return payload, True

    if not isinstance(payload, dict):
        return [], False

    for key in possible_keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, list):
            return value, True
        if isinstance(value, dict):
            nested_items, recognized = extract_items_from_payload(value, possible_keys)
            if recognized:
                return nested_items, True

    # Some filtered endpoints return one object instead of a list.
    if any(key in payload for key in EXAM_ID_KEYS + CAPTURE_UUID_KEYS):
        return [payload], True

    return [], False


def update_url_page(url, page_number):
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["page"] = [str(page_number)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def extract_next_page_url(payload, current_url):
    if not isinstance(payload, dict):
        return None

    containers = [payload]
    for key in ["pagination", "page_info", "meta", "links"]:
        value = payload.get(key)
        if isinstance(value, dict):
            containers.append(value)

    for container in containers:
        for key in ["next", "next_url", "nextPage", "next_page"]:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return urljoin(current_url, value)
            if isinstance(value, int):
                return update_url_page(current_url, value)

    # Support current-page/total-pages structures that omit a direct next URL.
    current_page = None
    total_pages = None
    for container in containers:
        for key in ["current_page", "page", "page_number"]:
            value = container.get(key)
            if isinstance(value, int):
                current_page = value
                break
        for key in ["total_pages", "pages", "num_pages"]:
            value = container.get(key)
            if isinstance(value, int):
                total_pages = value
                break

    if current_page is not None and total_pages is not None and current_page < total_pages:
        return update_url_page(current_url, current_page + 1)

    return None


def fetch_paginated_json(api_ctx, first_url, params, item_keys, debug_name):
    """Fetch every page from a JSON endpoint and return one combined item list.

    The helper accepts several possible list and pagination field names because
    Clarius response structures may differ between endpoints or future releases.
    """
    all_items = []
    url = first_url
    request_params = params
    page_num = 1
    seen_urls = set()

    while url:
        payload, final_url = request_json(api_ctx, url, params=request_params)
        request_params = None

        if final_url in seen_urls:
            raise RuntimeError(f"Pagination loop detected at {final_url}")
        seen_urls.add(final_url)

        dump_debug_json(debug_name, page_num, payload)
        items, recognized = extract_items_from_payload(payload, item_keys)
        if not recognized:
            raise RuntimeError(
                f"Unrecognized JSON structure for {debug_name}. "
                "Enable DEBUG_DUMP_JSON to inspect it."
            )

        all_items.extend(items)
        log(f"{debug_name} page {page_num}: {len(items)} items (total {len(all_items)})")

        url = extract_next_page_url(payload, final_url)
        page_num += 1

    return all_items


# =====================================================================
# EXAM OBJECT NORMALIZATION
# =====================================================================


def first_present(mapping, keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def normalize_patient_value(value):
    if isinstance(value, dict):
        value = first_present(
            value,
            ["patient_msp", "msp", "patient_id", "identifier", "id", "name"],
        )
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_int_value(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def normalize_exam_object(item, source="api"):
    if not isinstance(item, dict):
        return None

    exam_id = parse_int_value(first_present(item, EXAM_ID_KEYS))
    patient_id = normalize_patient_value(first_present(item, EXAM_PATIENT_KEYS))
    status_value = first_present(item, EXAM_STATUS_KEYS)
    status = str(status_value).strip() if status_value is not None else None
    reported_captures = parse_int_value(first_present(item, EXAM_CAPTURE_COUNT_KEYS))

    # Parse clinical Exam Date and upload/created time independently.
    # Do not let a recently uploaded timestamp masquerade as the exam date.
    exam_date_dt = None
    exam_date_raw = None
    exam_date_key = None
    for key in EXAM_CLINICAL_DATE_KEYS:
        if item.get(key) not in (None, ""):
            candidate = try_parse_date(item.get(key))
            if candidate is not None:
                exam_date_raw = item.get(key)
                exam_date_dt = candidate
                exam_date_key = key
                break

    upload_dt = None
    upload_raw = None
    upload_date_key = None
    for key in EXAM_UPLOAD_DATE_KEYS:
        if item.get(key) not in (None, ""):
            candidate = try_parse_date(item.get(key))
            if candidate is not None:
                upload_raw = item.get(key)
                upload_dt = candidate
                upload_date_key = key
                break

    detail_url = first_present(item, EXAM_DETAIL_URL_KEYS)
    if detail_url:
        detail_url = urljoin(BASE_URL, str(detail_url))

    nested_date_dt = None
    nested_date_path = None
    if USE_NESTED_JSON_DATE_FALLBACK:
        nested_date_dt, nested_date_path, nested_raw, nested_score = best_date_from_json(
            item, prefer_earliest_on_tie=False
        )
        if nested_date_dt is not None and DEBUG_DATE_RESOLUTION:
            log(
                f"[DATE DEBUG] Exam JSON fallback for {patient_id}: "
                f"{nested_date_dt} from {nested_date_path} "
                f"(score={nested_score}, raw={nested_raw!r})"
            )

    return {
        "exam_id": exam_id,
        "patient_id": patient_id,
        "exam_name": patient_id,
        "status": status,
        "reported_captures": reported_captures,
        "upload_raw": upload_raw,
        "upload_dt": upload_dt,
        "upload_date_key": upload_date_key,
        "exam_date_raw": exam_date_raw,
        "exam_date_dt": exam_date_dt,
        "exam_date_key": exam_date_key,
        "exam_date_source": (
            f"top-level API {exam_date_key}" if exam_date_dt is not None else None
        ),
        "nested_date_dt": nested_date_dt,
        "nested_date_path": nested_date_path,
        "nested_date_score": nested_score if nested_date_dt is not None else None,
        "detail_url": detail_url,
        "source": source,
        "raw_object": item,
    }


def deduplicate_exam_records(records):
    output = []
    seen = set()

    for record in records:
        if not record:
            continue
        key = record.get("exam_id")
        if key is not None:
            dedupe_key = ("id", key)
        else:
            dedupe_key = (
                "composite",
                record.get("patient_id"),
                record.get("upload_dt"),
                record.get("detail_url"),
            )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        output.append(record)

    return output


# =====================================================================
# API-FIRST EXAM ENUMERATION
# =====================================================================


def enumerate_exams_api(api_ctx):
    """Fast path: enumerate all institution exams through the JSON endpoint."""
    archived_text = str(bool(ARCHIVED)).lower()
    items = fetch_paginated_json(
        api_ctx=api_ctx,
        first_url=f"{BASE_URL}/exams/",
        params={"inst_id": INSTITUTION_ID, "archived": archived_text},
        item_keys=EXAM_LIST_ITEM_KEYS,
        debug_name="exams_api",
    )

    records = []
    for item in items:
        record = normalize_exam_object(item, source="api")
        if record:
            records.append(record)

    records = deduplicate_exam_records(records)

    if items and not any(record.get("patient_id") for record in records):
        raise RuntimeError(
            "The exams API returned items, but no patient field could be recognized. "
            "Enable DEBUG_DUMP_JSON and update EXAM_PATIENT_KEYS."
        )

    if not records:
        raise RuntimeError("The institution-wide exams API returned no recognizable exams.")

    log(f"API enumeration returned {len(records)} unique exams.")
    return records


# =====================================================================
# HTML FALLBACK ENUMERATION / DETAIL READING
# =====================================================================


def extract_exam_id_from_url(url):
    if not url:
        return None

    text = str(url)
    query_match = re.search(
        r"[?&](?:exam_id|exam|id)=(\d+)(?:&|$)", text, flags=re.IGNORECASE
    )
    if query_match:
        return int(query_match.group(1))

    path_patterns = [
        r"/(?:exams?|studies?)/(?:view/|detail/)?(\d+)(?:/|$)",
        r"/(?:exam|study)/(\d+)(?:/|$)",
    ]
    for pattern in path_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))

    path_numbers = [int(x) for x in re.findall(r"/(\d+)(?=/|$)", text)]
    for value in reversed(path_numbers):
        if value != int(INSTITUTION_ID) and value >= 100000:
            return value
    return None


def collect_page_rows(page):
    rows = page.query_selector_all("tr[onclick], tr[data-exam-id], tr[data-id]")
    collected = []

    for row in rows:
        try:
            name_td = row.query_selector("td.exam-id")
            upload_td = row.query_selector("td.exam-upload")
            exam_name = name_td.inner_text().strip() if name_td else ""
            upload_raw = upload_td.inner_text().strip() if upload_td else "N/A"
            onclick_attr = row.get_attribute("onclick") or ""

            onclick_url = None
            match = re.search(r"['\"]([^'\"]+)['\"]", onclick_attr)
            if match:
                onclick_url = match.group(1)

            if not onclick_url:
                anchor = row.query_selector("a[href]")
                if anchor:
                    onclick_url = anchor.get_attribute("href")

            exam_id = None
            for attr in ["data-exam-id", "data-id", "data-pk"]:
                raw_id = row.get_attribute(attr)
                if raw_id and str(raw_id).isdigit():
                    exam_id = int(raw_id)
                    break
            if exam_id is None:
                exam_id = extract_exam_id_from_url(onclick_url)

            collected.append(
                {
                    "exam_id": exam_id,
                    "patient_id": exam_name or None,
                    "exam_name": exam_name or None,
                    "status": None,
                    "reported_captures": None,
                    "upload_raw": upload_raw,
                    "upload_dt": try_parse_date(upload_raw),
                    "exam_date_dt": None,
                    "detail_url": urljoin(BASE_URL, onclick_url) if onclick_url else None,
                    "source": "html",
                    "raw_object": None,
                }
            )
        except Exception as e:
            log(f"[WARN] Failed collecting an HTML row: {e}")

    return collected


def enumerate_exams_html(page, last_sync_dt, stop_at_last_sync=True):
    """Fallback path: enumerate exams by reading each page of the HTML table."""
    archived_text = str(bool(ARCHIVED)).lower()
    records = []
    page_num = 1
    seen_page_fingerprints = set()

    while True:
        list_url = (
            f"{BASE_URL}/{INSTITUTION_ID}/exams/"
            f"?archived={archived_text}&page={page_num}"
        )
        log(f"Loading HTML exams page {page_num}...")
        page.goto(list_url)

        try:
            page.wait_for_selector("table", timeout=DEFAULT_TIMEOUT_MS)
        except PWTimeout:
            log(f"[INFO] No exams table on HTML page {page_num}; stopping fallback pagination.")
            break

        page_records = collect_page_rows(page)
        log(f"HTML page {page_num}: Found {len(page_records)} rows.")
        if not page_records:
            break

        fingerprint = tuple(
            (record.get("exam_id"), record.get("patient_id"), record.get("upload_raw"))
            for record in page_records
        )
        if fingerprint in seen_page_fingerprints:
            log("[WARN] Repeated HTML page detected; stopping pagination.")
            break
        seen_page_fingerprints.add(fingerprint)

        records.extend(page_records)

        # Do not stop HTML pagination using the table's upload/created column.
        # It is not the clinical Exam Date and can differ substantially. The
        # per-exam detail check in process_exam() applies the real last_sync
        # boundary safely.

        page_num += 1

    records = deduplicate_exam_records(records)
    if not records:
        raise RuntimeError("HTML fallback did not find any exam rows.")

    log(f"HTML fallback returned {len(records)} unique exams.")
    return records


def try_read_detail_date(page, labels):
    """Read a *labelled* date from the exam detail page.

    Only exact label matches are accepted. Earlier versions also used a broad
    ``contains(...)/following::*[1]`` XPath. On the 2026 Clarius UI that XPath
    can match a large ancestor containing the words "Exam Date" and then read
    an unrelated live/current timestamp. The result is especially dangerous in
    normal sync because an old exam can suddenly appear newer than last_sync.
    """
    for label in labels:
        selectors = [
            f"xpath=//dt[normalize-space(.)='{label}' or normalize-space(.)='{label}:']/following-sibling::dd[1]",
            f"xpath=//*[normalize-space(.)='{label}' or normalize-space(.)='{label}:']/following-sibling::*[1]",
        ]
        for selector in selectors:
            try:
                loc = page.locator(selector)
                if loc.count() <= 0:
                    continue
                raw = loc.first.inner_text().strip()
                if not raw or len(raw) > 120 or "\n" in raw:
                    continue
                parsed = try_parse_date(raw)
                if parsed is not None:
                    if DEBUG_DATE_RESOLUTION:
                        log(
                            f"[DATE DEBUG] Exact detail label {label!r} -> "
                            f"{parsed} from raw={raw!r}"
                        )
                    return parsed
            except Exception:
                pass

    # Text-line fallback for layouts where the exact label and value are
    # separate rows. Again, only exact label lines are accepted.
    try:
        body_text = page.locator("body").inner_text()
        lines = [line.strip() for line in body_text.splitlines() if line.strip()]
        normalized_labels = {
            normalize_clarius_datetime_text(label).rstrip(":").lower()
            for label in labels
        }
        for i, line in enumerate(lines):
            normalized_line = normalize_clarius_datetime_text(line).rstrip(":").lower()
            if normalized_line not in normalized_labels:
                continue
            for candidate in lines[i + 1 : i + 4]:
                if len(candidate) > 120:
                    continue
                parsed = try_parse_date(candidate)
                if parsed is not None:
                    if DEBUG_DATE_RESOLUTION:
                        log(
                            f"[DATE DEBUG] Detail text-line label {line!r} -> "
                            f"{parsed} from raw={candidate!r}"
                        )
                    return parsed
    except Exception:
        pass

    return None


def hydrate_html_record(page, record):
    detail_url = record.get("detail_url")
    if not detail_url:
        return record

    page.goto(detail_url)

    try:
        patient_tab = page.locator("li#patientInfoTab")
        if patient_tab.count() > 0:
            patient_tab.first.click(timeout=5000, force=True)
    except Exception:
        pass

    patient_id = record.get("patient_id")
    patient_selectors = [
        "dt:has-text('Patient ID') + dd",
        "xpath=//dt[contains(normalize-space(.), 'Patient ID')]/following-sibling::dd[1]",
        "xpath=//*[normalize-space(.)='Patient ID' or normalize-space(.)='Patient ID:']/following-sibling::*[1]",
        "xpath=//*[contains(normalize-space(.), 'Patient ID')]/following::*[1]",
    ]
    for selector in patient_selectors:
        try:
            loc = page.locator(selector)
            if loc.count() > 0:
                value = loc.first.inner_text().strip()
                if value:
                    patient_id = value
                    break
        except Exception:
            pass

    detail_upload_dt = try_read_detail_date(page, ["Upload Date", "Uploaded", "Created"])
    detail_exam_dt = try_read_detail_date(page, ["Exam Date", "Acquired Date"])

    candidate_dates = []
    for selector in ["#patient_info_tab_content", "body"]:
        try:
            loc = page.locator(selector)
            if loc.count() > 0:
                candidate_dates.extend(
                    extract_date_candidates_from_text(loc.first.inner_text())
                )
                if candidate_dates:
                    break
        except Exception:
            pass

    extra_dt = try_parse_any_date_strings(candidate_dates)
    record["patient_id"] = patient_id
    record["exam_name"] = patient_id
    if detail_exam_dt is not None:
        record["exam_date_dt"] = detail_exam_dt
        record["exam_date_source"] = "Clarius Cloud Exam Date"
    if record.get("upload_dt") is None and detail_upload_dt is not None:
        record["upload_dt"] = detail_upload_dt
        record["upload_date_key"] = "detail page Upload/Created"
    # Do not use an unlabelled page-wide date (extra_dt) for naming or sync.
    # It may be a page clock, footer timestamp, or unrelated date.
    record["exam_id"] = record.get("exam_id") or extract_exam_id_from_url(page.url)
    return record


_HTML_EXAM_RECORDS_CACHE = None
_HTML_TABLE_FALLBACK_FAILED = False
_DISCOVERED_EXAM_DETAIL_URL_TEMPLATE = None


def _candidate_exam_detail_urls(record):
    """Return likely detail-page URLs for one API exam record.

    The 2026 Clarius UI update may no longer render the old HTML table. The
    exam ID still comes from the API, so a direct detail URL is much cheaper
    and more reliable than rescanning the institution list for every patient.
    """
    global _DISCOVERED_EXAM_DETAIL_URL_TEMPLATE

    exam_id = record.get("exam_id")
    candidates = []

    if record.get("detail_url"):
        candidates.append(record["detail_url"])

    if exam_id is None:
        return candidates

    templates = []
    if EXAM_DETAIL_URL_TEMPLATE:
        templates.append(EXAM_DETAIL_URL_TEMPLATE)
    if _DISCOVERED_EXAM_DETAIL_URL_TEMPLATE:
        templates.append(_DISCOVERED_EXAM_DETAIL_URL_TEMPLATE)

    # Common current/legacy route shapes. The first successful template is
    # cached, so later exams normally require only one navigation.
    templates.extend(
        [
            f"{BASE_URL}/{INSTITUTION_ID}/exams/{{exam_id}}/",
            f"{BASE_URL}/{INSTITUTION_ID}/exam/{{exam_id}}/",
            f"{BASE_URL}/exams/{{exam_id}}/",
            f"{BASE_URL}/exam/{{exam_id}}/",
            f"{BASE_URL}/{INSTITUTION_ID}/exams/view/{{exam_id}}/",
            f"{BASE_URL}/{INSTITUTION_ID}/exams/detail/{{exam_id}}/",
            f"{BASE_URL}/{INSTITUTION_ID}/exams/?exam_id={{exam_id}}",
            f"{BASE_URL}/{INSTITUTION_ID}/exams/?exam={{exam_id}}",
            f"{BASE_URL}/{INSTITUTION_ID}/exams/?id={{exam_id}}",
            f"{BASE_URL}/{INSTITUTION_ID}/exams?exam_id={{exam_id}}",
        ]
    )

    seen = set()
    for template in templates:
        try:
            url = template.format(exam_id=exam_id)
        except Exception:
            continue
        if url not in seen:
            seen.add(url)
            candidates.append(url)
    return candidates


def _template_from_successful_detail_url(url, exam_id):
    if not url or exam_id is None:
        return None
    exam_text = str(exam_id)
    if exam_text not in url:
        return None
    return url.replace(exam_text, "{exam_id}", 1)


def _trusted_nested_sync_date(record):
    """Return a nested JSON date only when its key is specific enough."""
    dt = record.get("nested_date_dt")
    score = record.get("nested_date_score")
    if dt is None or score is None or score < MIN_SYNC_DATE_FALLBACK_SCORE:
        return None
    return dt


def _trusted_capture_sync_date(capture_dt, capture_score):
    if (
        not USE_CAPTURE_DATE_FOR_SYNC_FILTER
        or capture_dt is None
        or capture_score is None
        or capture_score < MIN_SYNC_DATE_FALLBACK_SCORE
    ):
        return None
    return capture_dt


def choose_sync_date(record, capture_date_dt=None, capture_score=None):
    """Choose the date used to compare an exam with last_sync.

    Priority is deliberately clinical:
      1. labelled/top-level clinical Exam Date;
      2. high-confidence nested clinical metadata;
      3. high-confidence capture acquisition metadata.

    uploaded_at/created_at are never used as the sync boundary. A current upload
    timestamp for an old exam must not make that exam look newly acquired.
    """
    if record.get("exam_date_dt") is not None:
        return record.get("exam_date_dt"), (
            record.get("exam_date_source") or "clinical exam date"
        )

    nested_dt = _trusted_nested_sync_date(record)
    if nested_dt is not None:
        return nested_dt, "nested clinical exam metadata"

    capture_dt = _trusted_capture_sync_date(capture_date_dt, capture_score)
    if capture_dt is not None:
        return capture_dt, "capture acquisition metadata"

    return None, None


def choose_folder_date(record, capture_date_dt=None, capture_score=None):
    """Choose a trustworthy clinical date for the study-folder name.

    Upload/created timestamps are intentionally excluded. If all clinical
    sources fail, return None so the folder is named UNKDATE instead of being
    assigned a false download/upload date.
    """
    if record.get("exam_date_dt") is not None:
        return record.get("exam_date_dt"), (
            record.get("exam_date_source") or "clinical exam date"
        )

    candidates = []
    if (
        record.get("nested_date_dt") is not None
        and (record.get("nested_date_score") or 0) >= MIN_FOLDER_DATE_FALLBACK_SCORE
    ):
        candidates.append((
            record.get("nested_date_score") or 0,
            record.get("nested_date_dt"),
            "nested clinical exam metadata",
        ))

    if (
        USE_CAPTURE_DATE_FOR_FOLDER_NAME
        and capture_date_dt is not None
        and (capture_score or 0) >= MIN_FOLDER_DATE_FALLBACK_SCORE
    ):
        candidates.append((
            capture_score or 0,
            capture_date_dt,
            "capture acquisition metadata",
        ))

    if not candidates:
        return None, None

    # Highest-confidence source wins. On an exact score tie, prefer the earlier
    # time because acquisition typically precedes later processing metadata.
    candidates.sort(key=lambda item: (-item[0], item[1]))
    _, dt, source = candidates[0]
    return dt, source


def _detail_date_conflicts_with_trusted_json(detail_dt, record):
    """Detect the characteristic 'page clock parsed as Exam Date' failure."""
    nested_dt = _trusted_nested_sync_date(record)
    if detail_dt is None or nested_dt is None:
        return False

    now = datetime.now()
    near_now = abs(detail_dt - now) <= timedelta(minutes=DETAIL_PAGE_CLOCK_GUARD_MINUTES)
    conflicts = abs(detail_dt - nested_dt) >= timedelta(days=DETAIL_PAGE_CONFLICT_DAYS)
    return near_now and conflicts


def hydrate_api_record_from_direct_detail_page(page, record):
    """Try direct exam-detail URLs and read Exam Date without list scanning."""
    global _DISCOVERED_EXAM_DETAIL_URL_TEMPLATE

    exam_id = record.get("exam_id")
    patient_id = str(record.get("patient_id") or "").strip()

    for detail_url in _candidate_exam_detail_urls(record):
        try:
            page.goto(
                detail_url,
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT_MS,
            )

            if "login" in urlparse(page.url).path.lower():
                continue

            # Give the updated client-rendered UI enough time to display the
            # detail card. A 500 ms sleep was too short on some workstations.
            try:
                page.wait_for_selector(
                    "text=Exam Date", timeout=min(DEFAULT_TIMEOUT_MS, 5000)
                )
            except Exception:
                try:
                    page.wait_for_timeout(1500)
                except Exception:
                    pass

            exam_dt = try_read_detail_date(page, ["Exam Date", "Acquired Date"])
            upload_dt = try_read_detail_date(
                page,
                ["Upload Date", "Uploaded", "Created"],
            )

            if _detail_date_conflicts_with_trusted_json(exam_dt, record):
                log(
                    f"[WARN] Rejected suspicious Exam Date for {patient_id}: "
                    f"{exam_dt}; trusted nested JSON date is "
                    f"{_trusted_nested_sync_date(record)}."
                )
                exam_dt = None

            if _detail_date_conflicts_with_trusted_json(upload_dt, record):
                log(
                    f"[WARN] Rejected suspicious Upload/Created date for {patient_id}: "
                    f"{upload_dt}; trusted nested JSON date is "
                    f"{_trusted_nested_sync_date(record)}."
                )
                upload_dt = None

            if exam_dt is None and upload_dt is None:
                if DEBUG_DATE_RESOLUTION:
                    log(
                        f"[DATE DEBUG] No detail date at candidate URL for "
                        f"exam_id={exam_id}: requested={detail_url}, final={page.url}"
                    )
                continue

            # Guard against accidentally parsing a date from an unrelated page.
            if patient_id:
                try:
                    body_text = page.locator("body").inner_text()
                    if patient_id not in body_text and "Exam Date" not in body_text:
                        continue
                except Exception:
                    pass

            record["detail_url"] = page.url
            if exam_dt is not None:
                # A labelled Cloud "Exam Date" is authoritative for folder naming
                # and normal-sync filtering. It intentionally overrides weaker
                # top-level/nested fallbacks, but never overwrites upload_dt.
                record["exam_date_dt"] = exam_dt
                record["exam_date_source"] = "Clarius Cloud Exam Date"
            if record.get("upload_dt") is None and upload_dt is not None:
                record["upload_dt"] = upload_dt
                record["upload_date_key"] = "detail page Upload/Created"

            discovered = _template_from_successful_detail_url(page.url, exam_id)
            if discovered:
                _DISCOVERED_EXAM_DETAIL_URL_TEMPLATE = discovered

            log(
                f"[INFO] Resolved date for {record.get('patient_id')} from "
                f"direct exam detail page: exam_date={record.get('exam_date_dt')}, "
                f"upload_date={record.get('upload_dt')}"
            )
            return record
        except Exception:
            continue

    return record


def get_all_html_exam_records_for_date_fallback(page):
    """Try the legacy HTML list once, then cache success or failure.

    In the updated UI the old table may not exist. Previously an exception left
    the cache as None, so every patient retried the same failing scan. This
    function now caches an empty list after failure, preventing the apparent
    infinite loop and repeated 10-second timeouts.
    """
    global _HTML_EXAM_RECORDS_CACHE, _HTML_TABLE_FALLBACK_FAILED

    if _HTML_EXAM_RECORDS_CACHE is not None:
        return _HTML_EXAM_RECORDS_CACHE

    if _HTML_TABLE_FALLBACK_FAILED and DISABLE_HTML_TABLE_FALLBACK_AFTER_FIRST_FAILURE:
        return []

    log(
        "[INFO] Direct detail lookup did not resolve the date. Trying the "
        "legacy HTML exams table once."
    )

    try:
        _HTML_EXAM_RECORDS_CACHE = enumerate_exams_html(
            page,
            datetime(1900, 1, 1),
            stop_at_last_sync=False,
        )
    except Exception as exc:
        _HTML_EXAM_RECORDS_CACHE = []
        _HTML_TABLE_FALLBACK_FAILED = True
        log(
            f"[WARN] Legacy HTML table fallback is unavailable: {exc}. "
            "It will not be retried for every patient."
        )

    return _HTML_EXAM_RECORDS_CACHE


def match_html_record_for_api_record(api_record, html_records):
    exam_id = api_record.get("exam_id")
    patient_id = str(api_record.get("patient_id") or "").strip().lower()

    if exam_id is not None:
        exact_id = [r for r in html_records if r.get("exam_id") == exam_id]
        if exact_id:
            return exact_id[0]

    patient_matches = [
        r
        for r in html_records
        if str(r.get("patient_id") or "").strip().lower() == patient_id
    ]
    if not patient_matches:
        return None
    if len(patient_matches) == 1:
        return patient_matches[0]

    if exam_id is not None:
        for candidate in patient_matches:
            if extract_exam_id_from_url(candidate.get("detail_url")) == exam_id:
                return candidate

    patient_matches.sort(
        key=lambda r: r.get("upload_dt") or datetime.min,
        reverse=True,
    )
    log(
        f"[WARN] Multiple HTML rows matched {api_record.get('patient_id')}; "
        "using the newest visible row."
    )
    return patient_matches[0]


def hydrate_missing_api_date_from_html(page, record):
    """Resolve the clinical Exam Date without confusing it with upload time.

    Even when the list API already supplied uploaded_at/created_at, we still try
    the direct detail page if the clinical Exam Date is missing. This is what
    prevents a folder downloaded on Aug 28 from being named Aug_28 when Cloud's
    Exam Date is Aug 21 or Aug 6.
    """
    if not HTML_DETAIL_DATE_FALLBACK:
        return record

    # Preferred path for the new UI: use exam_id to open a detail page directly.
    if record.get("exam_date_dt") is None:
        record = hydrate_api_record_from_direct_detail_page(page, record)
    if record.get("exam_date_dt") is not None:
        return record

    # Final legacy fallback. This is attempted no more than once per run.
    html_records = get_all_html_exam_records_for_date_fallback(page)
    if not html_records:
        log(
            f"[WARN] Could not resolve a date for {record.get('patient_id')} "
            f"(exam_id={record.get('exam_id')}); continuing without repeated "
            "HTML scans."
        )
        return record

    html_record = match_html_record_for_api_record(record, html_records)
    if html_record is None:
        log(
            f"[WARN] Could not find an HTML detail row for "
            f"{record.get('patient_id')} (exam_id={record.get('exam_id')})."
        )
        return record

    hydrated = hydrate_html_record(page, dict(html_record))
    record["detail_url"] = record.get("detail_url") or hydrated.get("detail_url")
    if hydrated.get("exam_date_dt") is not None:
        record["exam_date_dt"] = hydrated.get("exam_date_dt")
        record["exam_date_source"] = "Clarius Cloud Exam Date"
    if record.get("upload_dt") is None and hydrated.get("upload_dt") is not None:
        record["upload_dt"] = hydrated.get("upload_dt")
    record["exam_id"] = record.get("exam_id") or hydrated.get("exam_id")

    resolved = record.get("exam_date_dt")
    if resolved is not None:
        log(
            f"[INFO] Resolved clinical Exam Date for {record.get('patient_id')} "
            f"from HTML exam details: {resolved}"
        )
    else:
        log(
            f"[WARN] HTML detail page was found, but no trustworthy clinical "
            f"Exam Date was extracted for {record.get('patient_id')}."
        )
    return record


# =====================================================================
# FILTERED EXAM LOOKUP (USED WHEN AN HTML ROW HAS NO EXAM ID)
# =====================================================================


def lookup_exams_by_patient(api_ctx, patient_id):
    archived_text = str(bool(ARCHIVED)).lower()
    items = fetch_paginated_json(
        api_ctx=api_ctx,
        first_url=f"{BASE_URL}/exams/",
        params={
            "inst_id": INSTITUTION_ID,
            "archived": archived_text,
            "patient_msp": patient_id,
        },
        item_keys=EXAM_LIST_ITEM_KEYS,
        debug_name=f"exam_lookup_{patient_id}",
    )

    records = []
    for item in items:
        record = normalize_exam_object(item, source="patient_lookup")
        if record:
            records.append(record)
    return deduplicate_exam_records(records)


def choose_exam_id_from_lookup(records, target_dt):
    candidates = []
    for record in records:
        exam_id = record.get("exam_id")
        if exam_id is None:
            continue
        status = str(record.get("status") or "").strip().lower()
        candidate_dt = (
            record.get("exam_date_dt")
            or _trusted_nested_sync_date(record)
            or record.get("upload_dt")
        )
        candidates.append((exam_id, candidate_dt, status))

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    if target_dt is not None:
        dated = [candidate for candidate in candidates if candidate[1] is not None]
        if dated:
            dated.sort(
                key=lambda candidate: (
                    0 if candidate[2] in {"completed", "complete"} else 1,
                    abs((candidate[1] - target_dt).total_seconds()),
                )
            )
            selected = dated[0]
            log(
                f"[INFO] Multiple exams matched; selected exam_id={selected[0]} "
                f"using the closest clinical/date fallback to {target_dt}."
            )
            return selected[0]

    completed = [c for c in candidates if c[2] in {"completed", "complete"}]
    pool = completed or candidates
    pool.sort(key=lambda candidate: candidate[1] or datetime.min, reverse=True)
    selected = pool[0]
    log(f"[WARN] Multiple exams matched; selected newest exam_id={selected[0]}.")
    return selected[0]


def resolve_exam_id(api_ctx, record):
    if record.get("exam_id") is not None:
        return record["exam_id"]

    patient_id = record.get("patient_id")
    if not patient_id:
        raise RuntimeError("Cannot resolve exam ID because patient ID is missing.")

    log(f"[INFO] Looking up exam ID for patient {patient_id} through /exams/.")
    matches = lookup_exams_by_patient(api_ctx, patient_id)
    target_dt = (
        record.get("exam_date_dt")
        or _trusted_nested_sync_date(record)
        or record.get("upload_dt")
    )
    exam_id = choose_exam_id_from_lookup(matches, target_dt)
    if exam_id is None:
        raise RuntimeError(f"No exam ID could be resolved for patient {patient_id}.")
    return exam_id


# =====================================================================
# CAPTURE API / STABLE IMAGE-FOLDER MAPPING
# =====================================================================


def get_capture_uuid(capture):
    value = first_present(capture, CAPTURE_UUID_KEYS)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def get_capture_raw_flag(capture):
    """Return True, False, or None when the API field is absent/unknown."""
    value = first_present(capture, CAPTURE_RAW_KEYS)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n", ""}:
            return False
    return None


def get_all_captures(api_ctx, exam_id):
    """Return all unique capture objects for one exam, including later pages."""
    items = fetch_paginated_json(
        api_ctx=api_ctx,
        first_url=f"{BASE_URL}/api/captures/{exam_id}/",
        params=None,
        item_keys=CAPTURE_LIST_ITEM_KEYS,
        debug_name=f"captures_exam_{exam_id}",
    )

    captures = []
    seen_uuids = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        capture_uuid = get_capture_uuid(item)
        if capture_uuid and capture_uuid in seen_uuids:
            continue
        if capture_uuid:
            seen_uuids.add(capture_uuid)
        captures.append(item)
    return captures


def read_capture_uuid_marker(folder):
    path = os.path.join(folder, CAPTURE_UUID_MARKER)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                value = f.read().strip()
                return value or None
    except Exception:
        pass
    return None


def write_capture_uuid_marker(folder, capture_uuid):
    path = os.path.join(folder, CAPTURE_UUID_MARKER)
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(capture_uuid).strip() + "\n")


def load_existing_capture_folder_map(study_path):
    uuid_to_folder = {}
    used_folders = set()

    if not os.path.isdir(study_path):
        return uuid_to_folder, used_folders

    for name in os.listdir(study_path):
        full_path = os.path.join(study_path, name)
        if not os.path.isdir(full_path):
            continue
        if not re.search(r"_Image_\d+$", name):
            continue
        used_folders.add(full_path)
        capture_uuid = read_capture_uuid_marker(full_path)
        if capture_uuid:
            uuid_to_folder[capture_uuid] = full_path

    return uuid_to_folder, used_folders


def assign_capture_folder(
    study_path,
    patient_num,
    suggested_index,
    capture_uuid,
    uuid_to_folder,
    used_this_run,
):
    existing = uuid_to_folder.get(capture_uuid)
    if existing:
        used_this_run.add(existing)
        return existing

    index = suggested_index
    while True:
        candidate = os.path.join(study_path, f"P{patient_num}_Image_{index}")
        marker_uuid = read_capture_uuid_marker(candidate) if os.path.isdir(candidate) else None

        if candidate not in used_this_run and marker_uuid in (None, capture_uuid):
            os.makedirs(candidate, exist_ok=True)
            write_capture_uuid_marker(candidate, capture_uuid)
            uuid_to_folder[capture_uuid] = candidate
            used_this_run.add(candidate)
            return candidate

        index += 1


def find_nonempty_tar(folder):
    if not os.path.isdir(folder):
        return None
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(".tar"):
            continue
        path = os.path.join(folder, name)
        try:
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                return path
        except OSError:
            pass
    return None


# =====================================================================
# PLAYWRIGHT BROWSER RAW DOWNLOAD
# =====================================================================


def safe_capture_filename(capture_uuid):
    safe_uuid = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(capture_uuid)).strip("._")
    return f"{safe_uuid or 'capture'}.tar"


def download_raw_capture(download_page, capture_uuid, destination_path):
    """
    Download through Playwright only. Each attempt starts again at
    /raw/<uuid>/, so Clarius creates a fresh short-lived S3 redirect.

    Playwright writes the browser download to its own temporary file; save_as()
    copies it to a local .part file, which is atomically renamed only after a
    non-empty download succeeds.
    """
    raw_url = f"{BASE_URL}/raw/{capture_uuid}/"
    temp_path = destination_path + ".part"

    for attempt in range(1, RAW_DOWNLOAD_ATTEMPTS + 1):
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)

            # Use a same-origin page and a temporary anchor. This keeps the
            # authenticated browser cookies and lets Chromium follow the 302.
            with download_page.expect_download(timeout=RAW_DOWNLOAD_TIMEOUT_MS) as info:
                download_page.evaluate(
                    """
                    url => {
                        window.location.href = url;
                    }
                    """,
                    raw_url,
                )

            download = info.value
            failure = download.failure()
            if failure:
                raise RuntimeError(f"Browser download failed: {failure}")

            download.save_as(temp_path)

            if not os.path.exists(temp_path):
                raise RuntimeError("Playwright did not create the downloaded file.")

            bytes_written = os.path.getsize(temp_path)
            if bytes_written <= 0:
                raise RuntimeError("Downloaded RAW file was empty.")

            os.replace(temp_path, destination_path)
            return bytes_written

        except Exception as e:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass

            log(
                f"[WARN] RAW attempt {attempt}/{RAW_DOWNLOAD_ATTEMPTS} failed "
                f"for capture {capture_uuid}: {e}"
            )

            if attempt < RAW_DOWNLOAD_ATTEMPTS:
                download_page.wait_for_timeout(RAW_RETRY_DELAY_SECONDS * 1000)
            else:
                raise

    raise RuntimeError(f"RAW download failed for capture {capture_uuid}.")


# =====================================================================
# ONE-EXAM PROCESSING
# =====================================================================


def exam_is_new_enough(record, last_sync_dt):
    """Conservative date predicate used by callers/tests.

    Unknown dates are NOT automatically new. ``process_exam`` performs the
    richer nested/capture fallback before making its final decision.
    """
    if range_mode_enabled():
        return in_patient_range(record.get("patient_id"))

    sync_dt, _ = choose_sync_date(record)
    if sync_dt is None:
        return False
    return sync_dt > last_sync_dt


def process_exam(page, download_page, api_ctx, record, last_sync_dt, processed_exam_ids):
    """Process one normalized exam record.

    Returns
    -------
    selected_as_new : bool
        True when the exam passed the study/range/date filters and was selected
        for inspection during this run.
    exam_completed_without_error : bool
        True only when capture discovery and all required download actions
        completed successfully. A confirmed no-RAW capture is not an error.

    This return pair is used by main() to decide whether last_sync.json may be
    advanced safely.
    """
    patient_id = record.get("patient_id") or record.get("exam_name")

    if record.get("source") == "html":
        record = hydrate_html_record(page, record)
        patient_id = record.get("patient_id") or patient_id

    if not patient_id:
        log("[WARN] Exam has no patient identifier; skipping.")
        return False, False

    if not is_study_patient(patient_id):
        return False, True

    if range_mode_enabled() and not in_patient_range(patient_id):
        return False, True

    # Resolve the clinical Exam Date before the sync decision and folder naming.
    # This must run even if the list API has uploaded_at/created_at; those fields
    # describe Cloud ingestion/updates and can be days or months later than the
    # actual exam shown in the Cloud UI.
    if record.get("exam_date_dt") is None:
        record = hydrate_missing_api_date_from_html(page, record)
        patient_id = record.get("patient_id") or patient_id

    sync_filter_dt, sync_filter_source = choose_sync_date(record)

    exam_id = None
    captures = None
    capture_date_dt = None
    capture_date_path = None
    capture_score = None

    # If normal sync still has no trustworthy date, inspect capture metadata
    # BEFORE making the last_sync decision. This prevents the old behavior
    # where date=None was automatically treated as new.
    if not range_mode_enabled() and sync_filter_dt is None:
        exam_id = resolve_exam_id(api_ctx, record)
        captures = get_all_captures(api_ctx, exam_id)
        if captures:
            capture_date_dt, capture_date_path, capture_raw, capture_score = (
                best_date_from_captures(captures)
            )
            sync_filter_dt, sync_filter_source = choose_sync_date(
                record, capture_date_dt, capture_score
            )
            if capture_date_dt is not None and DEBUG_DATE_RESOLUTION:
                log(
                    f"[DATE DEBUG] Capture fallback for {patient_id}: "
                    f"{capture_date_dt} from {capture_date_path} "
                    f"(score={capture_score}, raw={capture_raw!r})"
                )

    force_this_exam = should_force_exam(patient_id)
    if not range_mode_enabled() and not force_this_exam:
        if sync_filter_dt is None:
            log(
                f"[WARN] Cannot safely determine whether {patient_id} is newer "
                f"than last_sync={last_sync_dt}. No folder/download will be "
                "created, and last_sync will not advance."
            )
            # selected=True + ok=False deliberately blocks state advancement;
            # this is safer than silently missing a genuinely new undated exam.
            return True, False
        if sync_filter_dt <= last_sync_dt:
            log(
                f"[SKIP] Exam older than last_sync: {patient_id} "
                f"({sync_filter_dt}, source={sync_filter_source})"
            )
            return False, True

    selected_as_new = True

    # Resolve exam_id and fetch capture metadata before creating the folder.
    # Reuse metadata already fetched for the normal-sync date decision.
    if exam_id is None:
        exam_id = resolve_exam_id(api_ctx, record)
    if exam_id in processed_exam_ids:
        log(f"[SKIP] exam_id={exam_id} was already processed in this run.")
        return selected_as_new, True
    processed_exam_ids.add(exam_id)

    if captures is None:
        captures = get_all_captures(api_ctx, exam_id)
    reported_captures = record.get("reported_captures")

    if capture_date_dt is None and USE_CAPTURE_DATE_FOR_FOLDER_NAME and captures:
        capture_date_dt, capture_date_path, capture_raw, capture_score = (
            best_date_from_captures(captures)
        )
        if capture_date_dt is not None and DEBUG_DATE_RESOLUTION:
            log(
                f"[DATE DEBUG] Capture fallback for {patient_id}: "
                f"{capture_date_dt} from {capture_date_path} "
                f"(score={capture_score}, raw={capture_raw!r})"
            )

    # Choose the folder date independently from upload/created timestamps.
    folder_dt, date_source = choose_folder_date(
        record, capture_date_dt, capture_score
    )
    if folder_dt is None:
        log(
            f"[WARN] No trustworthy clinical Exam Date for {patient_id} after "
            "Cloud detail-page, nested clinical metadata, and capture-acquisition "
            "fallbacks; using UNKDATE rather than an upload/created date."
        )
    else:
        log(f"[INFO] Folder date for {patient_id}: {folder_dt} ({date_source})")

    study_path = get_or_create_study_path(
        MASTER_FOLDER,
        patient_id,
        folder_dt,
    )

    if (
        SKIP_EXISTING_STUDY_FOLDER
        and folder_has_any_content(study_path)
        and not force_this_exam
    ):
        log(f"[SKIP] Existing non-empty study folder: {study_path}")
        return selected_as_new, True

    log(
        f"Processing exam_id={exam_id} patient_id={patient_id} "
        f"status={record.get('status')} exam_date={folder_dt} "
        f"upload_date={record.get('upload_dt')}"
    )

    log(
        f"Exam {exam_id}: API returned {len(captures)} captures; "
        f"reported count={reported_captures}."
    )

    if not captures:
        marker_path = os.path.join(study_path, NO_CAPTURES_MARKER)
        with open(marker_path, "w", encoding="utf-8") as f:
            f.write(f"No captures returned by /api/captures/{exam_id}/.\n")

        empty_is_error = reported_captures not in (None, 0)
        if reported_captures is None and EMPTY_CAPTURES_WITH_UNKNOWN_COUNT_IS_ERROR:
            empty_is_error = True

        if empty_is_error:
            log(
                f"[ERROR] Capture API returned none for exam {exam_id}; "
                f"reported count={reported_captures}."
            )
            return selected_as_new, False
        return selected_as_new, True

    remove_marker_if_present(os.path.join(study_path, NO_CAPTURES_MARKER))
    patient_num = extract_patient_number_text(patient_id)
    uuid_to_folder, _ = load_existing_capture_folder_map(study_path)
    used_this_run = set()
    exam_ok = True

    for suggested_index, capture in enumerate(captures, start=1):
        if CANCEL_REQUESTED:
            log(
                "[STOP] Stop requested; ending after the current network action. "
                "last_sync will not be advanced."
            )
            return selected_as_new, False

        capture_uuid = get_capture_uuid(capture)
        if not capture_uuid:
            exam_ok = False
            error_path = os.path.join(study_path, CAPTURE_ERROR_MARKER)
            with open(error_path, "a", encoding="utf-8") as f:
                f.write(f"Capture #{suggested_index} had no UUID.\n")
            log(f"[ERROR] Capture #{suggested_index} for exam {exam_id} has no UUID.")
            continue

        img_folder = assign_capture_folder(
            study_path=study_path,
            patient_num=patient_num,
            suggested_index=suggested_index,
            capture_uuid=capture_uuid,
            uuid_to_folder=uuid_to_folder,
            used_this_run=used_this_run,
        )

        marker_path = os.path.join(img_folder, NO_RAW_MARKER)
        existing_tar = find_nonempty_tar(img_folder)

        if existing_tar and not OVERWRITE_EXISTING_RAW:
            remove_marker_if_present(marker_path)
            log(f"[SKIP] Existing RAW archive for capture {capture_uuid}: {existing_tar}")
            continue

        raw_flag = get_capture_raw_flag(capture)
        if raw_flag is False:
            with open(marker_path, "w", encoding="utf-8") as f:
                f.write(f"Capture UUID: {capture_uuid}\nhas_raw_data is false.\n")
            log(f"[NO RAW] exam_id={exam_id} capture={capture_uuid}")
            continue

        if raw_flag is None and not TRY_RAW_WHEN_FLAG_MISSING:
            exam_ok = False
            with open(marker_path, "w", encoding="utf-8") as f:
                f.write(
                    f"Capture UUID: {capture_uuid}\n"
                    "has_raw_data was missing or unrecognized; download was not attempted.\n"
                )
            log(f"[ERROR] Unknown has_raw_data value for capture {capture_uuid}.")
            continue

        destination_path = (
            existing_tar
            if existing_tar and OVERWRITE_EXISTING_RAW
            else os.path.join(img_folder, safe_capture_filename(capture_uuid))
        )
        try:
            bytes_written = download_raw_capture(
                download_page=download_page,
                capture_uuid=capture_uuid,
                destination_path=destination_path,
            )
            remove_marker_if_present(marker_path)
            log(
                f"[DOWNLOADED] exam_id={exam_id} capture={capture_uuid} "
                f"bytes={bytes_written}"
            )
        except Exception as e:
            exam_ok = False
            with open(marker_path, "w", encoding="utf-8") as f:
                f.write(
                    f"Capture UUID: {capture_uuid}\n"
                    f"RAW download failed after retries: {e}\n"
                )
            log(
                f"[ERROR] RAW download failed for exam_id={exam_id}, "
                f"capture={capture_uuid}: {e}"
            )

    return selected_as_new, exam_ok


# =====================================================================
# MAIN SYNC
# =====================================================================


def main():
    """Coordinate one complete synchronization run.

    The state timestamp is captured before work begins. Saving the run-start
    time, rather than the run-end time, leaves a safety overlap for exams that
    may be uploaded while this script is running.
    """
    ensure_directories()
    validate_config()
    ensure_state()

    try:
        last_sync_dt = make_naive_local(datetime.fromisoformat(load_last_sync()))
    except Exception:
        last_sync_dt = datetime(2000, 1, 1)

    now_dt = datetime.now()
    if last_sync_dt > now_dt:
        log(f"[WARN] last_sync is in the future ({last_sync_dt}); resetting it.")
        last_sync_dt = datetime(2000, 1, 1)
        save_last_sync(last_sync_dt.isoformat())

    log(f"Last sync timestamp: {last_sync_dt.isoformat()}")
    log(f"[INFO] EXAM_ENUMERATION_MODE = {EXAM_ENUMERATION_MODE}")
    log(f"[INFO] ARCHIVED = {ARCHIVED}")
    log(f"[INFO] SKIP_EXISTING_STUDY_FOLDER = {SKIP_EXISTING_STUDY_FOLDER}")

    if range_mode_enabled():
        log(
            f"[INFO] PATIENT RANGE mode: {PATIENT_RANGE_START} to {PATIENT_RANGE_END}; "
            f"FORCE_PATIENT_RANGE={FORCE_PATIENT_RANGE}"
        )

    run_start_ts = datetime.now().isoformat()
    log("=== STARTING CLARIUS HYBRID SYNC ===")

    with sync_playwright() as playwright:
        launch_kwargs = {
            "headless": not SHOW_BROWSER,
            "slow_mo": SLOW_MO_MS,
        }
        if SHOW_BROWSER:
            launch_kwargs["args"] = ["--start-maximized"]

        browser = playwright.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        try:
            api_ctx = login_with_browser(page, context)

            download_page = context.new_page()
            download_page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            download_page.goto(f"{BASE_URL}/{INSTITUTION_ID}/exams/")

            records = None
            if EXAM_ENUMERATION_MODE in {"auto", "api"}:
                try:
                    records = enumerate_exams_api(api_ctx)
                except Exception as e:
                    if EXAM_ENUMERATION_MODE == "api":
                        raise
                    log(f"[WARN] API exam enumeration failed: {e}")
                    log("[INFO] Falling back to the exams webpage.")

            if records is None:
                records = enumerate_exams_html(page, last_sync_dt)

            # Prefer newest exams first when dates are available.
            records.sort(
                key=lambda record: (
                    record.get("exam_date_dt")
                    or record.get("upload_dt")
                    or datetime.min
                ),
                reverse=True,
            )

            # These flags summarize the entire run:
            # - processed_exam_ids prevents duplicates when API/HTML records overlap.
            # - selected_any tells us whether any new study exam was considered.
            # - run_had_errors blocks last_sync advancement after partial failure.
            processed_exam_ids = set()
            selected_any = False
            run_had_errors = False

            # Records are newest-first when dates are known. Cheap filters are
            # applied before opening detail pages to reduce browser work.
            for record in records:
                if CANCEL_REQUESTED:
                    run_had_errors = True
                    log(
                        "[STOP] Stop requested; no additional exams will be started. "
                        "last_sync will not be advanced."
                    )
                    break

                patient_id = record.get("patient_id") or record.get("exam_name")

                # Apply inexpensive filters before opening an HTML detail page.
                if patient_id and not is_study_patient(patient_id):
                    continue
                if patient_id and range_mode_enabled() and not in_patient_range(patient_id):
                    continue
                if (
                    patient_id
                    and not range_mode_enabled()
                    and record.get("exam_date_dt") is not None
                    and record["exam_date_dt"] <= last_sync_dt
                ):
                    continue

                try:
                    selected, exam_ok = process_exam(
                        page=page,
                        download_page=download_page,
                        api_ctx=api_ctx,
                        record=record,
                        last_sync_dt=last_sync_dt,
                        processed_exam_ids=processed_exam_ids,
                    )
                    selected_any = selected_any or selected
                    if selected and not exam_ok:
                        run_had_errors = True
                except Exception as e:
                    selected_any = True
                    run_had_errors = True
                    identifier = patient_id or record.get("exam_id") or "unknown exam"
                    log(f"[ERROR] Failed to process {identifier}: {e}")

            # A stop request can arrive during the final capture, after the last
            # loop-boundary check. Recheck immediately before any state update.
            if CANCEL_REQUESTED:
                run_had_errors = True
                log("[STOP] Stop requested; last_sync will not be advanced.")

            # State-update rules are deliberately conservative. Range mode is
            # isolated from routine sync state. Normal mode advances only when at
            # least one exam was selected and every selected exam completed.
            if range_mode_enabled():
                log("[INFO] PATIENT RANGE mode: last_sync was not updated.")
            elif selected_any and not run_had_errors:
                save_last_sync(run_start_ts)
            elif selected_any and run_had_errors:
                log(
                    "[WARN] One or more selected exams/captures failed; "
                    "last_sync was NOT updated so they can be retried."
                )
            else:
                log("No new study exams were selected; last_sync was not updated.")

        finally:
            browser.close()

    log("=== SYNC COMPLETE ===")


if __name__ == "__main__":
    main()
