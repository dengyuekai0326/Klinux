#!/usr/bin/env python3
"""Single-window ROS2 command panel."""

from __future__ import annotations

import json
import os
import queue
import shlex
import signal
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_CONFIG = {
    "ros_setup": "/opt/ros/humble/setup.bash",
    "workspace": "/home/ubuntu22/ds_ws",
    "shortcuts": [
        {
            "name": "视觉 Launch",
            "command": "ros2 launch ds_vision target_competition_vision.launch.py",
            "mode": "process",
        },
        {"name": "Topic 列表", "command": "ros2 topic list", "mode": "once"},
    ],
}


@dataclass
class ManagedProcess:
    name: str
    command: str
    process: subprocess.Popen[str]
    started_at: float


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return dict(DEFAULT_CONFIG)
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    merged.setdefault("shortcuts", [])
    return merged


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class Ros2PanelApp:
    def __init__(self) -> None:
        self.config = load_config()
        self.root = tk.Tk()
        self.root.title("ROS2 控制面板")
        self.root.geometry("1320x820")
        self.root.minsize(1080, 680)
        self.root.configure(bg="#101418")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.processes: dict[str, ManagedProcess] = {}
        self.packages: list[str] = []
        self.launch_files: dict[str, list[str]] = {}
        self.executables: dict[str, list[str]] = {}
        self.topics: list[str] = []
        self.nodes: list[str] = []

        self.vars = self.build_vars()
        self.setup_style()
        self.build_ui()
        self.root.after(100, self.poll_logs)
        self.root.after(500, self.refresh_process_table)
        self.refresh_all_async()

    def build_vars(self) -> dict[str, tk.Variable]:
        shortcuts = self.config.get("shortcuts", [])
        first_shortcut = shortcuts[0]["name"] if shortcuts else ""
        return {
            "ros_setup": tk.StringVar(value=self.config.get("ros_setup", DEFAULT_CONFIG["ros_setup"])),
            "workspace": tk.StringVar(value=self.config.get("workspace", DEFAULT_CONFIG["workspace"])),
            "package": tk.StringVar(value=""),
            "launch_file": tk.StringVar(value=""),
            "executable": tk.StringVar(value=""),
            "topic": tk.StringVar(value=""),
            "node": tk.StringVar(value=""),
            "shortcut": tk.StringVar(value=first_shortcut),
            "shortcut_name": tk.StringVar(value=""),
            "shortcut_command": tk.StringVar(value=""),
            "status": tk.StringVar(value="准备就绪"),
        }

    def setup_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=("Noto Sans CJK SC", 10))
        style.configure("Root.TFrame", background="#101418")
        style.configure("Panel.TFrame", background="#171d23")
        style.configure("Card.TFrame", background="#202830")
        style.configure("TLabel", background="#171d23", foreground="#edf2f7")
        style.configure("Card.TLabel", background="#202830", foreground="#edf2f7")
        style.configure("Muted.TLabel", foreground="#9aa7b4")
        style.configure("Title.TLabel", font=("Noto Sans CJK SC", 13, "bold"))
        style.configure("TButton", padding=(9, 5))
        style.configure("Danger.TButton", foreground="#ff8f8f")
        style.configure("Treeview", background="#0f1419", fieldbackground="#0f1419", foreground="#edf2f7")
        style.configure("Treeview.Heading", background="#202830", foreground="#edf2f7")

    def build_ui(self) -> None:
        root = ttk.Frame(self.root, style="Root.TFrame", padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        left = ttk.Frame(root, style="Panel.TFrame", padding=12)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        left.configure(width=390)
        left.grid_propagate(False)

        right = ttk.Frame(root, style="Root.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        self.build_left(left)
        self.build_right(right)

    def build_left(self, parent: ttk.Frame) -> None:
        row = 0
        ttk.Label(parent, text="环境", style="Title.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        row = self.add_entry(parent, row, "ROS setup", "ros_setup")
        row = self.add_entry(parent, row, "Workspace", "workspace")
        ttk.Button(parent, text="保存环境", command=self.save_environment).grid(row=row, column=0, sticky="ew", pady=6)
        ttk.Button(parent, text="检测", command=self.check_environment_async).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(parent, text="刷新全部", command=self.refresh_all_async).grid(row=row, column=2, sticky="ew")
        row += 1
        ttk.Separator(parent).grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1

        ttk.Label(parent, text="Launch / Run", style="Title.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        ttk.Label(parent, text="包").grid(row=row, column=0, sticky="w")
        self.package_combo = ttk.Combobox(parent, textvariable=self.vars["package"], values=[], state="readonly")
        self.package_combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        self.package_combo.bind("<<ComboboxSelected>>", lambda _: self.on_package_selected())
        row += 1
        ttk.Label(parent, text="Launch").grid(row=row, column=0, sticky="w")
        self.launch_combo = ttk.Combobox(parent, textvariable=self.vars["launch_file"], values=[], state="readonly")
        self.launch_combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        row += 1
        ttk.Label(parent, text="节点").grid(row=row, column=0, sticky="w")
        self.exec_combo = ttk.Combobox(parent, textvariable=self.vars["executable"], values=[], state="readonly")
        self.exec_combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        row += 1
        ttk.Button(parent, text="运行 Launch", command=self.run_selected_launch).grid(row=row, column=0, sticky="ew", pady=5)
        ttk.Button(parent, text="运行 Node", command=self.run_selected_node).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(parent, text="停止选中", command=self.stop_selected_process).grid(row=row, column=2, sticky="ew")
        row += 1
        ttk.Separator(parent).grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1

        ttk.Label(parent, text="Topic / Node", style="Title.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        ttk.Label(parent, text="Topic").grid(row=row, column=0, sticky="w")
        self.topic_combo = ttk.Combobox(parent, textvariable=self.vars["topic"], values=[], state="readonly")
        self.topic_combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        row += 1
        ttk.Button(parent, text="刷新 Topic", command=self.refresh_topics_async).grid(row=row, column=0, sticky="ew", pady=5)
        ttk.Button(parent, text="Echo", command=self.topic_echo).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(parent, text="Hz", command=self.topic_hz).grid(row=row, column=2, sticky="ew")
        row += 1
        ttk.Button(parent, text="Info", command=self.topic_info).grid(row=row, column=0, sticky="ew")
        ttk.Button(parent, text="Type", command=self.topic_type).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(parent, text="List", command=lambda: self.run_once("ros2 topic list", "topic list")).grid(
            row=row, column=2, sticky="ew"
        )
        row += 1
        ttk.Label(parent, text="Node").grid(row=row, column=0, sticky="w")
        self.node_combo = ttk.Combobox(parent, textvariable=self.vars["node"], values=[], state="readonly")
        self.node_combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        row += 1
        ttk.Button(parent, text="刷新 Node", command=self.refresh_nodes_async).grid(row=row, column=0, sticky="ew", pady=5)
        ttk.Button(parent, text="Node Info", command=self.node_info).grid(row=row, column=1, columnspan=2, sticky="ew", padx=(6, 0))
        row += 1
        ttk.Separator(parent).grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1

        ttk.Label(parent, text="快捷命令", style="Title.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        self.shortcut_combo = ttk.Combobox(parent, textvariable=self.vars["shortcut"], values=self.shortcut_names(), state="readonly")
        self.shortcut_combo.grid(row=row, column=0, columnspan=3, sticky="ew", pady=4)
        self.shortcut_combo.bind("<<ComboboxSelected>>", lambda _: self.load_shortcut_to_form())
        row += 1
        row = self.add_entry(parent, row, "名称", "shortcut_name")
        row = self.add_entry(parent, row, "命令", "shortcut_command")
        ttk.Button(parent, text="运行快捷", command=self.run_shortcut).grid(row=row, column=0, sticky="ew", pady=5)
        ttk.Button(parent, text="保存/更新", command=self.save_shortcut).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(parent, text="删除", command=self.delete_shortcut).grid(row=row, column=2, sticky="ew")
        row += 1
        ttk.Label(parent, textvariable=self.vars["status"], style="Muted.TLabel", wraplength=360).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )
        parent.columnconfigure(1, weight=1)

    def build_right(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Panel.TFrame", padding=(10, 8))
        top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(top, text="任务", style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="停止全部", command=self.stop_all_processes).pack(side="right", padx=(6, 0))
        ttk.Button(top, text="清空日志", command=self.clear_log).pack(side="right")

        body = ttk.PanedWindow(parent, orient="vertical")
        body.grid(row=1, column=0, sticky="nsew")

        proc_frame = ttk.Frame(body, style="Panel.TFrame", padding=8)
        self.process_tree = ttk.Treeview(proc_frame, columns=("cmd", "status", "time"), show="headings", height=7)
        self.process_tree.heading("cmd", text="命令")
        self.process_tree.heading("status", text="状态")
        self.process_tree.heading("time", text="运行时间")
        self.process_tree.column("cmd", width=720)
        self.process_tree.column("status", width=90, anchor="center")
        self.process_tree.column("time", width=90, anchor="center")
        self.process_tree.pack(fill="both", expand=True)
        body.add(proc_frame, weight=1)

        log_frame = ttk.Frame(body, style="Panel.TFrame", padding=8)
        self.log_text = tk.Text(
            log_frame,
            bg="#0b0f13",
            fg="#dfe7ef",
            insertbackground="#dfe7ef",
            relief="flat",
            wrap="word",
            font=("JetBrains Mono", 10),
        )
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        body.add(log_frame, weight=4)

    def add_entry(self, parent: ttk.Frame, row: int, label: str, key: str) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=self.vars[key]).grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        return row + 1

    def shell_prefix(self) -> str:
        ros_setup = shlex.quote(self.vars["ros_setup"].get())
        workspace = Path(self.vars["workspace"].get()).expanduser()
        ws_setup = workspace / "install" / "setup.bash"
        parts = [f"source {ros_setup}"]
        if ws_setup.exists():
            parts.append(f"source {shlex.quote(str(ws_setup))}")
        parts.append(f"cd {shlex.quote(str(workspace))}")
        return " && ".join(parts)

    def shell_command(self, command: str) -> str:
        return f"{self.shell_prefix()} && {command}"

    def enqueue_log(self, source: str, text: str) -> None:
        self.log_queue.put((source, text))

    def append_log(self, source: str, text: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] [{source}] {text}")
        if not text.endswith("\n"):
            self.log_text.insert("end", "\n")
        self.log_text.see("end")

    def poll_logs(self) -> None:
        while True:
            try:
                source, text = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.append_log(source, text)
        self.root.after(100, self.poll_logs)

    def run_shell_once(self, command: str, timeout: float = 12.0) -> tuple[int, str]:
        full = self.shell_command(command)
        try:
            result = subprocess.run(
                ["bash", "-lc", full],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
            return result.returncode, result.stdout
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            return 124, f"{output}\n[timeout] {command}\n"

    def run_once(self, command: str, name: str | None = None) -> None:
        title = name or command

        def worker() -> None:
            self.enqueue_log(title, f"$ {command}\n")
            code, output = self.run_shell_once(command)
            if output:
                self.enqueue_log(title, output)
            self.enqueue_log(title, f"[exit {code}]\n")

        threading.Thread(target=worker, daemon=True).start()

    def start_process(self, command: str, name: str | None = None) -> None:
        title = name or command
        process_id = f"{title}-{int(time.time() * 1000)}"
        full = self.shell_command(command)
        self.enqueue_log(title, f"$ {command}\n")
        try:
            proc = subprocess.Popen(
                ["bash", "-lc", full],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                bufsize=1,
            )
        except Exception as exc:
            self.enqueue_log(title, f"[failed] {exc}\n")
            return
        self.processes[process_id] = ManagedProcess(title, command, proc, time.time())
        self.vars["status"].set(f"已启动: {title}")
        threading.Thread(target=self.read_process_output, args=(process_id,), daemon=True).start()
        self.refresh_process_table(schedule_next=False)

    def read_process_output(self, process_id: str) -> None:
        managed = self.processes.get(process_id)
        if managed is None:
            return
        proc = managed.process
        assert proc.stdout is not None
        for line in proc.stdout:
            self.enqueue_log(managed.name, line)
        code = proc.wait()
        self.enqueue_log(managed.name, f"[exit {code}]\n")

    def selected_process_id(self) -> str | None:
        selection = self.process_tree.selection()
        if not selection:
            return None
        return selection[0]

    def stop_process(self, process_id: str) -> None:
        managed = self.processes.get(process_id)
        if managed is None:
            return
        proc = managed.process
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGINT)
            self.enqueue_log(managed.name, "[sent SIGINT]\n")
        except ProcessLookupError:
            return
        self.root.after(1800, lambda: self.kill_if_running(process_id))

    def kill_if_running(self, process_id: str) -> None:
        managed = self.processes.get(process_id)
        if managed is None or managed.process.poll() is not None:
            return
        try:
            os.killpg(managed.process.pid, signal.SIGTERM)
            self.enqueue_log(managed.name, "[sent SIGTERM]\n")
        except ProcessLookupError:
            pass

    def stop_selected_process(self) -> None:
        process_id = self.selected_process_id()
        if process_id is None:
            self.vars["status"].set("请先在右侧任务表选择一个任务")
            return
        self.stop_process(process_id)

    def stop_all_processes(self) -> None:
        for process_id in list(self.processes):
            self.stop_process(process_id)

    def refresh_process_table(self, schedule_next: bool = True) -> None:
        selected = self.selected_process_id()
        for item in self.process_tree.get_children():
            self.process_tree.delete(item)
        for process_id, managed in list(self.processes.items()):
            proc = managed.process
            code = proc.poll()
            status = "运行中" if code is None else f"退出 {code}"
            elapsed = int(time.time() - managed.started_at)
            self.process_tree.insert(
                "",
                "end",
                iid=process_id,
                values=(f"{managed.name}: {managed.command}", status, f"{elapsed}s"),
            )
        if selected in self.processes:
            self.process_tree.selection_set(selected)
        if schedule_next:
            self.root.after(500, self.refresh_process_table)

    def clear_log(self) -> None:
        self.log_text.delete("1.0", "end")

    def save_environment(self) -> None:
        self.config["ros_setup"] = self.vars["ros_setup"].get()
        self.config["workspace"] = self.vars["workspace"].get()
        save_config(self.config)
        self.vars["status"].set("环境配置已保存")

    def check_environment_async(self) -> None:
        def worker() -> None:
            checks = [
                ("ros2 path", "command -v ros2"),
                ("ros2 doctor", "ros2 --help | head -5"),
                ("workspace setup", f"test -f {shlex.quote(str(Path(self.vars['workspace'].get()) / 'install' / 'setup.bash'))} && echo ok || echo missing"),
            ]
            for name, cmd in checks:
                self.run_once(cmd, name)

        threading.Thread(target=worker, daemon=True).start()

    def refresh_all_async(self) -> None:
        self.refresh_packages_async()
        self.refresh_topics_async()
        self.refresh_nodes_async()

    def refresh_packages_async(self) -> None:
        def worker() -> None:
            self.root.after(0, lambda: self.vars["status"].set("正在刷新包列表"))
            code, output = self.run_shell_once("ros2 pkg list", timeout=18)
            if code != 0:
                self.enqueue_log("pkg list", output)
                self.vars["status"].set("刷新包列表失败")
                return
            packages = sorted(line.strip() for line in output.splitlines() if line.strip())
            self.root.after(0, lambda: self.set_packages(packages))

        threading.Thread(target=worker, daemon=True).start()

    def set_packages(self, packages: list[str]) -> None:
        self.packages = packages
        self.package_combo.configure(values=packages)
        current = self.vars["package"].get()
        preferred = "ds_vision" if "ds_vision" in packages else (packages[0] if packages else "")
        self.vars["package"].set(current if current in packages else preferred)
        self.on_package_selected()
        self.vars["status"].set(f"包列表已刷新: {len(packages)} 个")

    def on_package_selected(self) -> None:
        package = self.vars["package"].get()
        if not package:
            return
        self.refresh_package_items_async(package)

    def refresh_package_items_async(self, package: str) -> None:
        def worker() -> None:
            launch_files = self.find_launch_files(package)
            code, output = self.run_shell_once(f"ros2 pkg executables {shlex.quote(package)}", timeout=10)
            executables: list[str] = []
            if code == 0:
                for line in output.splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[0] == package:
                        executables.append(parts[1])
            self.root.after(0, lambda: self.set_package_items(package, launch_files, sorted(executables)))

        threading.Thread(target=worker, daemon=True).start()

    def find_launch_files(self, package: str) -> list[str]:
        workspace = Path(self.vars["workspace"].get()).expanduser()
        candidates = []
        for root in (workspace / "src", workspace / "install"):
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file() and (path.name.endswith(".launch.py") or path.name.endswith(".launch.xml") or path.name.endswith(".launch.yaml")):
                    if package in path.parts:
                        candidates.append(path.name)
        return sorted(set(candidates))

    def set_package_items(self, package: str, launch_files: list[str], executables: list[str]) -> None:
        if package != self.vars["package"].get():
            return
        self.launch_files[package] = launch_files
        self.executables[package] = executables
        self.launch_combo.configure(values=launch_files)
        self.exec_combo.configure(values=executables)
        self.vars["launch_file"].set(launch_files[0] if launch_files else "")
        self.vars["executable"].set(executables[0] if executables else "")

    def run_selected_launch(self) -> None:
        package = self.vars["package"].get()
        launch_file = self.vars["launch_file"].get()
        if not package or not launch_file:
            self.vars["status"].set("请选择 package 和 launch 文件")
            return
        self.start_process(f"ros2 launch {shlex.quote(package)} {shlex.quote(launch_file)}", f"launch {package}")

    def run_selected_node(self) -> None:
        package = self.vars["package"].get()
        executable = self.vars["executable"].get()
        if not package or not executable:
            self.vars["status"].set("请选择 package 和节点")
            return
        self.start_process(f"ros2 run {shlex.quote(package)} {shlex.quote(executable)}", f"run {package}/{executable}")

    def refresh_topics_async(self) -> None:
        def worker() -> None:
            code, output = self.run_shell_once("ros2 topic list", timeout=10)
            if code != 0:
                self.enqueue_log("topic list", output)
                return
            topics = sorted(line.strip() for line in output.splitlines() if line.strip())
            self.root.after(0, lambda: self.set_topics(topics))

        threading.Thread(target=worker, daemon=True).start()

    def set_topics(self, topics: list[str]) -> None:
        self.topics = topics
        self.topic_combo.configure(values=topics)
        if topics and self.vars["topic"].get() not in topics:
            self.vars["topic"].set(topics[0])
        self.vars["status"].set(f"Topic 已刷新: {len(topics)} 个")

    def selected_topic(self) -> str | None:
        topic = self.vars["topic"].get()
        if not topic:
            self.vars["status"].set("请先选择 topic")
            return None
        return topic

    def topic_echo(self) -> None:
        topic = self.selected_topic()
        if topic:
            self.start_process(f"ros2 topic echo {shlex.quote(topic)}", f"echo {topic}")

    def topic_hz(self) -> None:
        topic = self.selected_topic()
        if topic:
            self.start_process(f"ros2 topic hz {shlex.quote(topic)}", f"hz {topic}")

    def topic_info(self) -> None:
        topic = self.selected_topic()
        if topic:
            self.run_once(f"ros2 topic info {shlex.quote(topic)}", f"info {topic}")

    def topic_type(self) -> None:
        topic = self.selected_topic()
        if topic:
            self.run_once(f"ros2 topic type {shlex.quote(topic)}", f"type {topic}")

    def refresh_nodes_async(self) -> None:
        def worker() -> None:
            code, output = self.run_shell_once("ros2 node list", timeout=10)
            if code != 0:
                self.enqueue_log("node list", output)
                return
            nodes = sorted(line.strip() for line in output.splitlines() if line.strip())
            self.root.after(0, lambda: self.set_nodes(nodes))

        threading.Thread(target=worker, daemon=True).start()

    def set_nodes(self, nodes: list[str]) -> None:
        self.nodes = nodes
        self.node_combo.configure(values=nodes)
        if nodes and self.vars["node"].get() not in nodes:
            self.vars["node"].set(nodes[0])
        self.vars["status"].set(f"Node 已刷新: {len(nodes)} 个")

    def node_info(self) -> None:
        node = self.vars["node"].get()
        if not node:
            self.vars["status"].set("请先选择 node")
            return
        self.run_once(f"ros2 node info {shlex.quote(node)}", f"node info {node}")

    def shortcut_names(self) -> list[str]:
        return [item["name"] for item in self.config.get("shortcuts", [])]

    def find_shortcut(self, name: str) -> dict[str, Any] | None:
        for item in self.config.get("shortcuts", []):
            if item["name"] == name:
                return item
        return None

    def load_shortcut_to_form(self) -> None:
        item = self.find_shortcut(self.vars["shortcut"].get())
        if item is None:
            return
        self.vars["shortcut_name"].set(item["name"])
        self.vars["shortcut_command"].set(item["command"])

    def refresh_shortcut_combo(self) -> None:
        names = self.shortcut_names()
        self.shortcut_combo.configure(values=names)
        if self.vars["shortcut"].get() not in names:
            self.vars["shortcut"].set(names[0] if names else "")

    def run_shortcut(self) -> None:
        name = self.vars["shortcut_name"].get().strip() or self.vars["shortcut"].get()
        command = self.vars["shortcut_command"].get().strip()
        if not command:
            item = self.find_shortcut(self.vars["shortcut"].get())
            if item:
                name = item["name"]
                command = item["command"]
        if not command:
            self.vars["status"].set("快捷命令为空")
            return
        mode = "process"
        item = self.find_shortcut(name)
        if item:
            mode = item.get("mode", "process")
        if mode == "once":
            self.run_once(command, name)
        else:
            self.start_process(command, name)

    def save_shortcut(self) -> None:
        name = self.vars["shortcut_name"].get().strip()
        command = self.vars["shortcut_command"].get().strip()
        if not name or not command:
            self.vars["status"].set("快捷命令需要名称和命令")
            return
        shortcuts = self.config.setdefault("shortcuts", [])
        existing = self.find_shortcut(name)
        if existing:
            existing["command"] = command
            existing.setdefault("mode", "process")
        else:
            shortcuts.append({"name": name, "command": command, "mode": "process"})
        save_config(self.config)
        self.vars["shortcut"].set(name)
        self.refresh_shortcut_combo()
        self.vars["status"].set(f"快捷命令已保存: {name}")

    def delete_shortcut(self) -> None:
        name = self.vars["shortcut"].get()
        if not name:
            return
        self.config["shortcuts"] = [item for item in self.config.get("shortcuts", []) if item["name"] != name]
        save_config(self.config)
        self.refresh_shortcut_combo()
        self.vars["shortcut_name"].set("")
        self.vars["shortcut_command"].set("")
        self.vars["status"].set(f"快捷命令已删除: {name}")

    def close(self) -> None:
        running = [p for p in self.processes.values() if p.process.poll() is None]
        if running and not messagebox.askyesno("退出", f"还有 {len(running)} 个任务在运行，是否停止并退出？"):
            return
        self.stop_all_processes()
        self.root.after(250, self.root.destroy)

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    app = Ros2PanelApp()
    app.load_shortcut_to_form()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
