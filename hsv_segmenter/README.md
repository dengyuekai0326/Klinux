# HSV Segmenter

OpenCV HSV 视觉分割辅助工具。新版默认使用单窗口 UI，支持多段 HSV、实时预览、Mask/分割结果面板增删、摄像头切换、曝光/白平衡/增益等常见摄像头属性调节，并可导出参数 JSON。

## 运行

```bash
cd /home/ubuntu22/kwork/hsv_segmenter
python3 hsv_segmenter_gui.py --camera 0 --output hsv_params.json
```

## UI

- 左侧：摄像头、HSV、曝光、白平衡、增益等控制
- HSV 阈值：支持新增/删除多个范围，每段可单独启用/禁用，最终 Mask 会自动 OR 合并
- HSV 参考表：可展开常见颜色参考，支持套用到当前段或新增为一段。内置红/橙/黄/绿/青/蓝/紫/粉/白/灰/黑/棕/肤色等常用起点阈值
- 右侧：视图面板，可添加/删除 `原图`、`Mask`、`分割结果`、`HSV图`
- 顶部：保存参数、复制 HSV、打印 JSON

## 启动器

桌面图标和应用菜单会调用：

```bash
/home/ubuntu22/kwork/hsv_segmenter/run_hsv_segmenter.sh
```

如果把这个工程复制到另一台电脑或另一个用户目录，进入工程目录后运行：

```bash
./install_desktop_shortcut.sh
```

脚本会按当前路径重新生成桌面图标和应用菜单入口。

## 导出格式

保存文件示例：

```json
{
  "camera_index": 0,
  "hsv": {
    "lower": [0, 0, 0],
    "upper": [179, 255, 255]
  },
  "hsv_ranges": [
    {
      "name": "红1",
      "enabled": true,
      "lower": [0, 80, 80],
      "upper": [10, 255, 255]
    },
    {
      "name": "红2",
      "enabled": true,
      "lower": [170, 80, 80],
      "upper": [179, 255, 255]
    }
  ],
  "ui_controls": {
    "auto_exposure": true,
    "exposure": 50.0
  },
  "active_views": ["原图", "Mask", "分割结果"],
  "camera_readback": {}
}
```

其中 `hsv_ranges` 适合红色这种跨 Hue 边界的颜色：

```python
mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
for item in hsv_ranges:
    if not item["enabled"]:
        continue
    part = cv2.inRange(hsv, np.array(item["lower"]), np.array(item["upper"]))
    mask = cv2.bitwise_or(mask, part)
```

注意：自动曝光、白平衡、增益等属性是否生效取决于摄像头驱动。脚本会尝试设置，并在导出 JSON 的 `camera_readback` 中记录设备实际读回值。
