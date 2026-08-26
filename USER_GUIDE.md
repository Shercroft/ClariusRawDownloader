# Clarius RAW Data Downloader — User Guide

This program downloads and tracks RAW archives from Clarius Cloud. The Windows
installer includes the application runtime and browser: the operator does
**not** need Python and should never edit source code.

## First-time setup

1. Copy `ClariusRawDownloader-Setup.exe` to the computer that will perform the
   downloads.
2. Double-click the installer and complete the installation wizard.
3. Open **Clarius RAW Data Downloader** from the Start menu or desktop shortcut.
4. If Windows SmartScreen appears for an unsigned internal build, confirm the
   file came from the research team before choosing **More info → Run anyway**.
   A lab/Unity Health code-signed build is preferable for routine distribution.
5. Enter the Clarius email and password. The password is used only in memory for
   the current run and is never saved.
6. Confirm the institution ID, study code, and download folder.

If the team already has a working `last_sync.json` from the original Python
script, choose the correct active/archived mode and click **Import prior state…**
before the first normal sync. This preserves the existing tracking cutoff while
placing it in the new app's state folder.

The **download folder** may be local, a mapped drive, or an approved network
location, provided the operator has write access. Uninstalling the app does not
delete downloaded study data or synchronization logs stored there.

## Required first test

Use a small, known patient before running a full synchronization:

1. Select **Patient range rerun**.
2. Enter the same known patient number in both boxes, for example `149` to
   `149` only if P149 is an appropriate approved test case.
3. Leave **Show browser** checked.
4. Leave **Replace existing RAW archives** unchecked.
5. Click **Start download** and watch the browser/login plus the in-app log.
6. Open the download folder and confirm the expected study, image folders,
   `_CAPTURE_UUID.txt` markers, and non-empty `.tar` archives appear.
7. Run the same range again. Existing non-empty TAR files should be reported as
   skipped, demonstrating resume protection.

Patient-range runs never change the normal synchronization timestamp.

## Routine normal synchronization

1. Select **Normal sync**.
2. Confirm **Last successful sync** is the expected value for this download
   folder.
3. Click **Start download**.
4. Review the final status and warnings in the run log.

On the first normal sync in a new download folder, the program warns that no
tracking state exists. Continuing may inspect and download every matching study
exam. Cancel and use a patient-range test first if that is not intended.

Do not invent or manually edit a timestamp. Use **Import prior state…** only
with a known-good state file from the earlier downloader.

Active and archived exams have separate successful-sync timestamps. Switching
**Download archived exams** does not reuse the active-exam timestamp.

## Options

| Option | Meaning |
| --- | --- |
| Show browser | Makes login/navigation visible. Keep on for initial testing; turn off for quieter routine runs. |
| Download archived exams | Reads the archived Clarius list rather than active exams. It uses a separate tracking timestamp. |
| Detailed date-resolution log | Adds diagnostic messages showing how study-folder dates were selected. |
| Skip a study folder if it already contains any files | Skips the whole study folder. Normally leave this off so missing captures can resume. |
| Replace existing RAW archives | Deliberately replaces existing non-empty TARs. Leave off unless re-download is explicitly required. |

## Stopping safely

Click **Stop safely**. The current network download is allowed to finish so a
partial TAR cannot look complete; no new capture/exam will then begin. A stopped
run does not advance the successful-sync timestamp, so it can be resumed.

## Output and troubleshooting files

Downloaded study folders are written directly under the chosen download folder.
The following support folder is also created:

```text
<download folder>\_ClariusDownloader\
    last_sync_active.json
    last_sync_archived.json
    logs\
        sync_YYYY-MM-DD.txt
        crash_YYYYMMDD_HHMMSS.txt   (only after an unexpected failure)
```

When requesting technical help, send the relevant log file after checking that
it is permitted to share under the study's data-handling rules. Do not send RAW
archives, credentials, or temporary download URLs.

Common issues:

- **Login redirected back to the sign-in page:** re-enter the account details.
  If Clarius added MFA, SSO, or changed its login fields, the app may require an
  update.
- **Download folder cannot be opened:** reconnect the mapped/network drive or
  choose a local approved folder with write permission.
- **No matching exams:** confirm institution ID, study code, active/archived
  selection, and patient range.
- **Antivirus/SmartScreen blocks the app:** verify the ZIP source with the
  research team and ask institutional IT to approve or code-sign the build.
- **Clarius page/API changed:** enable the detailed date log, reproduce with one
  approved patient, and provide the normal log to the maintainer.

## Handoff acceptance checklist

Before relying on the app for research data collection, test the final installer
on a Windows computer that does not have Python installed:

- `ClariusRawDownloader-Setup.exe` installs without Python.
- The app opens from the Start menu and desktop shortcut.
- Password text is hidden and is absent after closing/reopening the app.
- A known one-patient range downloads the expected captures.
- Repeating that range skips existing non-empty TARs.
- **Stop safely** prevents the sync timestamp from advancing.
- A controlled normal sync updates `last_sync_active.json` only after a fully
  successful run.
- The daily log contains enough information to identify skipped, downloaded,
  no-RAW, and failed captures.
