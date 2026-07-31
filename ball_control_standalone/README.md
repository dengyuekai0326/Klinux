# 钢球控制 standalone 工程

本工程完全不依赖 ROS。运行链路为：

```text
V4L2摄像头线程（只保留最新帧）
        ↓
TensorRT YOLO11n（内存中的BGR帧）
        ↓
Alpha-Beta位置/速度滤波 + 最长120ms短时预测
        ↓
独立绝对时钟线程，以30Hz发送串口帧
```

推理偶尔慢于摄像头时，旧帧会直接丢弃，不会排队形成越来越大的控制延迟。
串口发送与推理解耦，在有效测量后的短时间内使用运动状态预测维持30Hz。

视觉只把完整水管所在的纵向 `25%～75%` 条带送进模型，TensorRT固定输入为
`640×192`。相比原来的640×640，理论输入计算量减少70%；摄像头完整画面
仍然保留用于调试显示，左右水管端点不会被裁掉。

## 1. 放入 TensorRT engine

在 Jetson 上执行：

```bash
cd ~/ball_control_standalone
source ~/venvs/yolo/bin/activate
python3 tools/export_engine_jetson.py
```

这会根据 `config/system.yaml` 重新生成 `models/best.engine`。之前生成的
640×640 engine不能用于新的640×192裁剪配置。`models/best.pt` 只用于
电脑调试和应急回退。

## 2. 集中配置

所有现场参数都在：

```text
config/system.yaml
```

首次运行前至少检查：

```yaml
camera:
  device: "auto:MF500 camera"

serial:
  port: /dev/ttyACM0
```

工程会按V4L2设备名称自动寻找MF500的有效采集节点，因此重新插拔后从
`/dev/video0` 变为 `/dev/video2` 也不需要修改配置。

摄像头请求使用 `640x360 MJPG @ 30 FPS`。训练图片最终进入YOLO时，有效
16:9区域同样会缩放为640x360，因此直接采集该尺寸可减少解码、画面复制和
二次缩放开销。MF500在当前电脑实测只输出
约16.1 FPS；这是直接使用 `v4l2-ctl` 也会出现的设备侧限制，不是模型耗时。
另外该UVC驱动必须使用 `buffer_size: 2`，设为1会进一步降到约8 FPS。

## 3. 水管坐标标定

由于机械结构和摄像头固定，坐标采用固定比例标定，不再每帧识别水管。
在电脑上运行一次点击标定工具：

```bash
source ~/venvs/yolo/bin/activate
cd ~/ball_control_standalone
python3 tools/calibrate_pipe.py
```

依次点击钢球中心能够到达的左端、加粗的0刻度、右端，然后按 `S`。
把终端打印的三个比例复制到 `config/system.yaml`。机械结构不拆动时只需做一次。

调试画面中：

- 左右两根蓝线：钢球中心能够到达的 `-12.5 cm` 和 `+12.5 cm`
- 中间黄线：水管 `0 cm`
- 红点：滤波/预测后的钢球位置

调整：

```yaml
calibration:
  left_x_ratio: 0.100
  center_x_ratio: 0.495
  right_x_ratio: 0.895
```

让三根线分别对准钢球中心的左端、原点和右端。这里标定的是“钢球中心可达
位置”，不是塑料水管外边缘。比例坐标使配置不受分辨率变化影响。

## 4. 启动

电脑开发调试使用 `best.pt`：

```bash
source ~/venvs/yolo/bin/activate
cd ~/ball_control_standalone
./run_desktop.sh
```

若电脑没有 `/dev/ttyACM0`，该脚本会自动关闭串口，只测试摄像头、模型和
实时性能。

Jetson正式启动使用 TensorRT：

```bash
source ~/venvs/yolo/bin/activate
cd ~/ball_control_standalone
./run.sh
```

关闭调试画面、用于正式比赛：

```bash
./run.sh --headless
```

只调摄像头和模型、不打开串口：

```bash
python3 tools/preflight.py --no-serial
python3 main.py --no-serial
```

按 `Q` 或 `Esc` 正常退出调试画面。

## 5. 正确的内存帧测速

旧脚本逐张从磁盘读取JPEG，`71.96 ms`包含了磁盘解码和文件路径调用开销，
不能代表摄像头线程已经解码好的内存帧。

在 Jetson 运行：

```bash
python3 tools/benchmark_memory.py \
  models/best.engine \
  ~/ball_yolo_jetson_stable/dataset/images/test
```

以 `P95 latency <= 33.33 ms` 为模型实时目标。正式程序每5秒还会打印：

```text
camera
inference_loop
latency_mean
latency_p95
detected
dropped
tx_jitter_max
```

稳定运行应满足：

- `camera` 接近 30 FPS
- `latency_p95` 尽量不超过 33.33 ms
- `pipeline_p95` 是从摄像头交付帧到识别完成的真实软件链路延迟
- `detected` 接近 100%
- `tx_jitter_max` 保持较小
- `dropped` 可以缓慢增加，但不能持续快速增加

丢弃旧帧是设计行为：控制系统需要最新状态，而不是处理完整历史帧。

当前电脑使用 `best.pt + 640×192 ROI` 的连续实测结果：

- 1035帧检测率100%
- 视觉循环约20.6 FPS（裁剪前约15.7 FPS）
- 完整链路P95约14.8 ms
- 无过期帧，只有启动阶段丢弃1帧

## 6. 串口协议

### Jetson发送钢球状态

固定6字节：

```text
AA X_H X_L V A FF
```

- `X`：以水管中心为0，右正左负，signed int16，限制为 `-320~+320`
- `V`：每个30Hz周期的位移量，signed int8
- `A`：每个30Hz周期平方的速度变化量，signed int8

负数全部使用二进制补码。

### 下位机发送模式

固定4字节：

```text
AA 00 00 FF       模式1：找中心
AA 55 00 FF       模式2：0 → +5 → -5
AA 整数位 小数位 FF  模式3：任意位置
```

模式3整数位是 signed int8，小数位为 `0~9`，例如：

```text
AA 05 03 FF       +5.3 cm
AA FB 03 FF       -5.3 cm
```

### Jetson发送任务状态

固定6字节：

```text
AB MODE_STEP TARGET_H TARGET_L STATUS FF
```

`STATUS`：`0`运行、`1`完成、`2`超时、`3`当前无有效球位置。

## 7. 安全策略

- 测量超过150ms仍未恢复时停止发送钢球状态，不发送虚假坐标
- 120ms以内的短时丢检使用有界速度预测
- 超出水管ROI的YOLO候选框会被拒绝
- 跳变超过物理速度门限的测量会被拒绝
- 关闭录像，避免磁盘I/O引入周期抖动
