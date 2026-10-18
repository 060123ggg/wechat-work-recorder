# 微信记工助手

Windows 桌面软件原型。用 PySide6 接收微信群聊天截图，通过本机 Tesseract OCR 识别文字，以规则提取记工信息。按件计算数量 × 单价；计时统一按 **15 元/小时**计算。不使用 AI 或付费 API。

## Windows 下载、安装、启动

1. 在 GitHub 仓库页面选择 **Code → Download ZIP**，解压到一个普通文件夹。也可以用 Git 克隆仓库的开发分支。
2. 安装 [Python 3.10 或更新版本](https://www.python.org/downloads/windows/)，安装时勾选 `py launcher`。
3. 安装 Windows 版 Tesseract OCR，勾选或额外安装 `chi_sim` 简体中文语言数据，并将 Tesseract 安装目录加入系统 PATH。安装后重新打开程序。
4. 双击项目文件夹内的 `start_windows.bat`。首次启动会自动创建 `.venv` 并安装 Python 依赖；需要联网。后续双击同一个文件启动。

若 Windows 提示找不到 Tesseract，检查 PATH 是否包含 `tesseract.exe` 所在目录，以及其 `tessdata` 目录下是否有 `chi_sim.traineddata`。一键脚本不负责安装 Python 或 Tesseract。

## 使用流程

1. 点击「设置员工和群」，每行填写一名员工（最多17名）和一个群名（最多3个）。配置保存在当前 Windows 用户的 `%APPDATA%\WechatWorkRecorder\settings.json`。同名员工暂不支持，别名尚未接入窗口配置。
2. 从群聊天复制截图，选中对应群后按 `Ctrl+V`。程序自动调用本地 OCR，并解析能明确识别的行。如果 OCR 文本中只出现一个已配置的群名，会自动选择该群；否则必须人工选择。
3. 核对 OCR 原文和表格。日期、员工昵称、货号、数量、单价和工时可分布在多行；程序沿用最近明确的日期与员工。可修改原文后点「解析文字」，也可直接编辑表格、用「手工添加记录」补充记录。修改原文后必须重新解析。未解析或疑似重复的记录会阻止保存，需人工核对。
4. 点击「确认并保存模拟账本」，再次确认后选一个**新的** `.xlsx` 文件名。程序拒绝覆盖现有文件。该文件仅用于测试，不会写入真实工资表。

解析示例：`2026-10-18 张三 货号 AB-123/45 数量 10 单价 2.5`、`2026/10/9 雪琴 8513-7 70*1.7` 或 `2026-10-18 张三 计时 3 小时`。紧凑计件写法支持 `*`、`×`、`x` 等乘号；货号中的横杠属于完整货号。支持 `3小时30分`、`3.5小时`、`计时3.5`、`计时3小时半`；不能确认的工时会提示人工核对。同一截图内的完全相同记录会被标记为疑似重复，同一次程序运行中再次保存相同记录会被阻止；跨程序重启的重复导入尚无持久校验。真实微信截图布局多变，仍可能需要人工整理。窗口显示已识别记录的工资总计。看起来像记工内容却无法解析的行会提示人工核对；OCR、群名检测和规则解析均需逐条核对，不能直接用于正式发薪。

## 开发和测试

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -e '.[test]'
.venv\Scripts\python.exe -m pytest
```

项目模块：`ocr.py` 负责本地识别，`parser.py` 负责规则解析，`employees.py` 和 `settings.py` 管理员工及群名，`payroll.py` 计算金额，`workbook.py` 定义真实账本接口并生成模拟表，`app.py` 实现窗口。

真实 WPS Excel 工资账本的工作表、列映射和重复记录处理尚未确定，`UnconfiguredWorkbookWriter.write_copy` 会拒绝写入。需要账本脱敏模板或字段说明后才能开发这一部分。尚未制作或验证 Windows 安装包；未来可用 PyInstaller 打包，但仍需处理 Tesseract 和中文语言数据的安装或分发。
