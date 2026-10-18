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
3. 核对 OCR 原文和表格。可修改原文后点「解析文字」，也可直接编辑表格、用「手工添加记录」补充记录。每行需包含已配置的员工、日期、群、工种、完整货号、数量、单价或工时，以及按规则计算的工资。未解析行会阻止保存，需修正原文重新解析或核对后移除无关行。
4. 点击「确认并保存模拟账本」，再次确认后选一个**新的** `.xlsx` 文件名。程序拒绝覆盖现有文件。该文件仅用于测试，不会写入真实工资表。

当前解析器要求每条工作记录在同一行。示例：`2026-10-18 张三 货号 AB-123/45 数量 10 单价 2.5` 或 `2026-10-18 张三 计时 3 小时`。真实微信截图往往含多行消息、发送者与日期分离，可能需要人工整理。OCR、群名检测和规则解析均需逐条核对，不能直接用于正式发薪。

## 开发和测试

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -e '.[test]'
.venv\Scripts\python.exe -m pytest
```

项目模块：`ocr.py` 负责本地识别，`parser.py` 负责规则解析，`employees.py` 和 `settings.py` 管理员工及群名，`payroll.py` 计算金额，`workbook.py` 定义真实账本接口并生成模拟表，`app.py` 实现窗口。

真实 WPS Excel 工资账本的工作表、列映射和重复记录处理尚未确定，`UnconfiguredWorkbookWriter.write_copy` 会拒绝写入。需要账本脱敏模板或字段说明后才能开发这一部分。尚未制作或验证 Windows 安装包；未来可用 PyInstaller 打包，但仍需处理 Tesseract 和中文语言数据的安装或分发。
