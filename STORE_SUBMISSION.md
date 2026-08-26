# Microsoft Store Submission Handoff

The project can produce a normal offline Windows `.exe` installer. Publishing
that installer in Microsoft Store is an organizational release process, not a
code-conversion step.

## Required ownership and approvals

Before submission, the research team should decide who legally owns and
maintains the app. The authorized publisher must provide:

- A Microsoft Partner Center Windows developer account.
- An approved publisher/app name and support contact.
- Institutional approval for distributing a Clarius research-data downloader.
- A public HTTPS privacy-policy and support page.
- A trusted code-signing certificate. Microsoft requires a submitted Win32
  installer and its executable files to be signed by a certificate chaining to
  a trusted root; a self-signed certificate is not sufficient.
- A stable HTTPS URL hosting the unchanged offline installer.
- Store description, screenshots, system requirements, age rating, and
  certification responses.

Official Microsoft references:

- https://learn.microsoft.com/windows/apps/publish/
- https://learn.microsoft.com/windows/apps/publish/partner-center/open-a-developer-account
- https://learn.microsoft.com/windows/apps/distribute-through-store/how-to-distribute-your-win32-app-through-microsoft-store
- https://learn.microsoft.com/windows/apps/package-and-deploy/publish-first-app
- https://learn.microsoft.com/windows/apps/publish/store-policies

## Recommended route for this research tool

For the immediate supervisor handoff, use the signed internal
`ClariusRawDownloader-Setup.exe`. A public Store listing may be unnecessary for
an app that is useful only with an authorized Clarius account and approved
research-data storage. Ask institutional IT whether controlled distribution
through the organization's software portal, Intune/Company Portal, or an
approved internal file service is more appropriate.

If Microsoft Store distribution is approved, Partner Center currently accepts
unmodified Win32 `.exe`/`.msi` installers after submission and certification.
The publisher should submit the signed installer generated from this project.

## Apple App Store

The project now produces direct-download Intel and Apple Silicon macOS DMGs.
These are not Mac App Store submissions. A Mac App Store release would still
require an Apple Developer account, approved bundle identity, distribution
certificates and provisioning, sandbox/entitlement review, notarization, Store
metadata, and review of whether the bundled Playwright Chromium runtime is
compatible with the App Store sandbox. Institutional approval is required.
