# Build the Installer Without Installing Python

Use this route when the maintainer also does not want Python on their computer.
GitHub's Windows build computer performs the build; Lynn receives one installer.

## One-time private repository setup

1. Sign in to GitHub and create a **private** repository, for example
   `clarius-raw-downloader`.
2. Open the repository and choose **Add file → Upload files**.
3. Upload the **contents** of this project folder so that `app.py`,
   `requirements-build.txt`, and `.github` are at the repository root.
4. Commit the uploaded files to the default branch.

The repository should remain private unless the research team explicitly
approves public release.

## Produce the Windows installer

1. Open the repository's **Actions** tab.
2. Select **Build Windows installer**.
3. Choose **Run workflow**.
4. Wait for every build step to become green.
5. Open the completed workflow run.
6. Under **Artifacts**, download **ClariusRawDownloader-Installer**.
7. Extract that small artifact ZIP. Inside is the end-user file:

   `ClariusRawDownloader-Setup.exe`

Only GitHub's temporary Windows runner uses Python. Neither the maintainer's
computer nor Lynn's computer needs Python.

## Produce the macOS downloads

1. In the same repository, open **Actions**.
2. Select **Build macOS apps** and choose **Run workflow**.
3. When both jobs are green, download the appropriate artifact:

   - `ClariusRawDownloader-macOS-Apple-Silicon` for M1/M2/M3/M4 or later
     Apple-series chips.
   - `ClariusRawDownloader-macOS-Intel` for Macs whose processor is Intel.

4. Extract the GitHub artifact ZIP to obtain the corresponding `.dmg` file.

Each workflow tests its architecture-matched embedded Chromium before exposing
the artifact. No Python installation is required on the Mac receiving the DMG.

## What Lynn receives

Send Lynn the appropriate operating-system download plus the approved handoff
instructions:

- Windows: `ClariusRawDownloader-Setup.exe`
- Apple Silicon Mac: `ClariusRawDownloader-macOS-Apple-Silicon.dmg`
- Intel Mac: `ClariusRawDownloader-macOS-Intel.dmg`

The installer is not automatically Microsoft Store-published or digitally
signed. Institutional IT should sign/approve it before broad distribution.
