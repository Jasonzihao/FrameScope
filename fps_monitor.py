import csv
import ctypes
import json
import math
import os
import queue
import shutil
import sys
import statistics
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("TkAgg")

import matplotlib.pyplot as plt
import psutil
import tkinter as tk
import tkinter.font as tkfont
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from tkinter import filedialog, messagebox, ttk


APP_NAME = "FrameScope"
SAMPLE_INTERVAL_SECONDS = 1.0
MAX_VISIBLE_POINTS = 180
TEMP_REFRESH_SECONDS = 5.0
DEFAULT_SETTINGS = {
    "output_dir": "records",
    "language": "zh",
}
WINDOW_BG = "#0b0f14"
PANEL_BG = "#121821"
PANEL_RAISED_BG = "#171f2a"
PANEL_BORDER = "#2b3644"
TEXT_PRIMARY = "#f4f7fb"
TEXT_MUTED = "#9daab8"
ACCENT_GREEN = "#4ade80"
ACCENT_BLUE = "#4ea1ff"
ACCENT_AMBER = "#f6b44b"
ACCENT_RED = "#ef6357"
ACCENT_PURPLE = "#b985ff"
ACCENT_CYAN = "#48d4c2"
UI_FONT_FAMILY = "Microsoft YaHei UI" if os.name == "nt" else "Segoe UI"
MPL_FONT_FAMILIES = ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Segoe UI", "Arial", "sans-serif"]

plt.rcParams["font.sans-serif"] = MPL_FONT_FAMILIES
plt.rcParams["axes.unicode_minus"] = False

I18N = {
    "zh": {
        "subtitle": "点击开始记录，点击结束生成 CSV、图表和 HTML 报告。",
        "idle": "待机",
        "recording": "REC",
        "starting": "启动中...",
        "generating": "生成中...",
        "start": "开始",
        "end": "结束并生成",
        "settings": "设置",
        "open_records": "打开记录目录",
        "fps": "实时 FPS",
        "low": "1% Low",
        "cpu": "CPU 占用",
        "gpu": "GPU 占用",
        "cpu_temp": "CPU 温度",
        "gpu_temp": "GPU 温度",
        "usage": "CPU / GPU 使用率",
        "temperature": "温度",
        "memory": "内存 / 显存",
        "output": "输出",
        "gpu_ok": "GPU: nvidia-smi 已连接",
        "gpu_missing": "GPU: 未检测到 nvidia-smi",
        "fps_ok": "FPS: PresentMon 已连接",
        "fps_missing": "FPS: 未检测到 PresentMon.exe",
        "fps_admin": "FPS: 需要管理员权限",
        "admin_title": "需要管理员权限",
        "admin_message": "FPS 采集依赖 Windows ETW，需要管理员权限。是否重启并请求权限？",
        "no_recording": "当前没有正在记录的会话。",
        "recording_active": "记录中不能修改设置。",
        "report_ready": "报告已生成：",
        "settings_title": "设置",
        "output_dir": "数据保存位置",
        "browse": "选择",
        "language": "语言",
        "save": "保存",
        "cancel": "取消",
        "saved": "设置已保存。",
        "language_zh": "中文",
        "language_en": "English",
        "report_title": "性能报告",
        "created": "生成时间",
        "duration": "记录时长",
        "samples": "采样点",
        "avg_fps": "平均 FPS",
        "avg_cpu": "平均 CPU",
        "avg_gpu": "平均 GPU",
        "metric": "指标",
        "average": "平均",
        "minimum": "最低",
        "maximum": "最高",
        "cpu_usage": "CPU 占用",
        "gpu_usage": "GPU 占用",
    },
    "en": {
        "subtitle": "Press Start to record, then End to export CSV, charts, and an HTML report.",
        "idle": "Idle",
        "recording": "REC",
        "starting": "Starting...",
        "generating": "Generating...",
        "start": "Start",
        "end": "End & Export",
        "settings": "Settings",
        "open_records": "Open Data Folder",
        "fps": "Live FPS",
        "low": "1% Low",
        "cpu": "CPU Usage",
        "gpu": "GPU Usage",
        "cpu_temp": "CPU Temp",
        "gpu_temp": "GPU Temp",
        "usage": "CPU / GPU Usage",
        "temperature": "Temperature",
        "memory": "Memory / VRAM",
        "output": "Output",
        "gpu_ok": "GPU: nvidia-smi connected",
        "gpu_missing": "GPU: nvidia-smi not found",
        "fps_ok": "FPS: PresentMon connected",
        "fps_missing": "FPS: PresentMon.exe not found",
        "fps_admin": "FPS: administrator required",
        "admin_title": "Administrator Required",
        "admin_message": "FPS capture uses Windows ETW and needs administrator permission. Restart with elevation now?",
        "no_recording": "No recording session is active.",
        "recording_active": "Settings cannot be changed while recording.",
        "report_ready": "Report generated:",
        "settings_title": "Settings",
        "output_dir": "Data folder",
        "browse": "Browse",
        "language": "Language",
        "save": "Save",
        "cancel": "Cancel",
        "saved": "Settings saved.",
        "language_zh": "中文",
        "language_en": "English",
        "report_title": "Performance Report",
        "created": "Created",
        "duration": "Duration",
        "samples": "Samples",
        "avg_fps": "Average FPS",
        "avg_cpu": "Average CPU",
        "avg_gpu": "Average GPU",
        "metric": "Metric",
        "average": "Average",
        "minimum": "Minimum",
        "maximum": "Maximum",
        "cpu_usage": "CPU Usage",
        "gpu_usage": "GPU Usage",
    },
}


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def settings_path() -> Path:
    return app_base_dir() / "framescope_settings.json"


def load_settings() -> dict[str, str]:
    settings = DEFAULT_SETTINGS.copy()
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings
    if isinstance(data, dict):
        output_dir = data.get("output_dir")
        language = data.get("language")
        if isinstance(output_dir, str) and output_dir.strip():
            settings["output_dir"] = output_dir
        if language in I18N:
            settings["language"] = language
    return settings


