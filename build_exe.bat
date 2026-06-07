@echo off
cd /d "%~dp0"
python -m PyInstaller --noconfirm --windowed --name FrameScope --add-binary "tools\PresentMon\PresentMon.exe;." fps_monitor.py
if errorlevel 1 (
  echo.
  echo PyInstaller is not installed. Install it with:
  echo python -m pip install pyinstaller
  pause
  exit /b 1
)
echo.
echo Built: dist\FrameScope\FrameScope.exe
pause
