@echo off
cd /d "%~dp0"
python -m PyInstaller --noconfirm --onefile --windowed --clean --name FrameScope --add-binary "tools\PresentMon\PresentMon.exe;." --collect-binaries=python3 fps_monitor.py --icon=app.ico
if errorlevel 1 (
echo.
echo Build failed!
echo Install PyInstaller first: python -m pip install pyinstaller
pause
exit /b 1
)
echo.
echo Build success!
echo File: dist\FrameScope.exe
pause