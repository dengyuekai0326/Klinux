# Jetson Orin NX 8GB 部署说明

这是一份独立部署副本，不依赖 ROS。现场参数全部集中在
`config/system.yaml`。

## 1. 复制并解压

把压缩包复制到 Jetson 主目录后执行：

```bash
cd ~
tar -xzf ball_control_jetson_v1.tar.gz
cd ball_control_jetson_v1
```

## 2. 使用已有 Jetson YOLO 环境

JetPack 6 对应的 CUDA、TensorRT、PyTorch 和 OpenCV 应继续使用板卡上
已经验证过的版本，不要通过普通 `pip install torch` 覆盖 NVIDIA 版本。

```bash
source ~/venvs/yolo/bin/activate
cd ~/ball_control_jetson_v1
./test_software.sh
```

若只缺少 YAML、串口或 Ultralytics Python 包，可在现有虚拟环境中执行：

```bash
python3 -m pip install --no-deps -r requirements-jetson.txt
```

这里使用 `--no-deps` 是为了避免 pip 替换 JetPack 自带的 CUDA PyTorch 和
OpenCV；若预检仍提示缺少某个依赖，再单独处理该依赖。

## 3. 设备权限

当前用户应属于 `video` 和 `dialout` 组：

```bash
sudo usermod -aG video,dialout "$USER"
```

修改用户组后注销并重新登录。检查设备：

```bash
ls -l /dev/video* /dev/ttyACM*
```

## 4. 修改现场参数

只编辑：

```bash
nano config/system.yaml
```

最常修改的参数：

| 参数 | 含义 |
|---|---|
| `camera.device` | 自动摄像头名称或 `/dev/videoN` |
| `serial.port` | 下位机串口，默认 `/dev/ttyACM0` |
| `calibration.left_x_ratio` | 钢球中心可达左端 |
| `calibration.center_x_ratio` | 水管 0 cm |
| `calibration.right_x_ratio` | 钢球中心可达右端 |
| `model.confidence` | YOLO最低置信度 |
| `modes.mode1_tolerance_cm` | 模式1到达判定范围 |
| `modes.mode2_targets_cm` | 模式2三个目标，默认 `0,+5,-5` |
| `modes.mode2_tolerance_cm` | 模式2三个目标共同判定范围 |
| `modes.mode2_hold_sec` | 模式2各目标连续停留时间 |
| `modes.mode2_timeout_sec` | 模式2总超时 |
| `modes.mode3_tolerance_cm` | 任意位置到达判定范围 |

`mode2_tolerance_cm: 0.5` 表示进入目标的 `±0.5 cm` 并连续满足对应
`hold_sec` 后，才切换到下一个目标。

## 5. 在本机生成 TensorRT engine

TensorRT engine 与生成它的 Jetson/TensorRT 环境绑定，不能使用电脑生成的
engine。板卡首次部署执行：

```bash
source ~/venvs/yolo/bin/activate
cd ~/ball_control_jetson_v1
chmod +x run.sh export_engine.sh test_software.sh
./export_engine.sh
```

生成文件应为 `models/best.engine`。导出过程不需要连接摄像头和下位机。

## 6. 启动

调试画面和串口全双工：

```bash
source ~/venvs/yolo/bin/activate
cd ~/ball_control_jetson_v1
./run.sh
```

比赛正式运行，关闭画面减少复制与绘制开销：

```bash
./run.sh --headless
```

仅验证视觉、不占用串口：

```bash
./run.sh --no-serial
```

按 `Q`、`Esc` 或终端 `Ctrl+C` 正常退出。

## 7. 协议摘要

上位机以 30 Hz 发送：

```text
AA X_H X_L V A FF
```

下位机发送：

```text
AA 00 00 FF             模式1
AA 55 00 FF             模式2
AA TARGET_H TARGET_L FF 模式3，signed int16，单位0.1 cm
```

例如模式3目标 `-5.3 cm` 为 `AA FF CB FF`。
