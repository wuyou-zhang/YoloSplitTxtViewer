# Soldering Split Viewer

一个用于查看和维护 YOLO 训练/验证/测试集图片清单（`train.txt` / `val.txt` / `test.txt` / `unused.txt`）的桌面工具。

## 功能

- 加载 `split_files` 目录中的 `train.txt` / `val.txt` / `test.txt` / `unused.txt`
- `All` 视图汇总全部图片：黄色为未划分，红色为缺少标签，已划分的项在提示中显示所属集合
- 左侧列表查看样本，可按文件名搜索；右键菜单可拷贝文件名（多选时按行拷贝多个）
- 右侧预览图片，支持：滚轮缩放、适配窗口、拖拽平移、1:1
- 支持在 Train/Val/Test/Unused 之间移动，或移除出划分
- 打开数据集时逐行校验清单路径：不属于当前数据集 `images` 目录的行标红并弹窗提醒，清单文件保持原样、不自动修改
- 执行划分时按 `All - Unused` 重新分配 Train/Val/Test，覆盖已有清单前会二次确认
- 保存时原子写入，避免写文件中断造成损坏
- 缺失文件或外部路径在列表中标红，不阻塞程序

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

首次启动未设置数据根目录，点击“显示数据路径”后选择数据集即可。界面设置（数据根目录、类别文件、比例、种子、缩放等）保存在：

`%APPDATA%\YoloSplitTxtViewer\split_config.json`

程序不内置默认数据路径；重新打包或替换 exe 不会覆盖用户配置。

## 打包为 exe

推荐优先使用项目自带的 `YoloSplitTxtViewer.spec`，产物名称与项目一致，且不会打包用户配置。

### 1. 激活环境

```bash
conda activate yolo
```

### 2. 安装 PyInstaller

```bash
python -m pip install pyinstaller
```

### 3. 打包

```bash
cd d:\Project\PycharmPorject\YoloSplitTxtViewer
python -m PyInstaller --clean --noconfirm YoloSplitTxtViewer.spec
```

### 4. 运行

打包完成后，运行：

```bash
dist\YoloSplitTxtViewer\YoloSplitTxtViewer.exe
```

一般不需要手动复制 `python311.dll`。

### 打包参数说明

| 参数                       | 说明                       |
| -------------------------- | -------------------------- |
| `-w` 或 `--windowed`   | 隐藏控制台窗口             |
| `--onefile`              | 打包成单个 exe（启动较慢，不推荐当前项目直接使用） |
| `--clean`                | 清理旧构建文件             |
| `--add-data "源;目标"` | 打包额外文件               |

如果你不想使用 `.spec` 文件，也可以直接执行：

```bash
python -m PyInstaller -w --clean --noconfirm --icon "YoloSplitTxtViewer.ico" --add-data "YoloSplitTxtViewer.ico;." --name YoloSplitTxtViewer app.py
```

## 路径规则

- 每行一个图片绝对路径
- 自动去除空行
- 自动去重（同一路径只保留首次出现，跨 train/val/test/unused 也去重）
- 数据集被复制或移动后，清单中的旧路径不会被自动改写：不属于当前数据集 `images` 目录的行保持原样并标红，加载时弹窗提醒
- 标红的行可选中后点击“移除出划分”清理，或直接重新执行划分
- 数据划分范围固定为 `All - Unused`，Unused 中的图片不参与 Train/Val/Test 分配
