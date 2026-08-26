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

## Produce the installer

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

## What Lynn receives

Send Lynn only `ClariusRawDownloader-Setup.exe` plus the approved handoff
instructions. She double-clicks it, completes the installation wizard, and then
opens **Clarius RAW Data Downloader** from the Windows Start menu or desktop.

The installer is not automatically Microsoft Store-published or digitally
signed. Institutional IT should sign/approve it before broad distribution.

