import csv
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
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from tkinter import messagebox, ttk


APP_NAME = "FrameScope"
SAMPLE_INTERVAL_SECONDS = 1.0
MAX_VISIBLE_POINTS = 180
TEMP_REFRESH_SECONDS = 5.0


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
        commands = [
            [
                self.executable,
                "--output_file",
                str(self.output_file),
                "--no_console_stats",
                "--stop_existing_session",
            ],
        ]
        for command in commands:
            try:
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                time.sleep(0.8)
                if self.process.poll() is None or self.output_file.exists():
                    self.active = True
                    return
            except Exception:
                self.process = None
        self.available = False
        self.active = False

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.active = False

    def read_current_fps(self) -> float | None:
        new_frame_times = self._read_new_frame_times()
        if new_frame_times:
            self.frame_times_ms.extend(new_frame_times)
            average_frame_time = statistics.fmean(new_frame_times)
            if average_frame_time > 0:
                return 1000.0 / average_frame_time
        if self.frame_times_ms:
            recent = self.frame_times_ms[-90:]
            average_frame_time = statistics.fmean(recent)
            return 1000.0 / average_frame_time if average_frame_time > 0 else None
        return None

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
    def __init__(self, output_dir: Path, samples: list[MetricSample], frame_times_ms: list[float]) -> None:
        self.output_dir = output_dir
        self.samples = samples
        self.frame_times_ms = frame_times_ms

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
            result["one_percent_low"] = self._low_fps_from_frame_time(frame_times, 0.99)
            result["point_one_percent_low"] = self._low_fps_from_frame_time(frame_times, 0.999)
        else:
            result["one_percent_low"] = self._percentile_low(clean_fps, 0.01)
            result["point_one_percent_low"] = self._percentile_low(clean_fps, 0.001)
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

    def _percentile_low(self, values: list[float], percentile: float) -> float | None:
        if not values:
            return None
        sorted_values = sorted(values)
        index = min(len(sorted_values) - 1, max(0, round((len(sorted_values) - 1) * percentile)))
        return round(sorted_values[index], 2)

    def _low_fps_from_frame_time(self, frame_times_ms: list[float], percentile: float) -> float | None:
        if not frame_times_ms:
            return None
        sorted_frame_times = sorted(frame_times_ms)
        frame_time = self._percentile(sorted_frame_times, percentile)
        if frame_time <= 0:
            return None
        return round(1000.0 / frame_time, 2)

    def _write_chart(self, path: Path) -> None:
        plt.style.use("dark_background")
        figure, axes = plt.subplots(2, 2, figsize=(14, 8), dpi=150)
        figure.patch.set_facecolor("#101316")
        series = [
            ("FPS", "fps", "#58d68d", axes[0][0]),
            ("CPU / GPU Usage %", ("cpu_percent", "gpu_percent"), "#5dade2", axes[0][1]),
            ("Temperature C", ("cpu_temp_c", "gpu_temp_c"), "#f5b041", axes[1][0]),
            ("GPU Power W", "gpu_power_w", "#af7ac5", axes[1][1]),
        ]
        elapsed = [sample.elapsed_s / 60 for sample in self.samples]
        for title, key, color, axis in series:
            axis.set_facecolor("#151a1f")
            axis.grid(True, color="#2a3138", linewidth=0.8, alpha=0.8)
            axis.tick_params(colors="#aeb6bf")
            axis.set_title(title, color="#f4f6f7", fontsize=12, pad=10)
            if isinstance(key, tuple):
                labels = {"cpu_percent": "CPU", "gpu_percent": "GPU", "cpu_temp_c": "CPU", "gpu_temp_c": "GPU"}
                colors = {"cpu_percent": "#58d68d", "gpu_percent": "#5dade2", "cpu_temp_c": "#f5b041", "gpu_temp_c": "#ec7063"}
                for item in key:
                    values = [numeric_value(getattr(sample, item)) for sample in self.samples]
                    axis.plot(elapsed, values, color=colors[item], linewidth=2, label=labels[item])
                axis.legend(facecolor="#151a1f", edgecolor="#34495e", labelcolor="#d6dbdf")
            else:
                values = [numeric_value(getattr(sample, key)) for sample in self.samples]
                axis.plot(elapsed, values, color=color, linewidth=2)
            axis.set_xlabel("Minutes", color="#aeb6bf")
        figure.tight_layout(pad=2)
        figure.savefig(path, facecolor=figure.get_facecolor())
        plt.close(figure)

    def _write_html(self, path: Path, summary: dict[str, object], chart_name: str) -> None:
        fps = summary["fps"]
        cpu = summary["cpu_percent"]
        gpu = summary["gpu_percent"]
        cpu_temp = summary["cpu_temp_c"]
        gpu_temp = summary["gpu_temp_c"]
        html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{APP_NAME} Report</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0f1216;
      --panel: #171c22;
      --line: #2b333c;
      --text: #eef2f5;
      --muted: #a8b3bd;
      --green: #58d68d;
      --blue: #5dade2;
      --amber: #f5b041;
      --red: #ec7063;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      background: radial-gradient(circle at 20% 0%, #18242a 0, transparent 28rem), var(--bg);
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
    .chart {{ width: 100%; border-radius: 8px; border: 1px solid var(--line); background: #101316; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; overflow: hidden; border-radius: 8px; }}
    th, td {{ text-align: left; padding: 13px 14px; border-bottom: 1px solid var(--line); }}
    th {{ color: var(--muted); font-weight: 600; background: #151a1f; }}
    td {{ background: #12171c; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} header {{ display: block; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>{APP_NAME} 性能报告</h1>
      <p>生成时间 {summary["created_at"]}，记录时长 {summary["duration_seconds"]} 秒，共 {summary["sample_count"]} 个采样点。</p>
    </div>
  </header>
  <section class="grid">
    <div class="card"><div class="label">平均 FPS</div><div class="value">{format_metric(fps["avg"], "", 1)}</div></div>
    <div class="card"><div class="label">1% Low FPS</div><div class="value">{format_metric(fps["one_percent_low"], "", 1)}</div></div>
    <div class="card"><div class="label">平均 CPU</div><div class="value">{format_metric(cpu["avg"], "%", 1)}</div></div>
    <div class="card"><div class="label">平均 GPU</div><div class="value">{format_metric(gpu["avg"], "%", 1)}</div></div>
  </section>
  <img class="chart" src="{chart_name}" alt="Performance charts">
  <table>
    <thead><tr><th>指标</th><th>平均</th><th>最低</th><th>最高</th><th>P95</th></tr></thead>
    <tbody>
      <tr><td>FPS</td><td>{format_metric(fps["avg"], "", 2)}</td><td>{format_metric(fps["min"], "", 2)}</td><td>{format_metric(fps["max"], "", 2)}</td><td>{format_metric(fps["p95"], "", 2)}</td></tr>
      <tr><td>CPU 占用</td><td>{format_metric(cpu["avg"], "%", 2)}</td><td>{format_metric(cpu["min"], "%", 2)}</td><td>{format_metric(cpu["max"], "%", 2)}</td><td>{format_metric(cpu["p95"], "%", 2)}</td></tr>
      <tr><td>GPU 占用</td><td>{format_metric(gpu["avg"], "%", 2)}</td><td>{format_metric(gpu["min"], "%", 2)}</td><td>{format_metric(gpu["max"], "%", 2)}</td><td>{format_metric(gpu["p95"], "%", 2)}</td></tr>
      <tr><td>CPU 温度</td><td>{format_metric(cpu_temp["avg"], " C", 2)}</td><td>{format_metric(cpu_temp["min"], " C", 2)}</td><td>{format_metric(cpu_temp["max"], " C", 2)}</td><td>{format_metric(cpu_temp["p95"], " C", 2)}</td></tr>
      <tr><td>GPU 温度</td><td>{format_metric(gpu_temp["avg"], " C", 2)}</td><td>{format_metric(gpu_temp["min"], " C", 2)}</td><td>{format_metric(gpu_temp["max"], " C", 2)}</td><td>{format_metric(gpu_temp["p95"], " C", 2)}</td></tr>
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
        self.accent = tk.Frame(self, bg=accent, height=3)
        self.columnconfigure(0, weight=1)
        self.accent.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 12))
        self.title.grid(row=1, column=0, sticky="w", padx=16)
        self.value.grid(row=2, column=0, sticky="w", padx=16, pady=(6, 16))

    def set_value(self, value: str) -> None:
        self.value.configure(text=value)


class MonitorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1180x760")
        self.root.minsize(980, 650)
        self.root.configure(bg="#0f1216")
        self.session_dir = Path("records") / datetime.now().strftime("session_%Y%m%d_%H%M%S")
        self.recorder = MetricsRecorder(self.session_dir)
        self.visible_samples: deque[MetricSample] = deque(maxlen=MAX_VISIBLE_POINTS)
        self.report_paths: dict[str, str] | None = None
        self.closed = False
        self._configure_style()
        self._build_ui()
        self.recorder.start()
        self.root.protocol("WM_DELETE_WINDOW", self.finish_and_close)
        self._update_loop()

    def _configure_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background="#0f1216", foreground="#eef2f5", font=("Segoe UI", 10))
        style.configure("Header.TLabel", background="#0f1216", foreground="#f7fbff", font=("Segoe UI", 23, "bold"))
        style.configure("Muted.TLabel", background="#0f1216", foreground="#9aa7b2", font=("Segoe UI", 10))
        style.configure("Status.TLabel", background="#151a1f", foreground="#d6dbdf", padding=(12, 7), borderwidth=0)
        style.configure("Card.TFrame", background="#171c22", relief="flat", borderwidth=0)
        style.configure("CardTitle.TLabel", background="#171c22", foreground="#9aa7b2", font=("Segoe UI", 10))
        style.configure("CardValue.TLabel", background="#171c22", foreground="#f7fbff", font=("Segoe UI", 25, "bold"))
        style.configure("Action.TButton", background="#2f80ed", foreground="#ffffff", borderwidth=0, padding=(14, 9), font=("Segoe UI", 10, "bold"))
        style.map("Action.TButton", background=[("active", "#3c8bf1")])
        style.configure("Ghost.TButton", background="#202832", foreground="#d6dbdf", borderwidth=0, padding=(12, 9))
        style.map("Ghost.TButton", background=[("active", "#2a3440")])

    def _build_ui(self) -> None:
        container = ttk.Frame(self, style="Root.TFrame") if False else tk.Frame(self.root, bg="#0f1216")
        container.pack(fill="both", expand=True, padx=24, pady=22)
        header = tk.Frame(container, bg="#0f1216")
        header.pack(fill="x")
        title_area = tk.Frame(header, bg="#0f1216")
        title_area.pack(side="left", fill="x", expand=True)
        ttk.Label(title_area, text=APP_NAME, style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            title_area,
            text="打开即开始记录，关闭时自动生成 CSV、图表和 HTML 报告。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 0))
        actions = tk.Frame(header, bg="#0f1216")
        actions.pack(side="right")
        self.status_label = ttk.Label(actions, text="REC 00:00", style="Status.TLabel")
        self.status_label.pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="打开记录目录", style="Ghost.TButton", command=self.open_records_dir).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="结束并生成", style="Action.TButton", command=self.finish_and_close).pack(side="left")

        cards = tk.Frame(container, bg="#0f1216")
        cards.pack(fill="x", pady=(22, 18))
        for column in range(6):
            cards.columnconfigure(column, weight=1, uniform="cards")
        self.cards = {
            "fps": MetricCard(cards, "实时 FPS", "#58d68d"),
            "low": MetricCard(cards, "1% Low", "#f5b041"),
            "cpu": MetricCard(cards, "CPU 占用", "#5dade2"),
            "gpu": MetricCard(cards, "GPU 占用", "#af7ac5"),
            "cpu_temp": MetricCard(cards, "CPU 温度", "#ec7063"),
            "gpu_temp": MetricCard(cards, "GPU 温度", "#48c9b0"),
        }
        for index, card in enumerate(self.cards.values()):
            card.grid(row=0, column=index, sticky="nsew", padx=6)

        chart_frame = tk.Frame(container, bg="#151a1f", highlightbackground="#2b333c", highlightthickness=1)
        chart_frame.pack(fill="both", expand=True)
        self.figure, self.axes = plt.subplots(2, 2, figsize=(11, 6), dpi=100)
        self.figure.patch.set_facecolor("#151a1f")
        self.lines: dict[str, object] = {}
        axis_specs = [
            (self.axes[0][0], "FPS", [("fps", "#58d68d", "FPS")]),
            (self.axes[0][1], "CPU / GPU 使用率", [("cpu_percent", "#5dade2", "CPU"), ("gpu_percent", "#af7ac5", "GPU")]),
            (self.axes[1][0], "温度", [("cpu_temp_c", "#ec7063", "CPU"), ("gpu_temp_c", "#48c9b0", "GPU")]),
            (self.axes[1][1], "内存 / 显存", [("memory_percent", "#f5b041", "RAM %"), ("gpu_memory_used_mb", "#85c1e9", "VRAM MB")]),
        ]
        for axis, title, line_specs in axis_specs:
            axis.set_facecolor("#151a1f")
            axis.grid(True, color="#2a3138", linewidth=0.8)
            axis.tick_params(colors="#9aa7b2")
            axis.set_title(title, color="#eef2f5", fontsize=11)
            for key, color, label in line_specs:
                line, = axis.plot([], [], color=color, linewidth=2, label=label)
                self.lines[key] = line
            axis.legend(facecolor="#151a1f", edgecolor="#34495e", labelcolor="#d6dbdf", loc="upper left")
        self.figure.tight_layout(pad=2)
        self.canvas = FigureCanvasTkAgg(self.figure, chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

        footer = tk.Frame(container, bg="#0f1216")
        footer.pack(fill="x", pady=(12, 0))
        self.source_label = ttk.Label(footer, text=self._source_text(), style="Muted.TLabel")
        self.source_label.pack(side="left")
        self.output_label = ttk.Label(footer, text=f"输出：{self.session_dir}", style="Muted.TLabel")
        self.output_label.pack(side="right")

    def _source_text(self) -> str:
        gpu_status = "GPU: nvidia-smi 已连接" if self.recorder.gpu_reader.available else "GPU: 未检测到 nvidia-smi"
        fps_status = "FPS: PresentMon 已连接" if self.recorder.fps_reader.available else "FPS: 未检测到 PresentMon.exe"
        return f"{gpu_status}    {fps_status}"

    def _update_loop(self) -> None:
        while True:
            try:
                sample = self.recorder.events.get_nowait()
            except queue.Empty:
                break
            self.visible_samples.append(sample)
        self._update_cards()
        self._update_chart()
        elapsed = int(time.monotonic() - self.recorder.started_at)
        self.status_label.configure(text=f"REC {elapsed // 60:02d}:{elapsed % 60:02d}")
        self.source_label.configure(text=self._source_text())
        if not self.closed:
            self.root.after(1000, self._update_loop)

    def _update_cards(self) -> None:
        if not self.visible_samples:
            return
        latest = self.visible_samples[-1]
        all_fps = [sample.fps for sample in self.recorder.samples if numeric_value(sample.fps) is not None]
        one_percent_low = ReportWriter(self.session_dir, [], [])._percentile_low([float(value) for value in all_fps], 0.01)
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
            y_values = [numeric_value(getattr(sample, key)) for sample in self.visible_samples]
            line.set_data(x_values, y_values)
        for axis in self.axes.flat:
            axis.relim()
            axis.autoscale_view()
            if x_values:
                axis.set_xlim(max(0, x_values[-1] - MAX_VISIBLE_POINTS), max(MAX_VISIBLE_POINTS, x_values[-1]))
        self.canvas.draw_idle()

    def open_records_dir(self) -> None:
        target = self.session_dir if self.session_dir.exists() else Path("records")
        target.mkdir(parents=True, exist_ok=True)
        os.startfile(target.resolve())

    def finish_and_close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.status_label.configure(text="生成中...")
        self.root.update_idletasks()
        self.recorder.stop()
        writer = ReportWriter(self.session_dir, self.recorder.samples, self.recorder.fps_reader.frame_times_ms)
        self.report_paths = writer.write_all()
        try:
            os.startfile(Path(self.report_paths["html"]).resolve())
        except OSError:
            pass
        messagebox.showinfo(APP_NAME, f"报告已生成：\n{self.report_paths['html']}")
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = MonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