def save_settings(settings: dict[str, str]) -> None:
    settings_path().write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def tr(language: str, key: str) -> str:
    return I18N.get(language, I18N["zh"]).get(key, I18N["zh"].get(key, key))


def is_windows_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    if os.name != "nt" or is_windows_admin():
        return False
    if getattr(sys, "frozen", False):
        executable = sys.executable
        params = subprocess.list2cmdline(sys.argv[1:])
    else:
        executable = sys.executable
        params = subprocess.list2cmdline([str(Path(__file__).resolve()), *sys.argv[1:]])
    try:
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
    except Exception:
        return False
    if result > 32:
        sys.exit(0)
    return False


@dataclass
class MetricSample:
    timestamp: str
    elapsed_s: float
    cpu_percent: float | None = None
    cpu_temp_c: float | None = None
    memory_percent: float | None = None
    gpu_percent: float | None = None
    gpu_temp_c: float | None = None
    gpu_memory_used_mb: float | None = None
    gpu_memory_total_mb: float | None = None
    gpu_power_w: float | None = None
    fps: float | None = None


def numeric_value(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def format_metric(value: float | None, suffix: str = "", precision: int = 0) -> str:
    number = numeric_value(value)
    if number is None:
        return "--"
    if precision == 0:
        return f"{number:.0f}{suffix}"
    return f"{number:.{precision}f}{suffix}"


def low_fps_from_frame_times(frame_times_ms: Iterable[float | None], percentile: float = 0.01) -> float | None:
    clean = [value for value in (numeric_value(item) for item in frame_times_ms) if value is not None and value > 0]
    if not clean:
        return None
    slow_count = max(1, math.ceil(len(clean) * percentile))
    slowest_frame_times = sorted(clean, reverse=True)[:slow_count]
    average_frame_time = statistics.fmean(slowest_frame_times)
    return round(1000.0 / average_frame_time, 2) if average_frame_time > 0 else None


def low_fps_from_fps_values(values: Iterable[float | None], percentile: float = 0.01) -> float | None:
    frame_times = []
    for item in values:
        fps = numeric_value(item)
        if fps is not None and fps > 0:
            frame_times.append(1000.0 / fps)
    return low_fps_from_frame_times(frame_times, percentile)


def low_fps_series(samples: Iterable["MetricSample"], percentile: float = 0.01) -> list[float | None]:
    running_frame_times: list[float] = []
    lows: list[float | None] = []
    for sample in samples:
        fps = numeric_value(sample.fps)
        if fps is not None and fps > 0:
            running_frame_times.append(1000.0 / fps)
        lows.append(low_fps_from_frame_times(running_frame_times, percentile))
    return lows


class TemperatureReader:
    def __init__(self) -> None:
        self.last_value: float | None = None
        self.last_refresh = 0.0
        self._lock = threading.Lock()
        self._probing = False

    def read_cpu_temp(self) -> float | None:
        now = time.monotonic()
        with self._lock:
            if now - self.last_refresh < TEMP_REFRESH_SECONDS or self._probing:
                return self.last_value
            self._probing = True
        threading.Thread(target=self._refresh_cpu_temp, daemon=True).start()
        return self.last_value

    def _refresh_cpu_temp(self) -> None:
        value = self._read_from_psutil() or self._read_from_hardware_monitor() or self._read_from_acpi()
        with self._lock:
            self.last_value = value
            self.last_refresh = time.monotonic()
            self._probing = False

    def wait_for_probe(self, timeout: float = 0.2) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not self._probing:
                    return
            time.sleep(0.02)

    @property
    def probing(self) -> bool:
        with self._lock:
            return self._probing

    def current_value(self) -> float | None:
        with self._lock:
            return self.last_value

    def _read_from_psutil(self) -> float | None:
        sensors = getattr(psutil, "sensors_temperatures", None)
        if sensors is None:
            return None
        try:
            all_sensors = sensors()
        except Exception:
            return None
        names = ("cpu", "package", "tctl", "tdie", "core")
        for sensor_entries in all_sensors.values():
            for entry in sensor_entries:
                label = f"{getattr(entry, 'label', '')}".lower()
                current = numeric_value(getattr(entry, "current", None))
                if current is not None and any(name in label for name in names):
                    return current
        return None

    def _read_from_hardware_monitor(self) -> float | None:
        namespaces = ("root\\LibreHardwareMonitor", "root\\OpenHardwareMonitor")
        for namespace in namespaces:
            script = (
                f"Get-CimInstance -Namespace '{namespace}' -ClassName Sensor "
                "| Where-Object { $_.SensorType -eq 'Temperature' -and "
                "($_.Name -match 'CPU Package|CPU CCD|Tctl|Tdie|Core \\(Tctl/Tdie\\)|Core Max|CPU') } "
                "| Select-Object -First 1 -ExpandProperty Value"
            )
            value = self._run_powershell_number(script)
            if value is not None and 0 < value < 130:
                return value
        return None

    def _read_from_acpi(self) -> float | None:
        script = (
            "Get-CimInstance -Namespace 'root\\wmi' -ClassName MSAcpi_ThermalZoneTemperature "
            "| Select-Object -First 1 -ExpandProperty CurrentTemperature"
        )
        raw_value = self._run_powershell_number(script)
        if raw_value is None:
            return None
        celsius = raw_value / 10.0 - 273.15
        if 0 < celsius < 130:
            return celsius
        return None

    def _run_powershell_number(self, script: str) -> float | None:
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception:
            return None
        if completed.returncode != 0:
            return None
        for line in completed.stdout.splitlines():
            value = numeric_value(line.strip())
            if value is not None:
                return value
        return None


class NvidiaSmiReader:
    def __init__(self) -> None:
        self.executable = shutil.which("nvidia-smi")
        self.available = self.executable is not None

    def read(self) -> dict[str, float | None]:
        empty = {
            "gpu_percent": None,
            "gpu_temp_c": None,
            "gpu_memory_used_mb": None,
            "gpu_memory_total_mb": None,
            "gpu_power_w": None,
        }
        if not self.executable:
            return empty
        query = (
            "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw"
        )
        try:
            completed = subprocess.run(
                [self.executable, query, "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception:
            self.available = False
            return empty
        if completed.returncode != 0:
            self.available = False
            return empty
        line = completed.stdout.splitlines()[0] if completed.stdout.splitlines() else ""
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 5:
            return empty
        self.available = True
        return {
            "gpu_percent": numeric_value(parts[0]),
            "gpu_temp_c": numeric_value(parts[1]),
            "gpu_memory_used_mb": numeric_value(parts[2]),
            "gpu_memory_total_mb": numeric_value(parts[3]),
            "gpu_power_w": numeric_value(parts[4]),
        }


class PresentMonReader:
    def __init__(self, output_dir: Path) -> None:
        self.executable = self._find_executable()
        self.output_file = output_dir / "presentmon.csv"
        self.process: subprocess.Popen[str] | None = None
        self.available = self.executable is not None
        self.active = False
        self.position = 0
        self.frame_times_ms: list[float] = []
        self._header: list[str] | None = None
        self._lock = threading.Lock()
        self._read_index = 0
        self._stdout_thread: threading.Thread | None = None
        self._capture_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._chunk_index = 0
        self._wrote_master_header = False

    def _find_executable(self) -> str | None:
        candidates: list[Path] = []
        if getattr(sys, "frozen", False):
            app_dir = Path(sys.executable).resolve().parent
            candidates.extend(
                [
                    app_dir / "PresentMon.exe",
                    app_dir / "tools" / "PresentMon" / "PresentMon.exe",
                    Path(getattr(sys, "_MEIPASS", app_dir)) / "PresentMon.exe",
                ]
            )
        source_dir = Path(__file__).resolve().parent
        candidates.extend(
            [
                source_dir / "PresentMon.exe",
                source_dir / "tools" / "PresentMon" / "PresentMon.exe",
            ]
        )
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return shutil.which("PresentMon.exe") or shutil.which("PresentMon")

    def start(self) -> None:
        if not self.executable:
            return
        self.active = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self.process and self.process.poll() is None:
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.kill()
        if self._stdout_thread:
            self._stdout_thread.join(timeout=1)
        if self._capture_thread:
            self._capture_thread.join(timeout=5)
        self.active = False

    def read_current_fps(self) -> float | None:
        with self._lock:
            new_frame_times = self.frame_times_ms[self._read_index :]
            self._read_index = len(self.frame_times_ms)
            recent = self.frame_times_ms[-90:]
        if new_frame_times:
            average_frame_time = statistics.fmean(new_frame_times)
            if average_frame_time > 0:
                return 1000.0 / average_frame_time
        if recent:
            average_frame_time = statistics.fmean(recent)
            return 1000.0 / average_frame_time if average_frame_time > 0 else None
        return None

    def _consume_stdout(self) -> None:
        if not self.process or not self.process.stdout:
            return
        try:
            with self.output_file.open("w", encoding="utf-8-sig", newline="") as file_handle:
                for line in self.process.stdout:
                    file_handle.write(line)
                    file_handle.flush()
                    self._parse_presentmon_line(line)
        except OSError:
            for line in self.process.stdout:
                self._parse_presentmon_line(line)

    def _parse_presentmon_line(self, line: str) -> None:
        try:
            row = next(csv.reader([line.strip()]))
        except (csv.Error, StopIteration):
            return
        if not row:
            return
        lowered = [column.strip().lower() for column in row]
        if "msbetweenpresents" in lowered or "msuntildisplayed" in lowered:
            with self._lock:
                self._header = row
            return
        with self._lock:
            header = self._header
        if header is None:
            return
        index = self._frame_time_index(header)
        if index is None or index >= len(row):
            return
        value = numeric_value(row[index])
        if value is not None and 0 < value < 1000:
            with self._lock:
                self.frame_times_ms.append(value)

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            chunk_path = self.output_file.with_name(f"presentmon_{self._chunk_index:04d}.csv")
            self._chunk_index += 1
            command = [
                self.executable,
                "--output_file",
                str(chunk_path),
                "--no_console_stats",
                "--timed",
                "2",
                "--terminate_after_timed",
                "--stop_existing_session",
            ]
            try:
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                self.process.wait(timeout=8)
            except Exception:
                self.available = False
                self.active = False
                return
            if chunk_path.exists():
                self._parse_chunk_file(chunk_path)
                try:
                    chunk_path.unlink()
                except OSError:
                    pass
            if self.process and self.process.returncode not in (0, None):
                self.available = False
                self.active = False
                return

    def _parse_chunk_file(self, path: Path) -> None:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return
        if not lines:
            return
        try:
            with self.output_file.open("a", encoding="utf-8-sig", newline="") as master:
                for line in lines:
                    if not line.strip():
                        continue
                    is_header = "MsBetweenPresents" in line and "Application" in line
                    if is_header and self._wrote_master_header:
                        pass
                    else:
                        master.write(line + "\n")
                        if is_header:
                            self._wrote_master_header = True
                    self._parse_presentmon_line(line)
        except OSError:
            for line in lines:
                self._parse_presentmon_line(line)

    def _read_new_frame_times(self) -> list[float]:
        if not self.output_file.exists():
            return []
        try:
            with self.output_file.open("r", encoding="utf-8", errors="ignore", newline="") as file_handle:
                file_handle.seek(self.position)
                text = file_handle.read()
                self.position = file_handle.tell()
        except OSError:
            return []
        if not text.strip():
            return []
        rows = list(csv.reader(text.splitlines()))
        frame_times: list[float] = []
        for row in rows:
            if not row:
                continue
            lowered = [column.strip().lower() for column in row]
            if "msbetweenpresents" in lowered or "msuntildisplayed" in lowered:
                self._header = row
                continue
            if self._header is None:
                continue
            index = self._frame_time_index(self._header)
            if index is None or index >= len(row):
                continue
            value = numeric_value(row[index])
            if value is not None and 0 < value < 1000:
                frame_times.append(value)
        return frame_times

    def _frame_time_index(self, header: list[str]) -> int | None:
        names = [column.strip().lower().replace(" ", "") for column in header]
        candidates = ("msbetweenpresents", "msuntildisplayed", "msbetweenflip")
        for candidate in candidates:
            if candidate in names:
                return names.index(candidate)
        return None


class MetricsRecorder:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.temperature_reader = TemperatureReader()
        self.gpu_reader = NvidiaSmiReader()
        self.fps_reader = PresentMonReader(output_dir)
        self.samples: list[MetricSample] = []
        self.events: queue.Queue[MetricSample] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.started_at = time.monotonic()

    def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        psutil.cpu_percent(interval=None)
        self.fps_reader.start()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        self.temperature_reader.wait_for_probe(timeout=0.5)
        self.fps_reader.stop()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            sample = self.collect_once()
            self.samples.append(sample)
            self.events.put(sample)
            self._stop_event.wait(SAMPLE_INTERVAL_SECONDS)

    def collect_once(self) -> MetricSample:
        now = datetime.now()
        gpu = self.gpu_reader.read()
        return MetricSample(
            timestamp=now.isoformat(timespec="seconds"),
            elapsed_s=round(time.monotonic() - self.started_at, 2),
            cpu_percent=numeric_value(psutil.cpu_percent(interval=None)),
            cpu_temp_c=self.temperature_reader.read_cpu_temp(),
            memory_percent=numeric_value(psutil.virtual_memory().percent),
            gpu_percent=gpu["gpu_percent"],
            gpu_temp_c=gpu["gpu_temp_c"],
            gpu_memory_used_mb=gpu["gpu_memory_used_mb"],
            gpu_memory_total_mb=gpu["gpu_memory_total_mb"],
            gpu_power_w=gpu["gpu_power_w"],
            fps=self.fps_reader.read_current_fps(),
        )


class ReportWriter:
    def __init__(
        self,
        output_dir: Path,
        samples: list[MetricSample],
        frame_times_ms: list[float],
        language: str = "zh",
    ) -> None:
        self.output_dir = output_dir
        self.samples = samples
        self.frame_times_ms = frame_times_ms
        self.language = language if language in I18N else "zh"

    def write_all(self) -> dict[str, str]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.output_dir / "metrics.csv"
        summary_path = self.output_dir / "summary.json"
        chart_path = self.output_dir / "charts.png"
        html_path = self.output_dir / "report.html"
        summary = self._summary()
        self._write_csv(csv_path)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_chart(chart_path)
        self._write_html(html_path, summary, chart_path.name)
        return {
            "csv": str(csv_path),
            "summary": str(summary_path),
            "chart": str(chart_path),
            "html": str(html_path),
        }

    def _write_csv(self, path: Path) -> None:
        fieldnames = list(asdict(self.samples[0]).keys()) if self.samples else list(MetricSample("", 0).__dict__.keys())
        with path.open("w", encoding="utf-8-sig", newline="") as file_handle:
            writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
            writer.writeheader()
            for sample in self.samples:
                writer.writerow(asdict(sample))

    def _summary(self) -> dict[str, object]:
        duration = self.samples[-1].elapsed_s if self.samples else 0
        fps_values = [sample.fps for sample in self.samples if numeric_value(sample.fps) is not None]
        cpu_values = [sample.cpu_percent for sample in self.samples if numeric_value(sample.cpu_percent) is not None]
        gpu_values = [sample.gpu_percent for sample in self.samples if numeric_value(sample.gpu_percent) is not None]
        cpu_temps = [sample.cpu_temp_c for sample in self.samples if numeric_value(sample.cpu_temp_c) is not None]
        gpu_temps = [sample.gpu_temp_c for sample in self.samples if numeric_value(sample.gpu_temp_c) is not None]
        fps_analysis = self._fps_analysis(fps_values)
        return {
            "app": APP_NAME,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": round(duration, 2),
            "sample_count": len(self.samples),
            "fps": fps_analysis,
            "cpu_percent": self._series_stats(cpu_values),
            "gpu_percent": self._series_stats(gpu_values),
            "cpu_temp_c": self._series_stats(cpu_temps),
            "gpu_temp_c": self._series_stats(gpu_temps),
        }

    def _fps_analysis(self, fps_values: list[float | None]) -> dict[str, float | None]:
        clean_fps = [value for value in (numeric_value(item) for item in fps_values) if value is not None]
        result = self._series_stats(clean_fps)
        frame_times = [value for value in (numeric_value(item) for item in self.frame_times_ms) if value is not None]
        if frame_times:
            result["one_percent_low"] = low_fps_from_frame_times(frame_times, 0.01)
            result["point_one_percent_low"] = low_fps_from_frame_times(frame_times, 0.001)
        else:
            result["one_percent_low"] = low_fps_from_fps_values(clean_fps, 0.01)
            result["point_one_percent_low"] = low_fps_from_fps_values(clean_fps, 0.001)
        return result

    def _series_stats(self, values: Iterable[float | None]) -> dict[str, float | None]:
        clean = [value for value in (numeric_value(item) for item in values) if value is not None]
        if not clean:
            return {"avg": None, "min": None, "max": None, "p95": None}
        clean_sorted = sorted(clean)
        return {
            "avg": round(statistics.fmean(clean), 2),
            "min": round(min(clean), 2),
            "max": round(max(clean), 2),
            "p95": round(self._percentile(clean_sorted, 0.95), 2),
        }

    def _percentile(self, sorted_values: list[float], percentile: float) -> float:
        if not sorted_values:
            return 0.0
        index = min(len(sorted_values) - 1, max(0, round((len(sorted_values) - 1) * percentile)))
        return sorted_values[index]

    def _write_chart(self, path: Path) -> None:
        plt.style.use("dark_background")
        figure, axes = plt.subplots(2, 2, figsize=(14, 8), dpi=150)
        figure.patch.set_facecolor(WINDOW_BG)
        series = [
            ("FPS", ("fps", "fps_low"), ACCENT_GREEN, axes[0][0]),
            (f"{tr(self.language, 'usage')} %", ("cpu_percent", "gpu_percent"), ACCENT_BLUE, axes[0][1]),
            (f"{tr(self.language, 'temperature')} C", ("cpu_temp_c", "gpu_temp_c"), ACCENT_AMBER, axes[1][0]),
            ("GPU Power W", "gpu_power_w", ACCENT_PURPLE, axes[1][1]),
        ]
        elapsed = [sample.elapsed_s / 60 for sample in self.samples]
        for title, key, color, axis in series:
            axis.set_facecolor(PANEL_BG)
            axis.grid(True, color=PANEL_BORDER, linewidth=0.8, alpha=0.65)
            axis.tick_params(colors=TEXT_MUTED)
            axis.set_title(title, color=TEXT_PRIMARY, fontsize=12, pad=10)
            for spine in axis.spines.values():
                spine.set_color(PANEL_BORDER)
            if isinstance(key, tuple):
                labels = {
                    "fps": "FPS",
                    "fps_low": "1% Low",
                    "cpu_percent": "CPU",
                    "gpu_percent": "GPU",
                    "cpu_temp_c": "CPU",
                    "gpu_temp_c": "GPU",
                }
                colors = {
                    "fps": ACCENT_GREEN,
                    "fps_low": ACCENT_AMBER,
                    "cpu_percent": ACCENT_BLUE,
                    "gpu_percent": ACCENT_PURPLE,
                    "cpu_temp_c": ACCENT_AMBER,
                    "gpu_temp_c": ACCENT_RED,
                }
                for item in key:
                    if item == "fps_low":
                        values = low_fps_series(self.samples)
                    else:
                        values = [numeric_value(getattr(sample, item)) for sample in self.samples]
                    axis.plot(elapsed, values, color=colors[item], linewidth=2, label=labels[item])
                axis.legend(facecolor=PANEL_BG, edgecolor=PANEL_BORDER, labelcolor="#dce5ee")
            else:
                values = [numeric_value(getattr(sample, key)) for sample in self.samples]
                axis.plot(elapsed, values, color=color, linewidth=2)
            axis.set_xlabel("Minutes", color=TEXT_MUTED)
        figure.tight_layout(pad=2)
        figure.savefig(path, facecolor=figure.get_facecolor())
        plt.close(figure)

    def _write_html(self, path: Path, summary: dict[str, object], chart_name: str) -> None:
        fps = summary["fps"]
        cpu = summary["cpu_percent"]
        gpu = summary["gpu_percent"]
        cpu_temp = summary["cpu_temp_c"]
        gpu_temp = summary["gpu_temp_c"]
        language = self.language
        html_lang = "zh-CN" if language == "zh" else "en"
        html = f"""<!doctype html>
<html lang="{html_lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{APP_NAME} Report</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: {WINDOW_BG};
      --panel: {PANEL_RAISED_BG};
      --line: {PANEL_BORDER};
      --text: {TEXT_PRIMARY};
      --muted: {TEXT_MUTED};
      --green: {ACCENT_GREEN};
      --blue: {ACCENT_BLUE};
      --amber: {ACCENT_AMBER};
      --red: {ACCENT_RED};
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Segoe UI", Arial, sans-serif;
      background: radial-gradient(circle at 20% 0%, #162235 0, transparent 30rem), var(--bg);
      color: var(--text);
    }}
    main {{ width: min(1180px, calc(100% - 40px)); margin: 32px auto 48px; }}
    header {{ display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }}
    h1 {{ font-size: 34px; margin: 0 0 6px; letter-spacing: 0; }}
    p {{ color: var(--muted); margin: 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 20px; }}
    .card {{ background: color-mix(in srgb, var(--panel) 92%, black); border: 1px solid var(--line); border-radius: 8px; padding: 18px; }}
    .label {{ color: var(--muted); font-size: 13px; }}
    .value {{ font-size: 28px; font-weight: 700; margin-top: 8px; }}
    .chart {{ width: 100%; border-radius: 8px; border: 1px solid var(--line); background: var(--bg); }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; overflow: hidden; border-radius: 8px; }}
    th, td {{ text-align: left; padding: 13px 14px; border-bottom: 1px solid var(--line); }}
    th {{ color: var(--muted); font-weight: 600; background: {PANEL_BG}; }}
    td {{ background: #101721; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} header {{ display: block; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>{APP_NAME} {tr(language, "report_title")}</h1>
      <p>{tr(language, "created")} {summary["created_at"]} | {tr(language, "duration")} {summary["duration_seconds"]} s | {tr(language, "samples")} {summary["sample_count"]}</p>
    </div>
  </header>
  <section class="grid">
    <div class="card"><div class="label">{tr(language, "avg_fps")}</div><div class="value">{format_metric(fps["avg"], "", 1)}</div></div>
    <div class="card"><div class="label">1% Low FPS</div><div class="value">{format_metric(fps["one_percent_low"], "", 1)}</div></div>
    <div class="card"><div class="label">{tr(language, "avg_cpu")}</div><div class="value">{format_metric(cpu["avg"], "%", 1)}</div></div>
    <div class="card"><div class="label">{tr(language, "avg_gpu")}</div><div class="value">{format_metric(gpu["avg"], "%", 1)}</div></div>
  </section>
  <img class="chart" src="{chart_name}" alt="Performance charts">
  <table>
    <thead><tr><th>{tr(language, "metric")}</th><th>{tr(language, "average")}</th><th>{tr(language, "minimum")}</th><th>{tr(language, "maximum")}</th><th>P95</th></tr></thead>
    <tbody>
      <tr><td>FPS</td><td>{format_metric(fps["avg"], "", 2)}</td><td>{format_metric(fps["min"], "", 2)}</td><td>{format_metric(fps["max"], "", 2)}</td><td>{format_metric(fps["p95"], "", 2)}</td></tr>
      <tr><td>{tr(language, "cpu_usage")}</td><td>{format_metric(cpu["avg"], "%", 2)}</td><td>{format_metric(cpu["min"], "%", 2)}</td><td>{format_metric(cpu["max"], "%", 2)}</td><td>{format_metric(cpu["p95"], "%", 2)}</td></tr>
      <tr><td>{tr(language, "gpu_usage")}</td><td>{format_metric(gpu["avg"], "%", 2)}</td><td>{format_metric(gpu["min"], "%", 2)}</td><td>{format_metric(gpu["max"], "%", 2)}</td><td>{format_metric(gpu["p95"], "%", 2)}</td></tr>
      <tr><td>{tr(language, "cpu_temp")}</td><td>{format_metric(cpu_temp["avg"], " C", 2)}</td><td>{format_metric(cpu_temp["min"], " C", 2)}</td><td>{format_metric(cpu_temp["max"], " C", 2)}</td><td>{format_metric(cpu_temp["p95"], " C", 2)}</td></tr>
      <tr><td>{tr(language, "gpu_temp")}</td><td>{format_metric(gpu_temp["avg"], " C", 2)}</td><td>{format_metric(gpu_temp["min"], " C", 2)}</td><td>{format_metric(gpu_temp["max"], " C", 2)}</td><td>{format_metric(gpu_temp["p95"], " C", 2)}</td></tr>
    </tbody>
  </table>
</main>
</body>
</html>"""
        path.write_text(html, encoding="utf-8")


class MetricCard(ttk.Frame):
    def __init__(self, parent: tk.Widget, title: str, accent: str) -> None:
        super().__init__(parent, style="Card.TFrame")
        self.title = ttk.Label(self, text=title, style="CardTitle.TLabel")
        self.value = ttk.Label(self, text="--", style="CardValue.TLabel")
        self.accent = tk.Frame(self, bg=accent, height=4)
        self.columnconfigure(0, weight=1)
        self.accent.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 14))
        self.title.grid(row=1, column=0, sticky="w", padx=18)
        self.value.grid(row=2, column=0, sticky="w", padx=18, pady=(7, 18))

    def set_value(self, value: str) -> None:
        self.value.configure(text=value)

    def set_title(self, title: str) -> None:
        self.title.configure(text=title)


class MonitorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.settings = load_settings()
        self.language = self.settings["language"]
        self.root.title(APP_NAME)
        self.root.geometry("1240x800")
        self.root.minsize(1040, 680)
        self.root.configure(bg=WINDOW_BG)
        self.session_dir: Path | None = None
        self.recorder: MetricsRecorder | None = None
        self.visible_samples: deque[MetricSample] = deque(maxlen=MAX_VISIBLE_POINTS)
        self.report_paths: dict[str, str] | None = None
        self.recording = False
        self.closed = False
        self.gpu_available = NvidiaSmiReader().available
        self.presentmon_available = PresentMonReader(app_base_dir()).available
        self._configure_style()
        self._build_ui()
        self.apply_language()
        self.end_button.state(["disabled"])
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._update_loop()

    def text(self, key: str) -> str:
        return tr(self.language, key)

    def output_root(self) -> Path:
        configured = Path(self.settings["output_dir"]).expanduser()
        if configured.is_absolute():
            return configured
        return app_base_dir() / configured

    def _configure_style(self) -> None:
        for font_name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(font_name).configure(family=UI_FONT_FAMILY)
            except tk.TclError:
                pass
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=WINDOW_BG, foreground=TEXT_PRIMARY, font=(UI_FONT_FAMILY, 10))
        style.configure("Header.TLabel", background=WINDOW_BG, foreground=TEXT_PRIMARY, font=(UI_FONT_FAMILY, 28, "bold"))
        style.configure("Muted.TLabel", background=WINDOW_BG, foreground=TEXT_MUTED, font=(UI_FONT_FAMILY, 10))
        style.configure(
            "Status.TLabel",
            background=PANEL_RAISED_BG,
            foreground="#dce5ee",
            padding=(14, 8),
            borderwidth=1,
            relief="solid",
        )
        style.configure("Card.TFrame", background=PANEL_RAISED_BG, relief="solid", borderwidth=1)
        style.configure("CardTitle.TLabel", background=PANEL_RAISED_BG, foreground=TEXT_MUTED, font=(UI_FONT_FAMILY, 10))
        style.configure("CardValue.TLabel", background=PANEL_RAISED_BG, foreground=TEXT_PRIMARY, font=(UI_FONT_FAMILY, 26, "bold"))
        style.configure(
            "Action.TButton",
            background=ACCENT_BLUE,
            foreground="#ffffff",
            borderwidth=0,
            padding=(18, 11),
            font=(UI_FONT_FAMILY, 10, "bold"),
        )
        style.map("Action.TButton", background=[("disabled", "#334154"), ("active", "#67b0ff")])
        style.configure(
            "Danger.TButton",
            background=ACCENT_RED,
            foreground="#ffffff",
            borderwidth=0,
            padding=(18, 11),
            font=(UI_FONT_FAMILY, 10, "bold"),
        )
        style.map("Danger.TButton", background=[("disabled", "#3d3032"), ("active", "#ff7b70")])
        style.configure(
            "Ghost.TButton",
            background=PANEL_RAISED_BG,
            foreground="#dce5ee",
            borderwidth=1,
            relief="solid",
            padding=(15, 11),
            font=(UI_FONT_FAMILY, 10),
        )
        style.map("Ghost.TButton", background=[("disabled", "#18202a"), ("active", "#223044")])

    def _build_ui(self) -> None:
        container = tk.Frame(self.root, bg=WINDOW_BG)
        container.pack(fill="both", expand=True, padx=28, pady=24)
        header = tk.Frame(container, bg=WINDOW_BG)
        header.pack(fill="x")
        title_area = tk.Frame(header, bg=WINDOW_BG)
        title_area.pack(side="left", fill="x", expand=True)
        ttk.Label(title_area, text=APP_NAME, style="Header.TLabel").pack(anchor="w")
        self.subtitle_label = ttk.Label(title_area, style="Muted.TLabel")
        self.subtitle_label.pack(anchor="w", pady=(2, 0))
        actions = tk.Frame(header, bg=WINDOW_BG)
        actions.pack(side="right")
        self.status_label = ttk.Label(actions, style="Status.TLabel")
        self.status_label.pack(side="left", padx=(0, 10))
        self.open_button = ttk.Button(actions, style="Ghost.TButton", command=self.open_records_dir)
        self.open_button.pack(side="left", padx=(0, 8))
        self.settings_button = ttk.Button(actions, style="Ghost.TButton", command=self.open_settings)
        self.settings_button.pack(side="left", padx=(0, 8))
        self.start_button = ttk.Button(actions, style="Action.TButton", command=self.start_recording)
        self.start_button.pack(side="left", padx=(0, 8))
        self.end_button = ttk.Button(actions, style="Danger.TButton", command=self.finish_recording)
        self.end_button.pack(side="left")

        cards = tk.Frame(container, bg=WINDOW_BG)
        cards.pack(fill="x", pady=(24, 20))
        for column in range(6):
            cards.columnconfigure(column, weight=1, uniform="cards")
        self.cards = {
            "fps": MetricCard(cards, "", ACCENT_GREEN),
            "low": MetricCard(cards, "", ACCENT_AMBER),
            "cpu": MetricCard(cards, "", ACCENT_BLUE),
            "gpu": MetricCard(cards, "", ACCENT_PURPLE),
            "cpu_temp": MetricCard(cards, "", ACCENT_RED),
            "gpu_temp": MetricCard(cards, "", ACCENT_CYAN),
        }
        for index, card in enumerate(self.cards.values()):
            card.grid(row=0, column=index, sticky="nsew", padx=6)

        chart_frame = tk.Frame(container, bg=PANEL_BG, highlightbackground=PANEL_BORDER, highlightthickness=1)
        chart_frame.pack(fill="both", expand=True)
        self.figure, self.axes = plt.subplots(2, 2, figsize=(11, 6), dpi=100)
        self.figure.patch.set_facecolor(PANEL_BG)
        self.lines: dict[str, object] = {}
        self.axis_title_keys = {
            self.axes[0][0]: "fps",
            self.axes[0][1]: "usage",
            self.axes[1][0]: "temperature",
            self.axes[1][1]: "memory",
        }
        axis_specs = [
            (self.axes[0][0], [("fps", ACCENT_GREEN, "FPS"), ("fps_low", ACCENT_AMBER, "1% Low")]),
            (self.axes[0][1], [("cpu_percent", ACCENT_BLUE, "CPU"), ("gpu_percent", ACCENT_PURPLE, "GPU")]),
            (self.axes[1][0], [("cpu_temp_c", ACCENT_RED, "CPU"), ("gpu_temp_c", ACCENT_CYAN, "GPU")]),
            (self.axes[1][1], [("memory_percent", ACCENT_AMBER, "RAM %"), ("gpu_memory_used_mb", "#85c1e9", "VRAM MB")]),
        ]
        for axis, line_specs in axis_specs:
            axis.set_facecolor(PANEL_BG)
            axis.grid(True, color=PANEL_BORDER, linewidth=0.8, alpha=0.7)
            axis.tick_params(colors=TEXT_MUTED)
            for spine in axis.spines.values():
                spine.set_color(PANEL_BORDER)
            for key, color, label in line_specs:
                line, = axis.plot([], [], color=color, linewidth=2, label=label)
                self.lines[key] = line
            axis.legend(facecolor=PANEL_BG, edgecolor=PANEL_BORDER, labelcolor="#dce5ee", loc="upper left")
        self.figure.tight_layout(pad=2)
        self.canvas = FigureCanvasTkAgg(self.figure, chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=12, pady=12)

        footer = tk.Frame(container, bg=WINDOW_BG)
        footer.pack(fill="x", pady=(12, 0))
        self.source_label = ttk.Label(footer, style="Muted.TLabel")
        self.source_label.pack(side="left")
        self.output_label = ttk.Label(footer, style="Muted.TLabel")
        self.output_label.pack(side="right")

    def apply_language(self) -> None:
        self.subtitle_label.configure(text=self.text("subtitle"))
        self.open_button.configure(text=self.text("open_records"))
        self.settings_button.configure(text=self.text("settings"))
        self.start_button.configure(text=self.text("start"))
        self.end_button.configure(text=self.text("end"))
        for key, card in self.cards.items():
            card.set_title(self.text(key))
        for axis, key in self.axis_title_keys.items():
            axis.set_title(self.text(key), color=TEXT_PRIMARY, fontsize=11)
        self.output_label.configure(text=f"{self.text('output')}: {self.output_root()}")
        self.source_label.configure(text=self._source_text())
        self._update_status_label()
        self.canvas.draw_idle()

    def _source_text(self) -> str:
        gpu_available = self.recorder.gpu_reader.available if self.recorder else self.gpu_available
        fps_available = self.recorder.fps_reader.available if self.recorder else self.presentmon_available
        gpu_status = self.text("gpu_ok") if gpu_available else self.text("gpu_missing")
        if fps_available and not is_windows_admin():
            fps_status = self.text("fps_admin")
        else:
            fps_status = self.text("fps_ok") if fps_available else self.text("fps_missing")
        return f"{gpu_status}    {fps_status}"

    def _update_status_label(self) -> None:
        if self.recording and self.recorder:
            elapsed = int(time.monotonic() - self.recorder.started_at)
            self.status_label.configure(text=f"{self.text('recording')} {elapsed // 60:02d}:{elapsed % 60:02d}")
        else:
            self.status_label.configure(text=self.text("idle"))

    def start_recording(self) -> None:
        if self.recording:
            return
        if self.presentmon_available and not is_windows_admin():
            if messagebox.askyesno(self.text("admin_title"), self.text("admin_message")):
                relaunch_as_admin()
                return
        self.status_label.configure(text=self.text("starting"))
        self.root.update_idletasks()
        self.session_dir = self.output_root() / datetime.now().strftime("session_%Y%m%d_%H%M%S")
        self.recorder = MetricsRecorder(self.session_dir)
        self.visible_samples.clear()
        self.report_paths = None
        self.reset_cards()
        self.clear_chart()
        self.recorder.start()
        self.gpu_available = self.recorder.gpu_reader.available
        self.presentmon_available = self.recorder.fps_reader.available
        self.recording = True
        self.start_button.state(["disabled"])
        self.end_button.state(["!disabled"])
        self.settings_button.state(["disabled"])
        self.output_label.configure(text=f"{self.text('output')}: {self.session_dir}")
        self.source_label.configure(text=self._source_text())

    def finish_recording(self) -> None:
        if not self.recording or not self.recorder or not self.session_dir:
            messagebox.showinfo(APP_NAME, self.text("no_recording"))
            return
        self.status_label.configure(text=self.text("generating"))
        self.root.update_idletasks()
        self.recorder.stop()
        writer = ReportWriter(
            self.session_dir,
            self.recorder.samples,
            self.recorder.fps_reader.frame_times_ms,
            self.language,
        )
        self.report_paths = writer.write_all()
        self.recording = False
        self.start_button.state(["!disabled"])
        self.end_button.state(["disabled"])
        self.settings_button.state(["!disabled"])
        self._update_status_label()
        self.source_label.configure(text=self._source_text())
        try:
            os.startfile(Path(self.report_paths["html"]).resolve())
        except OSError:
            pass
        messagebox.showinfo(APP_NAME, f"{self.text('report_ready')}\n{self.report_paths['html']}")

    def open_settings(self) -> None:
        if self.recording:
            messagebox.showinfo(APP_NAME, self.text("recording_active"))
            return
        window = tk.Toplevel(self.root)
        window.title(self.text("settings_title"))
        window.configure(bg=WINDOW_BG)
        window.resizable(False, False)
        window.transient(self.root)
        window.grab_set()
        frame = tk.Frame(window, bg=WINDOW_BG, padx=22, pady=22)
        frame.pack(fill="both", expand=True)
        path_var = tk.StringVar(value=str(self.output_root()))
        language_var = tk.StringVar(value=self.language)

        ttk.Label(frame, text=self.text("output_dir"), style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        path_entry = ttk.Entry(frame, textvariable=path_var, width=54)
        path_entry.grid(row=1, column=0, sticky="ew", padx=(0, 10))

        def browse() -> None:
            selected = filedialog.askdirectory(initialdir=path_var.get() or str(app_base_dir()))
            if selected:
                path_var.set(selected)

        ttk.Button(frame, text=self.text("browse"), style="Ghost.TButton", command=browse).grid(row=1, column=1, sticky="ew")
        ttk.Label(frame, text=self.text("language"), style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(18, 6))
        language_box = ttk.Combobox(
            frame,
            textvariable=language_var,
            values=["zh", "en"],
            state="readonly",
            width=12,
        )
        language_box.grid(row=3, column=0, sticky="w")
        hint = ttk.Label(frame, text=f"zh = {self.text('language_zh')}    en = {self.text('language_en')}", style="Muted.TLabel")
        hint.grid(row=3, column=0, sticky="w", padx=(110, 0))

        buttons = tk.Frame(frame, bg=WINDOW_BG)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(22, 0))

        def save() -> None:
            output_dir = path_var.get().strip()
            if not output_dir:
                output_dir = str(app_base_dir() / DEFAULT_SETTINGS["output_dir"])
            language = language_var.get() if language_var.get() in I18N else "zh"
            self.settings = {"output_dir": output_dir, "language": language}
            self.language = language
            save_settings(self.settings)
            self.apply_language()
            messagebox.showinfo(APP_NAME, self.text("saved"))
            window.destroy()

        ttk.Button(buttons, text=self.text("cancel"), style="Ghost.TButton", command=window.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text=self.text("save"), style="Action.TButton", command=save).pack(side="left")

    def _update_loop(self) -> None:
        if self.recording and self.recorder:
            while True:
                try:
                    sample = self.recorder.events.get_nowait()
                except queue.Empty:
                    break
                self.visible_samples.append(sample)
            self._update_cards()
            self._update_chart()
        self._update_status_label()
        self.source_label.configure(text=self._source_text())
        if not self.closed:
            self.root.after(1000, self._update_loop)

    def reset_cards(self) -> None:
        for card in self.cards.values():
            card.set_value("--")

    def clear_chart(self) -> None:
        for line in self.lines.values():
            line.set_data([], [])
        for axis in self.axes.flat:
            axis.relim()
            axis.autoscale_view()
            axis.set_xlim(0, MAX_VISIBLE_POINTS)
        self.canvas.draw_idle()

    def _update_cards(self) -> None:
        if not self.visible_samples or not self.recorder:
            return
        latest = self.visible_samples[-1]
        all_fps = [sample.fps for sample in self.recorder.samples if numeric_value(sample.fps) is not None]
        with self.recorder.fps_reader._lock:
            frame_times = list(self.recorder.fps_reader.frame_times_ms)
        one_percent_low = low_fps_from_frame_times(frame_times, 0.01) or low_fps_from_fps_values(all_fps, 0.01)
        self.cards["fps"].set_value(format_metric(latest.fps, "", 1))
        self.cards["low"].set_value(format_metric(one_percent_low, "", 1))
        self.cards["cpu"].set_value(format_metric(latest.cpu_percent, "%", 0))
        self.cards["gpu"].set_value(format_metric(latest.gpu_percent, "%", 0))
        self.cards["cpu_temp"].set_value(format_metric(latest.cpu_temp_c, " C", 0))
        self.cards["gpu_temp"].set_value(format_metric(latest.gpu_temp_c, " C", 0))

    def _update_chart(self) -> None:
        if not self.visible_samples:
            return
        x_values = [sample.elapsed_s for sample in self.visible_samples]
        for key, line in self.lines.items():
            if key == "fps_low":
                y_values = low_fps_series(self.visible_samples)
            else:
                y_values = [numeric_value(getattr(sample, key)) for sample in self.visible_samples]
            line.set_data(x_values, y_values)
        for axis in self.axes.flat:
            axis.relim()
            axis.autoscale_view()
            if x_values:
                axis.set_xlim(max(0, x_values[-1] - MAX_VISIBLE_POINTS), max(MAX_VISIBLE_POINTS, x_values[-1]))
        self.canvas.draw_idle()

    def open_records_dir(self) -> None:
        target = self.session_dir if self.session_dir and self.session_dir.exists() else self.output_root()
        target.mkdir(parents=True, exist_ok=True)
        os.startfile(target.resolve())

    def on_close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.recording:
            self.finish_recording()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = MonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
