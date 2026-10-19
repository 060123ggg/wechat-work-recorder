# 消息识别与项目价格库升级

- **目标**：从完整 Windows 安装版 `1683fc8` 新建 `feat/message-price-upgrade`，保留整合版界面、OCR、员工/昵称管理、打包、模拟账本及 WPS 三段复制。
- **修改**：统一消息边界与原文行号；正文工作日期优先、缺年用发送年；完整货号/单位/中文项目解析和消息内继承；计时备注固定15元；本机项目、别名、标准价及十月价格导入；单次特殊价审核；未知员工/日期人工选择；跨重启重复提醒与输出追溯；已确认批次价格快照。版本升至0.2.0。
- **文件**：`parser.py`、`message_context.py`、`message_view.py`、`wechat_text.py`、`catalog.py`、`catalog_dialog.py`、`import_history.py`、`app.py`、`review_dialog.py`、模型/计算/模拟账本、67项新增测试、脱敏 `october_prices.csv`、打包配置、README及价格库说明。
- **资料与隐私**：原工资文件只读，读取前后校验未变化。随包CSV仅十月39个项目/54条价格统计，不含员工、昵称或工资明细；26个单价项目、13个多价项目。用户确认导入后初始化单价，多价不自动选；跨月旧货号数据仅作身份识别。
- **实际测试**：修改前131项通过；修改后198项通过（含全部旧测试）；`git diff --check`、Python编译、YAML解析、版本一致性检查通过；同轮Linux PyInstaller构建和随包资源/OCR启动检查通过。最终代码 `facee80` 的 [Windows Actions](https://github.com/060123ggg/wechat-work-recorder/actions/runs/39291081102) 全部成功：198项测试、打包/OCR启动、安装程序编译、静默安装、桌面快捷方式、安装后启动及安装包上传。
- **未运行/人工验证**：真实微信截图准确率、真实多选复制布局、用户电脑升级数据保留与WPS副本粘贴必须Windows人工验证；CI使用合成数据和offscreen窗口，不代表已在用户电脑验证。
- **风险/未完成**：OCR和不规范文本不保证百分之百；高度相似提醒可能误报，须人决定。多条含糊计件挤在同一行可要求拆行审核。复制历史不证明WPS已入账，无法核实目标公式/选区；安装包未签名。
- **下一步**：按 `docs/price-library.md` 升级与测试；先备份APPDATA，同一用户安装0.2.0，确认员工/昵称仍在，再明确导入十月价格，只使用新测试表或工资表副本。
- **PR链接**：未创建：本环境GitHub GraphQL API返回Forbidden。[可创建PR的真实分支比较页](https://github.com/060123ggg/wechat-work-recorder/compare/feat/windows-installer...feat/message-price-upgrade?expand=1)。父分支为 `feat/windows-installer`，没有合并main或现有PR。

安装包：上述成功运行的 Artifacts → `WeChatWorkRecorder-Windows-Setup`，解压后安装 `WeChatWorkRecorder-Setup-0.2.0.exe`。
