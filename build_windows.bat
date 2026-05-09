@echo off
setlocal

cd /d "%~dp0"

py -m pip install --upgrade pyinstaller
py -m PyInstaller --noconfirm --onefile --windowed --name l2tool gui.py

echo.
echo Built: dist\l2tool.exe
