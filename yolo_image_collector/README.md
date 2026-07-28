# YOLO Image Collector

用于 YOLO 训练数据采集的单窗口摄像头工具。

## 运行

```bash
cd /home/ubuntu22/kwork/yolo_image_collector
./run_yolo_image_collector.sh
```

## 功能

- 实时摄像头预览
- 切换摄像头
- 设置分辨率和 FPS
- 设置保存目录、类别名、文件名前缀
- 单张采集
- 定时连拍
- 暂停/继续预览
- 自动编号保存 JPEG
- 保存采集配置
- 记录最近一次采集 session 信息

## 默认保存位置

```bash
/home/ubuntu22/kwork/yolo_image_collector/dataset/images/raw
```

文件名格式：

```text
前缀_类别_年月日_时分秒_毫秒_序号.jpg
```

示例：

```text
train_cone_20260607_191530_123_000001.jpg
```

## 快捷键

- `Space` / `Enter`：采集一张
- `A`：开始/停止连拍
- `P`：暂停/继续预览
- `S`：保存配置

## 配置文件

```bash
/home/ubuntu22/kwork/yolo_image_collector/collector_config.json
```

## 给 YOLO 使用

这个工具只负责采集原始图片。后续标注时，可以把 `dataset/images/raw` 里的图片导入 LabelImg、CVAT、Roboflow 或其他 YOLO 标注工具。
