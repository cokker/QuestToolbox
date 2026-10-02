# Changelog

## 0.1.1 Preview — 2026-10-02

The connection indicator now distinguishes an unauthorized or offline headset
from an active USB/Wi-Fi session. Switching the system-app filter refreshes
the list and clears stale selection. Official ADB and scrcpy downloads can
replace an existing managed copy; if installation fails, the previous copy is
restored. Windows and local UI tests cover the changes. Physical headset
testing is still pending.

## 0.1.0 Preview — 2026-10-01

Initial implementation: USB/Wi-Fi ADB, multi-device selection, APK management,
shared-storage file manager, documented Quest display settings with rollback,
model-specific profiles, scrcpy mirror/recording, screenshots, logcat and report
preview, themes, RU/EN interface and GitHub release checking.

Added regression coverage for preview update discovery, mouse-wheel scrolling,
scroll position on tab switches, log process shutdown and protected folders.
Windows CI builds the application and launches the actual packaged EXE before
release publication. Physical Quest compatibility still requires device testing.
