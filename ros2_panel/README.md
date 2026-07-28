# ROS2 Panel

一个单窗口 ROS2 控制面板，用来减少手动输入 `ros2 run`、`ros2 launch`、`ros2 topic echo` 等命令。

## 运行

```bash
cd /home/ubuntu22/kwork/ros2_panel
./run_ros2_panel.sh
```

桌面图标和应用菜单会调用同一个启动脚本。

如果把这个工程复制到另一台电脑或另一个用户目录，进入工程目录后运行：

```bash
./install_desktop_shortcut.sh
```

脚本会按当前路径重新生成桌面图标和应用菜单入口。

## 功能

- 自动 source ROS2 和 workspace 环境
- 刷新 ROS2 package 列表
- 自动扫描选中 package 的 launch 文件
- 查询选中 package 的 executable node
- 一键运行 `ros2 launch`
- 一键运行 `ros2 run`
- 刷新 topic / node 列表
- 一键 `topic echo`、`topic hz`、`topic info`、`topic type`
- 一键 `node info`
- GUI 内查看 stdout/stderr 日志
- 停止选中任务或停止全部任务
- 保存常用命令为快捷按钮

## 配置

配置文件在：

```bash
/home/ubuntu22/kwork/ros2_panel/config.json
```

默认环境：

```json
{
  "ros_setup": "/opt/ros/humble/setup.bash",
  "workspace": "/home/ubuntu22/ds_ws"
}
```

每条命令都会用类似下面的方式执行：

```bash
source /opt/ros/humble/setup.bash
source /home/ubuntu22/ds_ws/install/setup.bash
cd /home/ubuntu22/ds_ws
ros2 ...
```

## 快捷命令

快捷命令支持保存任意 ROS2 命令，例如：

```bash
ros2 launch ds_vision target_competition_vision.launch.py
ros2 topic echo /camera/image_raw
ros2 topic list
```

长时间运行的命令会出现在右侧任务列表里，可以选中后停止。
