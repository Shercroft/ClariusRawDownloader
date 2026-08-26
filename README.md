# Clarius RAW Data Downloader

A Windows and macOS desktop interface around the existing Clarius Playwright
downloader. End-user downloads contain Python, Playwright, and Chromium. The
operator does not install Python or edit code.

## What changed from the original script

- Removed embedded credentials. The GUI supplies a session-only password.
- Replaced code constants with ordinary form controls.
- Added normal-sync and patient-range modes, folder selection, protected
  overwrite confirmation, live logs, and graceful stopping.
- Kept active and archived synchronization state separate.
- Added local settings that intentionally exclude the password.
- Added Windows PyInstaller/Chromium packaging, a one-file installer, and offline
  self-tests.

The existing exam enumeration, date resolution, stable capture mapping,
resume/overwrite behavior, and conservative `last_sync` rules remain in
`clarius_downloader_core.py`.

## End-user downloads

| Computer | Download |
| --- | --- |
| Windows 64-bit | `ClariusRawDownloader-Setup.exe` |
| Apple Silicon Mac | `ClariusRawDownloader-macOS-Apple-Silicon.dmg` |
| Intel Mac | `ClariusRawDownloader-macOS-Intel.dmg` |

## Preferred builds: no local Python

Follow `CLOUD_BUILD.md`. The included private GitHub Actions workflow uses a
temporary Windows build computer and produces the end-user artifact
the Windows installer and both architecture-specific macOS DMGs. Neither the
maintainer nor Lynn needs Python.

## Local maintainer build

The final Windows executable must be built on Windows because PyInstaller
packages for the operating system on which it runs.

1. Install 64-bit Python 3.12 on the maintainer's build computer.
2. Double-click `build_windows.bat` (developer tool only; never give this file
   to Lynn).
3. Wait while the isolated build environment and Chromium are downloaded.
4. Retrieve `dist\installer\ClariusRawDownloader-Setup.exe`.
5. Test that installer on a separate Windows computer without Python, following
   `USER_GUIDE.md`.

The build script runs unit tests, a source self-test, the PyInstaller build, the
packaged executable's self-test, and then wraps the complete one-folder runtime
inside a conventional Inno Setup installer.

Microsoft Store publishing is optional and requires an authorized publisher
account, code signing, institutional approval, hosting, and Store certification.
See `STORE_SUBMISSION.md`; generating an installer does not publish it.

## Local source checks

```powershell
python -m unittest discover -s tests -v
python app.py --self-test
```

Running the live downloader from source additionally requires the matching
Playwright/Chromium installation in `requirements-build.txt`.

## Security and operational notes

- Never hard-code credentials or include a real password in screenshots, logs,
  source control, tickets, or a packaged executable.
- The email and non-sensitive preferences are saved per Windows user; the
  password is not saved.
- The app does not bypass Clarius permissions. Use only an authorized account
  and an approved research-data destination.
- The internal ZIP is unsigned unless institutional IT applies a code-signing
  certificate. Verify provenance before accepting a SmartScreen override.
- Rebuild and retest when Playwright is upgraded or Clarius changes its login,
  page structure, or API fields.

## Project layout

| File | Purpose |
| --- | --- |
| `app.py` | tkinter GUI, settings, thread/log bridge, validation, and self-test |
| `clarius_downloader_core.py` | Existing Clarius download engine with credentials removed and safe-stop checks added |
| `ClariusRawDownloader.spec` | PyInstaller one-folder build including Playwright and Chromium |
| `ClariusRawDownloader-macos.spec` | PyInstaller macOS `.app` build including Playwright and Chromium |
| `build_windows.bat` | Repeatable Windows build and packaged smoke test |
| `installer/ClariusRawDownloader.iss` | One-file Windows installer definition |
| `USER_GUIDE.md` | Operator instructions and handoff acceptance checklist |
| `CLOUD_BUILD.md` | Build the installer without installing Python locally |
| `STORE_SUBMISSION.md` | Store/account/signing handoff requirements |
| `MACOS_SIGNING.md` | Optional Developer ID signing and notarization setup |
| `tests/test_app.py` | Offline configuration/security tests |
| `.github/workflows/build-windows.yml` | Windows cloud build producing the installer |
| `.github/workflows/build-macos.yml` | Apple Silicon and Intel Mac cloud builds producing DMGs |
