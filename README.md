# Klinux

一些在 Linux/Ubuntu 上使用的视觉、ROS2 和训练数据采集辅助工具。

## 工具

- `hsv_segmenter`：HSV 分割调参
- `ros2_panel`：ROS2 控制面板
- `yolo_image_collector`：YOLO 训练图像采集

## 一键生成桌面图标

克隆或复制整个仓库后，进入仓库目录运行：

```bash
git clone git@github.com:dengyuekai0326/Klinux.git
cd Klinux
./install_desktop_shortcuts.sh
```

脚本会自动按当前路径生成：

- 桌面图标
- 应用菜单入口

如果桌面图标第一次打开时提示未信任，右键图标，在属性里允许启动即可。工程目录里的 `.desktop` 文件可能会被文件管理器当文本打开，推荐使用桌面图标、应用菜单，或直接运行 `run_*.sh`。

## 直接运行

也可以不使用桌面图标，直接运行每个工具目录里的启动脚本：

```bash
./hsv_segmenter/run_hsv_segmenter.sh
./ros2_panel/run_ros2_panel.sh
./yolo_image_collector/run_yolo_image_collector.sh
```
