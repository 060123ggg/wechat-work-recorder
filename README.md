# 微信记工助手

Windows 桌面软件原型。使用 PySide6 接收粘贴的微信群截图，使用本机 Tesseract OCR 识别文字，以规则解析记工信息，按件或按每小时 **15 元**计算工资。第一版不使用 AI 或付费 API。

## 当前范围

- `Ctrl+V` 粘贴截图并显示 OCR 原文，供人工核对。
- 业务接口支持最多 17 名员工和 3 个微信群；姓名、别名及群标识须按实际情况配置。当前没有预置真实名单。
- 解析示例格式：`2026-10-18 张三 货号 AB-123 数量 10 单价 2.5` 或 `2026-10-18 张三 计时 3 小时`。一行一条，缺失或含糊的信息进入警告列表，不自动记账。
- 工资表模块提供预览和写入副本接口。取得真实 WPS Excel 模板及列映射前，写入会明确拒绝；原始工资表不会被修改。

当前窗口只完成截图粘贴与 OCR 原文展示。规则解析、人工确认、员工设置和账本映射尚未接入窗口，不能用于正式发薪。

## Windows 本地运行

安装 Python 3.10+、Tesseract OCR 及其 `chi_sim` 中文语言数据；确认 `tesseract` 在 PATH 中。若安装在其他位置，可在代码中向 `TesseractOcr(executable=...)` 传入路径。建议在项目目录运行：

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e '.[test]'
python -m pytest
wechat-work-recorder
```

WPS 可以打开 `.xlsx`，后续使用 `openpyxl` 对账本**副本**写入。含宏或复杂公式的模板须先做兼容性验证。OCR 对图片质量、聊天布局和消息上下文敏感，所有识别结果都需要人工确认。

## 项目结构

- `src/wechat_work_recorder/models.py`：记录和员工数据结构。
- `ocr.py`：OCR 接口和本地 Tesseract 适配器。
- `parser.py`：保守规则解析。
- `payroll.py`：工资计算。
- `employees.py`：员工与群配置接口。
- `workbook.py`：账本预览与写入副本接口。
- `app.py`：PySide6 粘贴窗口。
- `tests/`：业务模块基础测试。

## 后续接入资料

需要真实员工名单及别名、三个群的标识、典型聊天截图和工资账本的脱敏副本或字段说明，才能完善消息上下文、人工确认和 Excel 列映射。不要在配置文件中保存敏感工资数据。

## 打包准备

业务模块与窗口分离，可在 Windows 上使用 PyInstaller 构建；需将 Tesseract 可执行文件及 `chi_sim` 语言数据作为独立运行依赖或按其许可证一起分发。当前尚未生成或验证 Windows 安装包。
