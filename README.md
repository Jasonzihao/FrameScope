# FrameScope

FrameScope 是一个 Windows 本地性能记录工具。打开后自动记录，点击“结束并生成”或直接关闭窗口后，会在 `records/session_日期_时间/` 生成：

- `metrics.csv`：完整采样数据
- `summary.json`：均值、最低、最高、P95、1% Low 等统计
- `charts.png`：曲线图
- `report.html`：可直接打开的可视化报告

## 运行

```bat
run.bat
```

或：

```bat
python fps_monitor.py
```

首次打开 EXE 时会弹出 Windows 管理员权限确认。FPS 采集依赖 Windows ETW，PresentMon 没有管理员权限会返回 `access denied`，因此必须允许该权限。

## FPS 记录

Windows 没有稳定的通用内置 FPS API。FrameScope 会自动寻找当前目录或 PATH 中的 `PresentMon.exe`：

- 找到 `PresentMon.exe`：记录真实 FPS，并计算 1% Low / 0.1% Low。
- 没找到 `PresentMon.exe`：CPU、GPU、内存、温度、功耗照常记录，FPS 显示为空。

项目已经在 `tools/PresentMon/PresentMon.exe` 放入官方 x64 版本。打包后会复制到 `dist/FrameScope/_internal/PresentMon.exe`，软件会自动接入。

## 温度与 GPU

- NVIDIA 显卡通过 `nvidia-smi` 读取 GPU 占用、温度、显存、功耗。
- CPU 温度会尝试读取 LibreHardwareMonitor / OpenHardwareMonitor / ACPI。部分主板或系统权限下可能不可用。

## 打包 EXE

如果已安装 PyInstaller：

```bat
build_exe.bat
```

生成位置：

```text
dist\FrameScope\FrameScope.exe
```
