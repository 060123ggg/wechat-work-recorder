# 消息定位、重复审核与双击启动版

- **目标**：在当前完整界面上修复重复计时审核点击无响应、增加消息分隔和问题自动定位，主交付改为便携双击启动。
- **基线/分支**：从远端 `feat/message-price-upgrade` 的 `4f57cd6` 新建 `fix/message-review-navigation`。未从旧main开始，未修改/合并现有PR或原分支。
- **实际修改**：计时草稿不再查询空货号历史价格；审核入口异常可见。重复项增加明确独立计薪/忽略/合并/取消；裸乘15不自动确认。原文显示层增加间距/分隔线，完整消息与问题行分别高亮；修正长消息光标在末尾造成的定位问题。合并两个重复问题框，按消息和行号排序、自动换行，点击定位并打开统一审核。保留原功能、固定15元计时与Decimal计算。
- **涉及文件**：`app.py`、`message_widgets.py`、`review_dialog.py`、`parser.py`、`import_history.py`、版本文件、相关Qt回归测试、Windows构建workflow/启动脚本/便携说明、README及Windows测试说明。
- **数据**：不更改资料目录或表结构，不覆盖名册/绑定/价格/既有历史；忽略/合并在原 `output_audit` 表追加说明，原始消息不改。忽略决定仅当前消息批次有效，编辑/换群/重启重新导入需重新核对。没有读取或修改真实工资表，不提交本机私有数据。
- **实际运行通过**：父提交已复现 `AttributeError: 'NoneType' object has no attribute 'strip'`（重复计时无货号却查价）。基线198项通过；本轮222项自动测试通过（含24项新测试，真实Qt按钮/问题点击、计时两种写法、四种处理、长消息滚动与行号、资料及历史保留）。Linux离屏截图已检查界面分隔和布局。
- **尚未测试/未完成**：首轮Windows219项测试、打包程序与中文OCR启动通过；便携脚本中文路径冒烟失败，正在修正并重新构建，随后补最终链接；PR尚未创建。
- **需Windows人工验证**：真实显示缩放/长消息、中文OCR、Ctrl+V焦点、旧本机资料升级、Windows安全提示、WPS副本三段粘贴。方法见 `docs/message-review-testing.md`，不将CI冒烟等同实机验收。
- **风险**：裸乘15只提供候选而非事实；合并不叠加工时/工资。无法安全拆分同一行多项工作时仍要求整理原文。复制历史不证明WPS已粘贴；便携版未签名，需完整解压，家/厂电脑资料互不自动同步。
- **下一步**：构建通过后下载Portable，按验收步骤确认四个重点，再由用户审核；不自行合并。
- **PR链接**：待创建。分支比较页：https://github.com/060123ggg/wechat-work-recorder/compare/feat/message-price-upgrade...fix/message-review-navigation?expand=1
