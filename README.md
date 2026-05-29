# Soldering Split Viewer

一个用于查看和维护 YOLO 训练/验证集图片清单（`train.txt` / `val.txt`）的桌面工具。

## 功能

- 加载 `split_files` 目录中的 `train.txt` 和 `val.txt`
- 左侧列表查看样本，可按文件名搜索
- 右侧预览图片，支持：滚轮缩放、适配窗口、拖拽平移、1:1
- 支持将样本在 Train/Val 之间移动
- 保存时原子写入，避免写文件中断造成损坏
- 缺失文件在列表中标红，不阻塞程序
- 关闭时若有未保存修改会提醒

## 环境

推荐解释器：

`D:\Anaconda3\envs\yolo\python.exe`

安装依赖：

```bash
D:\Anaconda3\envs\yolo\python.exe -m pip install -r requirements.txt
```

## 运行

```bash
D:\Anaconda3\envs\yolo\python.exe app.py
```

默认读取目录：

`E:\Desktop\solderingData\split_files`

可在界面右下角点击“选择 split_files”切换目录。

## 路径规则

- 每行一个图片绝对路径
- 自动去除空行
- 自动去重（保留首次出现）
- train/val 之间自动去重，避免同路径同时存在
