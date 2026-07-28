#!/usr/bin/env python3
"""Single-window HSV segmentation tuner."""

from __future__ import annotations

import argparse
import json
import platform
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

import cv2
import numpy as np


CAMERA_PROPS = {
    "exposure": cv2.CAP_PROP_EXPOSURE,
    "auto_wb": cv2.CAP_PROP_AUTO_WB,
    "wb_temp": cv2.CAP_PROP_WB_TEMPERATURE,
    "gain": cv2.CAP_PROP_GAIN,
    "brightness": cv2.CAP_PROP_BRIGHTNESS,
    "contrast": cv2.CAP_PROP_CONTRAST,
    "saturation": cv2.CAP_PROP_SATURATION,
}

VIEW_NAMES = ("原图", "Mask", "分割结果", "HSV图")

COLOR_PRESETS = [
    ("红1-亮", [0, 90, 80], [10, 255, 255]),
    ("红2-亮", [170, 90, 80], [179, 255, 255]),
    ("红1-暗", [0, 70, 40], [12, 255, 180]),
    ("红2-暗", [168, 70, 40], [179, 255, 180]),
    ("橙", [10, 80, 80], [24, 255, 255]),
    ("黄", [24, 80, 90], [36, 255, 255]),
    ("黄绿", [36, 60, 60], [50, 255, 255]),
    ("绿", [50, 50, 50], [85, 255, 255]),
    ("深绿", [40, 70, 25], [90, 255, 150]),
    ("青", [85, 50, 50], [100, 255, 255]),
    ("天蓝", [95, 50, 80], [112, 255, 255]),
    ("蓝", [100, 80, 50], [130, 255, 255]),
    ("深蓝", [105, 80, 20], [135, 255, 150]),
    ("紫", [130, 50, 50], [155, 255, 255]),
    ("粉/洋红", [155, 50, 80], [170, 255, 255]),
    ("白-亮", [0, 0, 200], [179, 45, 255]),
    ("白-阴影", [0, 0, 150], [179, 65, 255]),
    ("灰", [0, 0, 70], [179, 45, 200]),
    ("银灰", [0, 0, 120], [179, 35, 230]),
    ("黑-通用", [0, 0, 0], [179, 255, 60]),
    ("黑-低噪", [0, 0, 0], [179, 80, 55]),
    ("黑-阴影", [0, 0, 0], [179, 255, 90]),
    ("棕", [8, 60, 40], [25, 255, 180]),
    ("肤色", [0, 30, 60], [25, 180, 255]),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Single-window HSV segmentation UI.")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--max-camera", type=int, default=8)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("hsv_params.json"))
    return parser.parse_args()


def auto_exposure_value(enabled: bool) -> float:
    if platform.system() == "Linux":
        return 3.0 if enabled else 1.0
    return 0.75 if enabled else 0.25


def slider_to_signed(value: float) -> float:
    return float(value - 50)


def slider_to_wb_temp(value: float) -> float:
    return float(2000 + value * 80)


