# Platform packages and release verification

The native build includes Python, application dependencies, compiled dashboard, CLI, terminal UI and node/worker/API adapter entry points. External coding tools, Git, provider credentials and third-party adapter plugins are not included. Install plugins in the Python distribution or make a custom native build including them; portable packages cannot discover arbitrary plugins installed in another Python environment.

## Supported targets

CI builds and tests Windows x64, macOS Intel and Apple Silicon, Linux x64 and ARM64. Linux packages target glibc 2.39+ (Ubuntu 24.04 baseline). Use Python installation or Docker on Alpine/musl or older Linux. Windows ARM64 and 32-bit systems are not native release targets. Android/iOS use a browser connected to a server; add the page to the home screen where supported. A web manifest provides app metadata; the dashboard does not cache authenticated project data or promise offline operation.

Each native job runs the backend tests, actual browser workflows and a portable smoke test outside the checkout with Python/Node/Git removed from PATH. Source-wheel installers are additionally exercised with Python 3.11 and 3.14 on macOS/Windows. Managed cancellation tests exercise real worker and CLI descendants, including a process whose parent exited.

## Building

```bash
uv sync --frozen --extra dev --extra build --python 3.12
uv run --extra build python packaging/build.py --native-formats
```

Build on the target OS and architecture. Linux needs dpkg-deb and rpmbuild. Windows needs Inno Setup 6. macOS needs hdiutil from the system. Outputs are under `dist/native`; this directory is never committed. Preserve the full extracted portable folder, not just its executable.

Linux produces portable tar.gz, deb and rpm. Windows produces a portable ZIP and an Inno Setup installer without requiring administrator privileges. macOS produces portable tar.gz and a disk image containing AgentVerse.app.

The release job waits for all test/install/native jobs, verifies archive checksums, and publishes a stable v0.4.2 release with the updater manifest. It preserves an already published stable release rather than replacing its assets with unrelated later commits. Bump the version, installer tag and release target together for a subsequent release.

## Signing

Signing credentials belong to the maintainer and cannot be generated from the repository. Without configured credentials, packages are unsigned (or ad-hoc signed by the macOS bundler), and release notes state this clearly. OS trust prompts are not bypassed.

Optional GitHub Actions secrets:

- `WINDOWS_SIGNING_PFX`: base64 PFX; `WINDOWS_SIGNING_PASSWORD`: its password. The build signs the executable and Windows installer using signtool and SHA-256 timestamping.
- `MACOS_SIGNING_P12`, `MACOS_SIGNING_PASSWORD`, `MACOS_SIGNING_IDENTITY`: Developer ID certificate material and identity. The build imports a temporary keychain and signs the bundled runtime and application.
- `MACOS_NOTARY_PROFILE`: a notarytool credential profile already configured in the build environment; or `MACOS_NOTARY_KEY_P8`, `MACOS_NOTARY_KEY_ID`, `MACOS_NOTARY_ISSUER`: App Store Connect API key material for ephemeral CI. Successful notarization is stapled to the disk image.

Release SHA-256 files and the updater manifest detect corrupt downloads. They do not replace publisher signatures. Private signing material is never committed or printed.

## Startup and removal

`shortcut` creates a per-user launcher. `autostart` is opt-in. Linux desktop autostart uses XDG; Linux service mode uses systemd --user. macOS uses a LaunchAgent. Windows uses the user's Startup folder, not an elevated pre-login Windows service. There is no forced startup task at installation.

Stop and remove autostart/user services before moving the application folder. `uninstall` removes installer environments and keeps data unless `--delete-data` is passed. Native installed files are removed through their OS installer/package manager; portable folders can be deleted after stopping. Restore/updates never recursively delete an arbitrary workspace directory.
