#!/usr/bin/env python3
"""YOLO training image collector."""

from __future__ import annotations

import json
import platform
import subprocess
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

import cv2
import numpy as np


APP_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = APP_DIR / "dataset" / "images" / "raw"
CONFIG_PATH = APP_DIR / "collector_config.json"


DEFAULT_CONFIG = {
    "camera": 0,
    "width": 1280,
    "height": 720,
    "fps": 30,
    "output_dir": str(DEFAULT_OUTPUT),
    "class_name": "object",
    "prefix": "train",
    "interval_ms": 800,
    "save_preview_overlay": False,
}


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)
        return merged
    CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dict(DEFAULT_CONFIG)


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class YoloImageCollector:
    def __init__(self) -> None:
        self.config = load_config()
        self.root = tk.Tk()
        self.root.title("YOLO 图像采集")
        self.root.geometry("1240x780")
        self.root.minsize(980, 620)
        self.root.configure(bg="#101418")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.cap: cv2.VideoCapture | None = None
        self.frame_bgr: np.ndarray | None = None
        self.running = True
        self.preview_paused = False
        self.auto_capture = False
        self.last_capture_time = 0.0
        self.saved_count = 0
        self.failed_reads = 0

        self.vars = self.build_vars()
        self.setup_style()
        self.build_ui()
        self.open_camera()
        self.root.after(20, self.update_loop)

    def build_vars(self) -> dict[str, tk.Variable]:
        return {
            "camera": tk.IntVar(value=int(self.config["camera"])),
            "width": tk.IntVar(value=int(self.config["width"])),
            "height": tk.IntVar(value=int(self.config["height"])),
            "fps": tk.IntVar(value=int(self.config["fps"])),
            "output_dir": tk.StringVar(value=str(self.config["output_dir"])),
            "class_name": tk.StringVar(value=str(self.config["class_name"])),
            "prefix": tk.StringVar(value=str(self.config["prefix"])),
            "interval_ms": tk.IntVar(value=int(self.config["interval_ms"])),
            "save_preview_overlay": tk.BooleanVar(value=bool(self.config["save_preview_overlay"])),
            "status": tk.StringVar(value="准备打开摄像头"),
            "count": tk.StringVar(value="已采集 0 张"),
            "auto_text": tk.StringVar(value="开始连拍"),
        }

    def setup_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=("Noto Sans CJK SC", 10))
        style.configure("Root.TFrame", background="#101418")
        style.configure("Panel.TFrame", background="#171d23")
        style.configure("Card.TFrame", background="#202830")
        style.configure("TLabel", background="#171d23", foreground="#edf2f7")
        style.configure("Preview.TLabel", background="#0b0f13", foreground="#edf2f7")
        style.configure("Muted.TLabel", foreground="#9aa7b4")
        style.configure("Title.TLabel", font=("Noto Sans CJK SC", 13, "bold"))
        style.configure("Count.TLabel", font=("Noto Sans CJK SC", 16, "bold"), foreground="#7ee787")
        style.configure("TButton", padding=(10, 6))
        style.configure("Accent.TButton", padding=(12, 8))
        style.configure("Danger.TButton", foreground="#ff8f8f")
        style.configure("TCheckbutton", background="#171d23", foreground="#edf2f7")

    def build_ui(self) -> None:
        root = ttk.Frame(self.root, style="Root.TFrame", padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        controls = ttk.Frame(root, style="Panel.TFrame", padding=14)
        controls.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        controls.configure(width=360)
        controls.grid_propagate(False)

        preview_panel = ttk.Frame(root, style="Root.TFrame")
        preview_panel.grid(row=0, column=1, sticky="nsew")
        preview_panel.rowconfigure(1, weight=1)
        preview_panel.columnconfigure(0, weight=1)

        self.build_controls(controls)
        self.build_preview(preview_panel)

        self.root.bind("<space>", lambda _: self.capture_one())
        self.root.bind("<Return>", lambda _: self.capture_one())
        self.root.bind("p", lambda _: self.toggle_pause())
        self.root.bind("a", lambda _: self.toggle_auto_capture())
        self.root.bind("s", lambda _: self.save_current_config())

    def build_controls(self, parent: ttk.Frame) -> None:
        row = 0
        ttk.Label(parent, text="采集配置", style="Title.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        row = self.add_spin(parent, row, "摄像头", "camera", 0, 12)
        row = self.add_spin(parent, row, "宽度", "width", 160, 4096)
        row = self.add_spin(parent, row, "高度", "height", 120, 2160)
        row = self.add_spin(parent, row, "FPS", "fps", 1, 120)
        ttk.Button(parent, text="打开/切换摄像头", command=self.open_camera).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=8
        )
        row += 1
        ttk.Separator(parent).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        ttk.Label(parent, text="保存", style="Title.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        ttk.Label(parent, text="目录").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=self.vars["output_dir"]).grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(parent, text="选择", command=self.choose_output_dir).grid(row=row, column=2, sticky="ew", padx=(6, 0))
        row += 1
        row = self.add_entry(parent, row, "类别", "class_name")
        row = self.add_entry(parent, row, "前缀", "prefix")
        ttk.Checkbutton(parent, text="保存预览叠字", variable=self.vars["save_preview_overlay"]).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=4
        )
        row += 1
        ttk.Button(parent, text="保存配置", command=self.save_current_config).grid(row=row, column=0, sticky="ew", pady=6)
        ttk.Button(parent, text="打开目录", command=self.open_output_dir).grid(row=row, column=1, columnspan=2, sticky="ew", padx=(6, 0))
        row += 1
        ttk.Separator(parent).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        ttk.Label(parent, text="采集", style="Title.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        ttk.Button(parent, text="采集一张", style="Accent.TButton", command=self.capture_one).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(8, 5)
        )
        row += 1
        row = self.add_spin(parent, row, "间隔ms", "interval_ms", 100, 10000)
        ttk.Button(parent, textvariable=self.vars["auto_text"], command=self.toggle_auto_capture).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=5
        )
        ttk.Button(parent, text="暂停预览", command=self.toggle_pause).grid(row=row, column=2, sticky="ew", padx=(6, 0))
        row += 1
        ttk.Label(parent, textvariable=self.vars["count"], style="Count.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(10, 4)
        )
        row += 1
        ttk.Separator(parent).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        ttk.Label(parent, text="快捷键", style="Title.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        ttk.Label(
            parent,
            text="Space/Enter 采集一张\nA 开始/停止连拍\nP 暂停预览\nS 保存配置",
            style="Muted.TLabel",
            wraplength=320,
        ).grid(row=row, column=0, columnspan=3, sticky="ew", pady=4)
        row += 1
        ttk.Label(parent, textvariable=self.vars["status"], style="Muted.TLabel", wraplength=320).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(12, 0)
        )
        parent.columnconfigure(1, weight=1)

    def build_preview(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Panel.TFrame", padding=(12, 10))
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(top, text="实时预览", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="YOLO images/raw 采集", style="Muted.TLabel").pack(side="right")

        frame = ttk.Frame(parent, style="Card.TFrame", padding=8)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.preview_label = ttk.Label(frame, style="Preview.TLabel", anchor="center")
        self.preview_label.grid(row=0, column=0, sticky="nsew")

    def add_entry(self, parent: ttk.Frame, row: int, label: str, key: str) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=self.vars[key]).grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        return row + 1

    def add_spin(self, parent: ttk.Frame, row: int, label: str, key: str, low: int, high: int) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Spinbox(parent, from_=low, to=high, textvariable=self.vars[key], width=8).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=3
        )
        return row + 1

    def open_camera(self) -> None:
        if self.cap is not None:
            self.cap.release()
        index = int(self.vars["camera"].get())
        backend = cv2.CAP_V4L2 if platform.system() == "Linux" else cv2.CAP_ANY
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(index)
        self.cap = cap
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.vars["width"].get()))
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.vars["height"].get()))
            cap.set(cv2.CAP_PROP_FPS, int(self.vars["fps"].get()))
            self.vars["status"].set(f"摄像头 {index} 已打开")
        else:
            self.vars["status"].set(f"摄像头 {index} 打开失败")

    def choose_output_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.vars["output_dir"].get())
        if selected:
            self.vars["output_dir"].set(selected)

    def open_output_dir(self) -> None:
        path = Path(self.vars["output_dir"].get()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            self.vars["status"].set(f"打开目录失败: {exc}")

    def output_dir(self) -> Path:
        return Path(self.vars["output_dir"].get()).expanduser()

    def safe_text(self, text: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text.strip())
        return cleaned or "object"

    def next_image_path(self) -> Path:
        output = self.output_dir()
        output.mkdir(parents=True, exist_ok=True)
        cls = self.safe_text(self.vars["class_name"].get())
        prefix = self.safe_text(self.vars["prefix"].get())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        return output / f"{prefix}_{cls}_{timestamp}_{self.saved_count + 1:06d}.jpg"

    def frame_with_overlay(self, frame: np.ndarray) -> np.ndarray:
        image = frame.copy()
        lines = [
            f"class: {self.vars['class_name'].get()}",
            f"saved: {self.saved_count}",
            "Space/Enter capture | A auto | P pause",
        ]
        y = 30
        for line in lines:
            cv2.putText(image, line, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
            cv2.putText(image, line, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)
            y += 30
        return image

    def capture_one(self) -> None:
        if self.frame_bgr is None:
            self.vars["status"].set("当前没有可保存画面")
            return
        frame = self.frame_with_overlay(self.frame_bgr) if self.vars["save_preview_overlay"].get() else self.frame_bgr
        path = self.next_image_path()
        ok = cv2.imwrite(str(path), frame)
        if not ok:
            self.vars["status"].set(f"保存失败: {path}")
            return
        self.saved_count += 1
        self.vars["count"].set(f"已采集 {self.saved_count} 张")
        self.vars["status"].set(f"已保存: {path.name}")
        self.write_session_info(path)

    def write_session_info(self, last_path: Path) -> None:
        data = {
            "last_saved": str(last_path),
            "saved_count": self.saved_count,
            "camera": int(self.vars["camera"].get()),
            "width": int(self.vars["width"].get()),
            "height": int(self.vars["height"].get()),
            "fps": int(self.vars["fps"].get()),
            "output_dir": str(self.output_dir()),
            "class_name": self.vars["class_name"].get(),
            "prefix": self.vars["prefix"].get(),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        (APP_DIR / "last_session.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def toggle_auto_capture(self) -> None:
        self.auto_capture = not self.auto_capture
        self.vars["auto_text"].set("停止连拍" if self.auto_capture else "开始连拍")
        self.vars["status"].set("连拍已开始" if self.auto_capture else "连拍已停止")
        self.last_capture_time = 0.0

    def toggle_pause(self) -> None:
        self.preview_paused = not self.preview_paused
        self.vars["status"].set("预览已暂停" if self.preview_paused else "预览已继续")

    def save_current_config(self) -> None:
        config = {
            "camera": int(self.vars["camera"].get()),
            "width": int(self.vars["width"].get()),
            "height": int(self.vars["height"].get()),
            "fps": int(self.vars["fps"].get()),
            "output_dir": self.vars["output_dir"].get(),
            "class_name": self.vars["class_name"].get(),
            "prefix": self.vars["prefix"].get(),
            "interval_ms": int(self.vars["interval_ms"].get()),
            "save_preview_overlay": bool(self.vars["save_preview_overlay"].get()),
        }
        save_config(config)
        self.vars["status"].set(f"配置已保存: {CONFIG_PATH}")

    def show_image(self, image: np.ndarray) -> None:
        width = max(320, self.preview_label.winfo_width())
        height = max(240, self.preview_label.winfo_height())
        src_h, src_w = image.shape[:2]
        scale = min(width / src_w, height / src_h)
        new_size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
        resized = cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        ppm = b"P6 %d %d 255 " % (rgb.shape[1], rgb.shape[0]) + rgb.tobytes()
        photo = tk.PhotoImage(data=ppm, format="PPM")
        self.preview_label.configure(image=photo)
        self.preview_label.image = photo

    def show_placeholder(self, text: str) -> None:
        image = np.zeros((480, 720, 3), dtype=np.uint8)
        cv2.putText(image, text, (45, 245), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (40, 170, 255), 2)
        self.show_image(image)

    def update_loop(self) -> None:
        if not self.running:
            return
        if self.cap is None or not self.cap.isOpened():
            self.show_placeholder("Camera unavailable")
            self.root.after(200, self.update_loop)
            return
        if not self.preview_paused:
            ok, frame = self.cap.read()
            if ok:
                self.failed_reads = 0
                self.frame_bgr = frame
                self.show_image(self.frame_with_overlay(frame))
            else:
                self.failed_reads += 1
                if self.failed_reads % 20 == 0:
                    self.vars["status"].set("摄像头读取失败，建议重连")
        if self.auto_capture:
            now = time.time()
            interval = max(0.1, int(self.vars["interval_ms"].get()) / 1000.0)
            if now - self.last_capture_time >= interval:
                self.capture_one()
                self.last_capture_time = now
        self.root.after(20, self.update_loop)

    def close(self) -> None:
        self.running = False
        self.save_current_config()
        if self.cap is not None:
            self.cap.release()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    app = YoloImageCollector()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