class HsvSegmenterApp:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.root = tk.Tk()
        self.root.title("HSV 分割调参")
        self.root.geometry("1280x780")
        self.root.minsize(980, 620)
        self.root.configure(bg="#101418")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.cap: cv2.VideoCapture | None = None
        self.camera_index = args.camera
        self.last_controls: dict[str, float | bool] = {}
        self.running = True
        self.frame_bgr: np.ndarray | None = None
        self.active_views: dict[str, ttk.Frame] = {}
        self.image_labels: dict[str, ttk.Label] = {}
        self.hsv_ranges = [
            {"name": "范围 1", "enabled": True, "lower": [0, 0, 0], "upper": [179, 255, 255]}
        ]
        self.current_range = 0
        self.loading_range = False
        self.reference_visible = False

        self.vars = self.build_vars()
        self.setup_style()
        self.build_ui()
        for key in ("h_min", "h_max", "s_min", "s_max", "v_min", "v_max"):
            self.vars[key].trace_add("write", self.on_hsv_slider_changed)
        self.open_camera(self.camera_index)
        self.root.after(20, self.update_loop)

    def build_vars(self) -> dict[str, tk.Variable]:
        return {
            "camera": tk.IntVar(value=self.args.camera),
            "view": tk.StringVar(value=VIEW_NAMES[0]),
            "h_min": tk.IntVar(value=0),
            "h_max": tk.IntVar(value=179),
            "s_min": tk.IntVar(value=0),
            "s_max": tk.IntVar(value=255),
            "v_min": tk.IntVar(value=0),
            "v_max": tk.IntVar(value=255),
            "range_enabled": tk.BooleanVar(value=True),
            "auto_exposure": tk.BooleanVar(value=True),
            "exposure": tk.IntVar(value=50),
            "auto_wb": tk.BooleanVar(value=True),
            "wb_temp": tk.IntVar(value=45),
            "gain": tk.IntVar(value=0),
            "brightness": tk.IntVar(value=50),
            "contrast": tk.IntVar(value=50),
            "saturation": tk.IntVar(value=50),
            "status": tk.StringVar(value="准备打开摄像头"),
        }

    def setup_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=("Noto Sans CJK SC", 10))
        style.configure("Root.TFrame", background="#101418")
        style.configure("Panel.TFrame", background="#171d23")
        style.configure("Card.TFrame", background="#202830", relief="flat")
        style.configure("TLabel", background="#171d23", foreground="#edf2f7")
        style.configure("Muted.TLabel", foreground="#9aa7b4")
        style.configure("Title.TLabel", font=("Noto Sans CJK SC", 13, "bold"))
        style.configure("TButton", padding=(10, 6))
        style.configure("Tool.TButton", padding=(8, 4))
        style.configure("TCheckbutton", background="#171d23", foreground="#edf2f7")
        style.configure("Horizontal.TScale", background="#171d23")

    def build_ui(self) -> None:
        root = ttk.Frame(self.root, style="Root.TFrame", padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        controls = ttk.Frame(root, style="Panel.TFrame", padding=14)
        controls.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        controls.configure(width=330)
        controls.grid_propagate(False)

        workspace = ttk.Frame(root, style="Root.TFrame")
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.rowconfigure(1, weight=1)
        workspace.columnconfigure(0, weight=1)

        self.view_grid = ttk.Frame(workspace, style="Root.TFrame")
        self.view_grid.grid(row=1, column=0, sticky="nsew")

        self.build_controls(controls)
        self.build_topbar(workspace)
        for name in ("原图", "Mask", "分割结果"):
            self.add_view(name)

    def build_topbar(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent, style="Panel.TFrame", padding=(12, 10))
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        bar.columnconfigure(2, weight=1)
        ttk.Label(bar, text="添加视图", style="Title.TLabel").grid(row=0, column=0, padx=(0, 10))
        ttk.OptionMenu(bar, self.vars["view"], VIEW_NAMES[0], *VIEW_NAMES).grid(row=0, column=1)
        ttk.Button(bar, text="添加", command=lambda: self.add_view(self.vars["view"].get())).grid(
            row=0, column=2, sticky="w", padx=8
        )
        ttk.Button(bar, text="保存参数", command=self.save_params).grid(row=0, column=3, padx=4)
        ttk.Button(bar, text="复制HSV", command=self.copy_hsv).grid(row=0, column=4, padx=4)
        ttk.Button(bar, text="打印JSON", command=self.print_params).grid(row=0, column=5, padx=(4, 0))

    def build_controls(self, parent: ttk.Frame) -> None:
        row = 0
        ttk.Label(parent, text="摄像头", style="Title.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        cam = ttk.Spinbox(parent, from_=0, to=self.args.max_camera, textvariable=self.vars["camera"], width=7)
        cam.grid(row=row, column=0, sticky="w", pady=8)
        ttk.Button(parent, text="切换", command=self.switch_camera).grid(row=row, column=1, sticky="w", padx=8)
        ttk.Button(parent, text="重连", command=lambda: self.open_camera(self.camera_index)).grid(row=row, column=2)
        row += 1
        ttk.Separator(parent).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        ttk.Label(parent, text="HSV 阈值", style="Title.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        self.range_listbox = tk.Listbox(
            parent,
            height=4,
            bg="#101418",
            fg="#edf2f7",
            selectbackground="#2f81f7",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#33404c",
        )
        self.range_listbox.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8, 6))
        self.range_listbox.bind("<<ListboxSelect>>", self.on_range_select)
        row += 1
        ttk.Button(parent, text="新增", command=self.add_hsv_range).grid(row=row, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(parent, text="删除", command=self.delete_hsv_range).grid(row=row, column=1, sticky="ew", padx=4)
        ttk.Checkbutton(parent, text="启用", variable=self.vars["range_enabled"], command=self.set_current_enabled).grid(
            row=row, column=2, sticky="w", padx=(4, 0)
        )
        row += 1
        for label, key, limit in (
            ("H min", "h_min", 179),
            ("H max", "h_max", 179),
            ("S min", "s_min", 255),
            ("S max", "s_max", 255),
            ("V min", "v_min", 255),
            ("V max", "v_max", 255),
        ):
            row = self.add_scale(parent, row, label, key, 0, limit)
        ttk.Button(parent, text="重置当前段", command=self.reset_hsv).grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        row += 1
        ttk.Button(parent, text="HSV参考表", command=self.toggle_reference).grid(
            row=row, column=0, columnspan=3, sticky="ew"
        )
        row += 1
        self.reference_frame = ttk.Frame(parent, style="Panel.TFrame")
        self.reference_row = row
        self.build_reference_panel(self.reference_frame)
        self.refresh_range_list()
        self.load_current_range()
        row += 1
        ttk.Separator(parent).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        ttk.Label(parent, text="相机控制", style="Title.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        ttk.Checkbutton(parent, text="自动曝光", variable=self.vars["auto_exposure"]).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(8, 2)
        )
        row += 1
        row = self.add_scale(parent, row, "曝光", "exposure", 0, 100)
        ttk.Checkbutton(parent, text="自动白平衡", variable=self.vars["auto_wb"]).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(8, 2)
        )
        row += 1
        for label, key in (
            ("白平衡温度", "wb_temp"),
            ("增益", "gain"),
            ("亮度", "brightness"),
            ("对比度", "contrast"),
            ("饱和度", "saturation"),
        ):
            row = self.add_scale(parent, row, label, key, 0, 100)

        ttk.Separator(parent).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1
        ttk.Label(parent, textvariable=self.vars["status"], style="Muted.TLabel", wraplength=295).grid(
            row=row, column=0, columnspan=3, sticky="ew"
        )

    def add_scale(self, parent: ttk.Frame, row: int, label: str, key: str, start: int, end: int) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        value = ttk.Label(parent, textvariable=self.vars[key], width=4)
        value.grid(row=row, column=2, sticky="e")
        scale = ttk.Scale(parent, from_=start, to=end, variable=self.vars[key], orient="horizontal")
        scale.grid(row=row, column=1, sticky="ew", padx=8)
        parent.columnconfigure(1, weight=1)
        return row + 1

    def build_reference_panel(self, parent: ttk.Frame) -> None:
        canvas = tk.Canvas(parent, height=220, bg="#171d23", highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas, style="Panel.TFrame")
        content.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        parent.columnconfigure(0, weight=1)

        for idx, (name, lower, upper) in enumerate(COLOR_PRESETS):
            row = idx
            text = f"{name}  {lower}-{upper}"
            ttk.Label(content, text=text, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=2)
            ttk.Button(content, text="套用", style="Tool.TButton", command=lambda p=(name, lower, upper): self.apply_preset(p)).grid(
                row=row, column=1, padx=3
            )
            ttk.Button(content, text="新增", style="Tool.TButton", command=lambda p=(name, lower, upper): self.add_preset(p)).grid(
                row=row, column=2, padx=3
            )

    def toggle_reference(self) -> None:
        self.reference_visible = not self.reference_visible
        if self.reference_visible:
            self.reference_frame.grid(row=self.reference_row, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        else:
            self.reference_frame.grid_forget()

    def range_display_name(self, idx: int) -> str:
        item = self.hsv_ranges[idx]
        mark = "✓" if item["enabled"] else "×"
        return f'{mark} {item["name"]}: {item["lower"]}-{item["upper"]}'

    def refresh_range_list(self) -> None:
        self.range_listbox.delete(0, tk.END)
        for idx in range(len(self.hsv_ranges)):
            self.range_listbox.insert(tk.END, self.range_display_name(idx))
        self.range_listbox.selection_clear(0, tk.END)
        self.range_listbox.selection_set(self.current_range)
        self.range_listbox.activate(self.current_range)

    def sync_current_range_from_vars(self) -> None:
        if self.loading_range or not self.hsv_ranges:
            return
        item = self.hsv_ranges[self.current_range]
        item["enabled"] = bool(self.vars["range_enabled"].get())
        item["lower"] = [
            min(int(self.vars["h_min"].get()), int(self.vars["h_max"].get())),
            min(int(self.vars["s_min"].get()), int(self.vars["s_max"].get())),
            min(int(self.vars["v_min"].get()), int(self.vars["v_max"].get())),
        ]
        item["upper"] = [
            max(int(self.vars["h_min"].get()), int(self.vars["h_max"].get())),
            max(int(self.vars["s_min"].get()), int(self.vars["s_max"].get())),
            max(int(self.vars["v_min"].get()), int(self.vars["v_max"].get())),
        ]

    def load_current_range(self) -> None:
        self.loading_range = True
        item = self.hsv_ranges[self.current_range]
        self.vars["range_enabled"].set(bool(item["enabled"]))
        self.vars["h_min"].set(item["lower"][0])
        self.vars["s_min"].set(item["lower"][1])
        self.vars["v_min"].set(item["lower"][2])
        self.vars["h_max"].set(item["upper"][0])
        self.vars["s_max"].set(item["upper"][1])
        self.vars["v_max"].set(item["upper"][2])
        self.loading_range = False

    def on_range_select(self, _: tk.Event) -> None:
        selection = self.range_listbox.curselection()
        if not selection:
            return
        self.sync_current_range_from_vars()
        self.current_range = int(selection[0])
        self.load_current_range()
        self.refresh_range_list()

    def add_hsv_range(self) -> None:
        self.sync_current_range_from_vars()
        index = len(self.hsv_ranges) + 1
        self.hsv_ranges.append(
            {"name": f"范围 {index}", "enabled": True, "lower": [0, 0, 0], "upper": [179, 255, 255]}
        )
        self.current_range = len(self.hsv_ranges) - 1
        self.load_current_range()
        self.refresh_range_list()

    def delete_hsv_range(self) -> None:
        if len(self.hsv_ranges) <= 1:
            self.vars["status"].set("至少保留一个 HSV 范围")
            return
        del self.hsv_ranges[self.current_range]
        self.current_range = min(self.current_range, len(self.hsv_ranges) - 1)
        self.load_current_range()
        self.refresh_range_list()

    def set_current_enabled(self) -> None:
        self.sync_current_range_from_vars()
        self.refresh_range_list()

    def on_hsv_slider_changed(self, *_: str) -> None:
        if self.loading_range:
            return
        self.sync_current_range_from_vars()
        self.refresh_range_list()

    def apply_preset(self, preset: tuple[str, list[int], list[int]]) -> None:
        name, lower, upper = preset
        item = self.hsv_ranges[self.current_range]
        item["name"] = name
        item["enabled"] = True
        item["lower"] = list(lower)
        item["upper"] = list(upper)
        self.load_current_range()
        self.refresh_range_list()
        self.vars["status"].set(f"已套用参考色: {name}")

    def add_preset(self, preset: tuple[str, list[int], list[int]]) -> None:
        name, lower, upper = preset
        self.sync_current_range_from_vars()
        self.hsv_ranges.append({"name": name, "enabled": True, "lower": list(lower), "upper": list(upper)})
        self.current_range = len(self.hsv_ranges) - 1
        self.load_current_range()
        self.refresh_range_list()
        self.vars["status"].set(f"已新增参考色: {name}")

    def add_view(self, name: str) -> None:
        if name in self.active_views:
            return
        frame = ttk.Frame(self.view_grid, style="Card.TFrame", padding=8)
        header = ttk.Frame(frame, style="Card.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text=name, style="Title.TLabel", background="#202830").pack(side="left")
        ttk.Button(header, text="删除", style="Tool.TButton", command=lambda: self.remove_view(name)).pack(side="right")
        label = ttk.Label(frame, background="#0b0f13", anchor="center")
        label.pack(fill="both", expand=True, pady=(8, 0))
        self.active_views[name] = frame
        self.image_labels[name] = label
        self.layout_views()

    def remove_view(self, name: str) -> None:
        frame = self.active_views.pop(name, None)
        self.image_labels.pop(name, None)
        if frame is not None:
            frame.destroy()
        self.layout_views()

    def layout_views(self) -> None:
        for child in self.view_grid.winfo_children():
            child.grid_forget()
        count = max(1, len(self.active_views))
        columns = 1 if count == 1 else 2
        for idx, frame in enumerate(self.active_views.values()):
            frame.grid(row=idx // columns, column=idx % columns, sticky="nsew", padx=6, pady=6)
        for col in range(2):
            self.view_grid.columnconfigure(col, weight=1 if col < columns else 0)
        rows = (count + columns - 1) // columns
        for row in range(max(1, rows)):
            self.view_grid.rowconfigure(row, weight=1)

    def open_camera(self, index: int) -> None:
        if self.cap is not None:
            self.cap.release()
        backend = cv2.CAP_V4L2 if platform.system() == "Linux" else cv2.CAP_ANY
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(index)
        self.cap = cap
        self.camera_index = index
        self.last_controls.clear()
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.args.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.args.height)
            cap.set(cv2.CAP_PROP_FPS, self.args.fps)
            self.vars["status"].set(f"摄像头 {index} 已打开")
        else:
            self.vars["status"].set(f"摄像头 {index} 打开失败")

    def switch_camera(self) -> None:
        self.open_camera(int(self.vars["camera"].get()))

    def current_controls(self) -> dict[str, float | bool]:
        return {
            "auto_exposure": bool(self.vars["auto_exposure"].get()),
            "exposure": float(self.vars["exposure"].get()),
            "auto_wb": bool(self.vars["auto_wb"].get()),
            "wb_temp": float(self.vars["wb_temp"].get()),
            "gain": float(self.vars["gain"].get()),
            "brightness": float(self.vars["brightness"].get()),
            "contrast": float(self.vars["contrast"].get()),
            "saturation": float(self.vars["saturation"].get()),
        }

    def set_prop(self, prop: int, value: float) -> None:
        if self.cap is None or not self.cap.isOpened():
            return
        self.cap.set(prop, value)
        time.sleep(0.002)

    def apply_camera_controls(self) -> None:
        values = self.current_controls()
        if values == self.last_controls:
            return
        changed = {key for key, value in values.items() if self.last_controls.get(key) != value}
        if "auto_exposure" in changed:
            self.set_prop(cv2.CAP_PROP_AUTO_EXPOSURE, auto_exposure_value(bool(values["auto_exposure"])))
        if "exposure" in changed or "auto_exposure" in changed:
            self.set_prop(CAMERA_PROPS["exposure"], slider_to_signed(float(values["exposure"])))
        if "auto_wb" in changed:
            self.set_prop(CAMERA_PROPS["auto_wb"], float(bool(values["auto_wb"])))
        if "wb_temp" in changed or "auto_wb" in changed:
            self.set_prop(CAMERA_PROPS["wb_temp"], slider_to_wb_temp(float(values["wb_temp"])))
        for key in ("gain", "brightness", "contrast", "saturation"):
            if key in changed:
                self.set_prop(CAMERA_PROPS[key], float(values[key]))
        self.last_controls = values

    def hsv_bounds(self) -> tuple[np.ndarray, np.ndarray]:
        self.sync_current_range_from_vars()
        lower = np.array(
            [
                min(self.vars["h_min"].get(), self.vars["h_max"].get()),
                min(self.vars["s_min"].get(), self.vars["s_max"].get()),
                min(self.vars["v_min"].get(), self.vars["v_max"].get()),
            ],
            dtype=np.uint8,
        )
        upper = np.array(
            [
                max(self.vars["h_min"].get(), self.vars["h_max"].get()),
                max(self.vars["s_min"].get(), self.vars["s_max"].get()),
                max(self.vars["v_min"].get(), self.vars["v_max"].get()),
            ],
            dtype=np.uint8,
        )
        return lower, upper

    def active_hsv_ranges(self) -> list[tuple[np.ndarray, np.ndarray]]:
        self.sync_current_range_from_vars()
        ranges = []
        for item in self.hsv_ranges:
            if not item["enabled"]:
                continue
            ranges.append(
                (
                    np.array(item["lower"], dtype=np.uint8),
                    np.array(item["upper"], dtype=np.uint8),
                )
            )
        return ranges

    def build_mask(self, hsv: np.ndarray) -> np.ndarray:
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for lower, upper in self.active_hsv_ranges():
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, lower, upper))
        return mask

    def make_views(self, frame: np.ndarray) -> dict[str, np.ndarray]:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = self.build_mask(hsv)
        segmented = cv2.bitwise_and(frame, frame, mask=mask)
        hsv_bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        return {
            "原图": frame,
            "Mask": cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR),
            "分割结果": segmented,
            "HSV图": hsv_bgr,
        }

    def show_image(self, label: ttk.Label, image: np.ndarray) -> None:
        width = max(240, label.winfo_width())
        height = max(160, label.winfo_height())
        src_h, src_w = image.shape[:2]
        scale = min(width / src_w, height / src_h)
        new_size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
        resized = cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        ppm = b"P6 %d %d 255 " % (rgb.shape[1], rgb.shape[0]) + rgb.tobytes()
        photo = tk.PhotoImage(data=ppm, format="PPM")
        label.configure(image=photo)
        label.image = photo

    def show_placeholder(self, text: str) -> None:
        image = np.zeros((360, 640, 3), dtype=np.uint8)
        cv2.putText(image, text, (35, 185), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (40, 170, 255), 2)
        for label in self.image_labels.values():
            self.show_image(label, image)

    def update_loop(self) -> None:
        if not self.running:
            return
        if self.cap is None or not self.cap.isOpened():
            self.show_placeholder(f"Camera {self.camera_index} unavailable")
            self.root.after(200, self.update_loop)
            return
        self.apply_camera_controls()
        ok, frame = self.cap.read()
        if ok:
            self.frame_bgr = frame
            views = self.make_views(frame)
            for name, label in self.image_labels.items():
                self.show_image(label, views[name])
        else:
            self.vars["status"].set(f"摄像头 {self.camera_index} 读取失败")
        self.root.after(20, self.update_loop)

    def camera_readback(self) -> dict[str, float]:
        if self.cap is None or not self.cap.isOpened():
            return {}
        data = {
            "width": self.cap.get(cv2.CAP_PROP_FRAME_WIDTH),
            "height": self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
            "fps": self.cap.get(cv2.CAP_PROP_FPS),
            "auto_exposure": self.cap.get(cv2.CAP_PROP_AUTO_EXPOSURE),
        }
        for key, prop in CAMERA_PROPS.items():
            data[key] = self.cap.get(prop)
        return data

    def collect_params(self) -> dict[str, Any]:
        self.sync_current_range_from_vars()
        lower, upper = self.hsv_bounds()
        return {
            "camera_index": self.camera_index,
            "hsv": {"lower": lower.tolist(), "upper": upper.tolist()},
            "hsv_ranges": [
                {
                    "name": item["name"],
                    "enabled": item["enabled"],
                    "lower": item["lower"],
                    "upper": item["upper"],
                }
                for item in self.hsv_ranges
            ],
            "ui_controls": self.current_controls(),
            "active_views": list(self.active_views.keys()),
            "camera_readback": self.camera_readback(),
        }

    def save_params(self) -> None:
        params = self.collect_params()
        self.args.output.parent.mkdir(parents=True, exist_ok=True)
        self.args.output.write_text(json.dumps(params, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.vars["status"].set(f"已保存: {self.args.output.resolve()}")
        print(f"[saved] {self.args.output.resolve()}")

    def print_params(self) -> None:
        print(json.dumps(self.collect_params(), indent=2, ensure_ascii=False))
        self.vars["status"].set("已打印 JSON 到终端")

    def copy_hsv(self) -> None:
        hsv = self.collect_params()["hsv_ranges"]
        self.root.clipboard_clear()
        self.root.clipboard_append(json.dumps(hsv, ensure_ascii=False))
        self.vars["status"].set("HSV ranges 已复制到剪贴板")

    def reset_hsv(self) -> None:
        for key, value in {
            "h_min": 0,
            "h_max": 179,
            "s_min": 0,
            "s_max": 255,
            "v_min": 0,
            "v_max": 255,
        }.items():
            self.vars[key].set(value)
        self.sync_current_range_from_vars()
        self.refresh_range_list()

    def close(self) -> None:
        self.running = False
        if self.cap is not None:
            self.cap.release()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    app = HsvSegmenterApp(parse_args())
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
