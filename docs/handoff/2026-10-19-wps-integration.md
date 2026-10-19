# 任务交接：完整审核版与 WPS 分列复制整合

- 任务目标：以 PR #4 最新版本为基线，加入 PR #5 的安全分列复制，保留原有审核与工作项目识别。
- 实际修改内容：移植 B:D、F、H:I 三段剪贴板复制；货号 F 列文本格式提示；同批记录重新复制时要求明确确认；保留异常、重复和单价差异核对。
- 涉及文件：`src/wechat_work_recorder/app.py`、`src/wechat_work_recorder/wps_clipboard.py`、`tests/test_wps_integration.py`、`README.md`、本文件。
- 未完成事项：整合版 Windows/WPS 实机验证；等待项目负责人审核 PR。
- 测试情况：
  - 自动测试（实际运行通过）：`.venv/bin/python -m pytest -q`，128 项通过；`git diff --check` 通过。
  - 未运行：真实工资表写入；本功能不直接写入文件。
  - 需要 Windows 人工验证：整合版界面、F 列文本格式、三段同首行粘贴、J 公式计算、E/G 内容及 K 列合并布局。先前 PR #5 的实测结果不能代替整合版验证。
- 潜在风险：软件无法读取 WPS 当前选区或确认是否实际粘贴；手动换行、换起始行或重复粘贴仍可能出错。
- 下一步建议：只用账本副本按 README 步骤实测，再由项目负责人审核整合 PR；不自动合并 main。
- PR 链接：创建 PR 后填写真实链接。
