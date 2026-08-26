# macOS Signing and Notarization

The macOS workflow builds usable architecture-specific DMGs without Python on
the recipient's Mac. Without institutional Apple credentials, PyInstaller uses
an ad-hoc signature; Gatekeeper may require an explicit first-launch approval.

For a normal double-click experience, an authorized Apple Developer Program
Account Holder should obtain a **Developer ID Application** certificate and
configure the following encrypted GitHub repository secrets:

| Secret | Value |
| --- | --- |
| `MACOS_CERTIFICATE_BASE64` | Base64 encoding of the exported Developer ID Application `.p12` file |
| `MACOS_CERTIFICATE_PASSWORD` | Password protecting that `.p12` export |
| `MACOS_CODESIGN_IDENTITY` | Full certificate identity, such as the approved `Developer ID Application: … (TEAMID)` value |
| `APPLE_ID` | Apple ID authorized for notarization |
| `APPLE_APP_SPECIFIC_PASSWORD` | App-specific password created for the authorized Apple ID |
| `APPLE_TEAM_ID` | Apple Developer team identifier |

Never commit a certificate, private key, password, or Apple credential to the
repository. Use **Settings → Secrets and variables → Actions → New repository
secret**. Once configured, **Build macOS apps** applies hardened Developer ID
signing, submits each DMG to Apple's notary service, and staples the result.

Before production signing, replace the provisional bundle identifier
`org.research.clariusrawdownloader` in `ClariusRawDownloader-macos.spec` with an
identifier approved and controlled by the responsible institution.

Official references:

- https://developer.apple.com/help/account/certificates/create-developer-id-certificates/
- https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution
