@echo off
cd /d "%~dp0"
echo === Chess 3 build ===
python make_icon.py
python -m PyInstaller --noconfirm --onefile --windowed --name Chess3 --icon chess3.ico main.py
if errorlevel 1 (
  echo BUILD FAILED
  exit /b 1
)
echo.
echo Done! Send dist\Chess3.exe to your friends.
