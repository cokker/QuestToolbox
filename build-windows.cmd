@echo off
setlocal
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt pytest pyinstaller
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pytest -q
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name QuestToolbox --icon docs\icon.ico --add-data "licenses;licenses" main.py
if errorlevel 1 goto fail
copy README.md dist\QuestToolbox\README.md >nul
copy LICENSE dist\QuestToolbox\LICENSE >nul
copy THIRD_PARTY_NOTICES.md dist\QuestToolbox\THIRD_PARTY_NOTICES.md >nul
powershell -NoProfile -Command "Compress-Archive -Path 'dist\QuestToolbox' -DestinationPath 'dist\QuestToolbox-Windows-x64.zip' -Force"
if errorlevel 1 goto fail
start "" "dist\QuestToolbox"
echo Build complete.
pause
exit /b 0
:fail
echo Build failed. See the error above.
pause
exit /b 1
