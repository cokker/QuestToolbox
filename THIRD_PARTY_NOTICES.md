# Third-party components

Quest Toolbox source code: MIT, copyright 2026 COKKER.

## Portable distribution

- CPython 3.12.10: Python Software Foundation license; `runtime/LICENSE.txt`.
  Unmodified official embeddable distribution: https://www.python.org/downloads/release/python-31210/
  Source: https://www.python.org/ftp/python/3.12.10/Python-3.12.10.tar.xz
- PySide6-Essentials 6.8.3 / Qt 6.8.3 and Shiboken6 6.8.3: LGPLv3 for the libraries used by this application, with additional notices as distributed by Qt.
  License text: `licenses/LGPL-3.0.txt`, `licenses/GPL-3.0.txt`.
  Original wheels and metadata remain under `runtime/Lib/site-packages`.
  Exact-version upstream source: https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/
  Qt source: https://download.qt.io/official_releases/qt/6.8/6.8.3/single/
  Qt license documentation: https://doc.qt.io/qt-6/licensing.html
  Qt libraries are dynamically loaded and remain replaceable. Reverse engineering for debugging modifications to these libraries is not prohibited by this project.
- Microsoft VC runtime DLLs included in the official CPython / Qt distributions retain their upstream redistribution terms.

## Optional external tools

- Android SDK Platform-Tools / ADB: downloaded by the user from Google after accepting Android SDK terms. Not bundled.
- scrcpy: Apache-2.0, Genymobile. Official Windows release contains additional third-party components and corresponding notices. Not bundled. Downloaded archives and licenses are preserved in the tool installation directory.

No Meta firmware, games, store APKs, credentials or proprietary headset assets are included.
