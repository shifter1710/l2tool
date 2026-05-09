@echo off
setlocal

cd /d "%~dp0"

py -m pip install --upgrade pyinstaller
py -m pip install -r requirements.txt
py -m PyInstaller --noconfirm --onefile --windowed --name l2tool --collect-all tzdata gui.py

echo.
echo Built: dist\l2tool.exe
