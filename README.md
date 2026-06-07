# FrameScope

FrameScope is a Windows desktop performance recorder for FPS, low FPS, CPU/GPU usage, temperature, memory, VRAM, and GPU power.

打开软件后默认不会开始记录。点击 **开始** 后开始采样，点击 **结束并生成** 后会导出本次会话数据和报告。

## Features

- Start/End recording from the app UI.
- Live charts for FPS, CPU/GPU usage, temperatures, RAM, and VRAM.
- Session export as `metrics.csv`, `summary.json`, `charts.png`, and `report.html`.
- Settings dialog for data folder and language.
- Chinese and English UI/report text.
- PresentMon integration for real FPS and 1% / 0.1% low FPS.

## Run From Source

```bat
run.bat
```

or:

```bat
python fps_monitor.py
```

## Build EXE

```bat
build_exe.bat
```

The app is generated at:

```text
dist\FrameScope\FrameScope.exe
```

## FPS Capture

FrameScope uses Intel PresentMon to capture real FPS on Windows. The official x64 binary is placed at:

```text
tools\PresentMon\PresentMon.exe
```

PyInstaller copies it into the packaged app under:

```text
dist\FrameScope\_internal\PresentMon.exe
```

FPS capture requires Windows ETW access, so administrator permission is required. The app does not request elevation on launch; it prompts only when you click **开始 / Start** and FPS capture is available.

If you decline the administrator prompt, CPU/GPU/temperature data can still be recorded, but FPS will be empty.

## Settings

Use **设置 / Settings** in the app to change:

- Data folder
- Language: `zh` or `en`

Settings are stored locally in `framescope_settings.json`, which is ignored by Git.

## Notes

- NVIDIA GPU metrics are read through `nvidia-smi`.
- CPU temperature support depends on the motherboard and available Windows sensors. LibreHardwareMonitor/OpenHardwareMonitor/ACPI are attempted when available.
