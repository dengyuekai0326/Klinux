# Jetson Orin NX 8GB：钢球控制 v2 部署

v2 不依赖ROS。视觉控制线程、30 Hz串口线程、录像线程和GUI已经相互解耦；
NoMachine显示变慢时只跳过旧调试快照，不会把旧摄像头帧排队送入控制链路。

## 1. 解压与环境

```bash
cd ~
tar -xzf ball_control_jetson_v2.tar.gz
cd ball_control_jetson_v2
source ~/venvs/yolo/bin/activate
chmod +x *.sh
./test_software.sh
```

继续使用JetPack 6已经验证的CUDA、TensorRT、PyTorch和OpenCV，不要用普通
`pip install torch` 覆盖NVIDIA版本。只缺少普通Python包时：

```bash
python3 -m pip install --no-deps -r requirements-jetson.txt
```

用户需属于 `video` 和 `dialout` 组；修改后注销并重新登录：

```bash
sudo usermod -aG video,dialout "$USER"
```

## 2. 集中参数

只编辑：

```bash
nano ~/ball_control_jetson_v2/config/system.yaml
```

先看 `现场调参说明.md`。至少确认摄像头、串口和三点标定。比赛持续图传时
保持 `debug.enabled: true`，不要添加 `--headless`。

## 3. 在这块Jetson重新导出engine

TensorRT engine与生成它的Jetson/TensorRT环境绑定。导出不需要摄像头或串口：

```bash
cd ~/ball_control_jetson_v2
source ~/venvs/yolo/bin/activate
./export_engine.sh
ls -lh models/best.engine
```

当前固定输入应显示为 `640x192`。若已有相同输入、且确实由当前板卡和当前
TensorRT生成的engine，也可以直接复制到 `models/best.engine`。

## 4. 低延迟运行

先检查当前功耗模式、温度和频率：

```bash
sudo nvpmodel -q
tegrastats
```

比赛前在规则允许的散热和供电条件下选择Orin NX可用的高性能功耗模式，并运行：

```bash
sudo jetson_clocks
```

启动完整程序：

```bash
cd ~/ball_control_jetson_v2
source ~/venvs/yolo/bin/activate
./run.sh
```

画面左上角 `display_age` 应低于120 ms；终端每5秒的 `pipeline_p95` 应尽量
低于33.33 ms。若这两个值都低而NoMachine仍显得慢，瓶颈在远程桌面或无线
网络。使用独立近距离无线网络，避免比赛时依赖互联网。

## 5. 图形桌面自启动

因为必须一直显示调试画面，应使用“图形桌面登录后自启动”，而不是无显示环境
的systemd服务：

```bash
cd ~/ball_control_jetson_v2
./install_desktop_autostart.sh
```

安装器会检查 `~/venvs/yolo`、`models/best.engine` 和配置文件，自动备份旧版
球控桌面启动项。异常启动（例如USB设备尚未就绪）会每3秒重试；用户在窗口按
`Q/Esc` 正常退出后不会自动拉起。手动启动和自启动共用进程锁，不会重复占用
摄像头或串口。

查询或关闭自启动：

```bash
./install_desktop_autostart.sh status
./install_desktop_autostart.sh disable
```

Jetson需启用图形桌面自动登录。NoMachine应连接这个物理桌面会话；客户端断开
不应结束Jetson桌面会话。自启动日志：

```bash
tail -f ~/ball_control_jetson_v2/logs/autostart.log
```

## 6. 完整赛前测试

同时打开TensorRT、串口、录像、NoMachine和电机，连续运行至少10分钟：

- `camera`、`inference_loop` 接近30 FPS；
- `pipeline_p95 < 33.33 ms`，`stale_dropped` 不持续增加；
- `tx_jitter_max` 较小；
- `rec_dropped=0`；
- 发送 `AA BB BB FF` 与 `AA CC CC FF` 后录像可完整回放；
- NoMachine断开再连接时，串口控制和录像不中断。
