# 消息定位、重复审核与双击启动版

- **目标**：在当前完整界面上修复重复计时审核点击无响应、增加消息分隔和问题自动定位，主交付改为便携双击启动。
- **基线/分支**：从远端 `feat/message-price-upgrade` 的 `4f57cd6` 新建 `fix/message-review-navigation`。未从旧main开始，未修改/合并现有PR或原分支。
- **实际修改**：计时草稿不再查询空货号历史价格；审核入口异常可见。重复项增加明确独立计薪/忽略/合并/取消；裸乘15不自动确认；显式消息价匹配已导入历史且无标准价冲突时免重复提醒，但不设为默认价。随包OCR使用相对语言路径和内存输入，避免中文程序/临时目录被转换成问号。原文显示层增加间距/分隔线，完整消息与问题行分别高亮；修正长消息光标在末尾造成的定位问题。合并两个重复问题框，按消息和行号排序、自动换行，点击定位并打开统一审核。保留原功能、固定15元计时与Decimal计算。
- **涉及文件**：`ocr.py`、`app.py`、`message_widgets.py`、`review_dialog.py`、`parser.py`、`import_history.py`、版本文件、相关Qt回归测试、Windows构建workflow/启动脚本/便携说明、README及Windows测试说明。
- **数据**：不更改资料目录或表结构，不覆盖名册/绑定/价格/既有历史；忽略/合并在原 `output_audit` 表追加说明，原始消息不改。忽略决定仅当前消息批次有效，编辑/换群/重启重新导入需重新核对。没有读取或修改真实工资表，不提交本机私有数据。
- **实际运行通过**：父提交已复现 `AttributeError: 'NoneType' object has no attribute 'strip'`（重复计时无货号却查价）。基线198项通过；本轮228项自动测试通过（含30项新测试，真实Qt按钮/问题点击、计时两种写法、四种处理、长消息滚动与行号、资料及历史保留）。Linux离屏截图已检查界面分隔和布局；真实本地Tesseract英文语言包通过中文目录+内存PNG输入检查（本机未装中文包，中文加载由Windows CI验证）。
- **Windows CI实际通过**：[最终构建](https://github.com/060123ggg/wechat-work-recorder/actions/runs/39370834270) 对代码 `1066d91` 完成228项测试、打包/中文OCR加载、中文带空格路径的真实cmd双击脚本启动、Portable上传、可选安装包编译、静默安装/桌面快捷方式/安装后启动及上传。Portable约103 MB，Setup约68.4 MB。前两轮发现的Tesseract中文路径问题已解决。
- **未完成**：PR创建接口返回Forbidden，未能自动创建PR；不影响已推送分支和成功构建下载。
- **需Windows人工验证**：真实显示缩放/长消息、中文OCR、Ctrl+V焦点、旧本机资料升级、Windows安全提示、WPS副本三段粘贴。方法见 `docs/message-review-testing.md`，不将CI冒烟等同实机验收。
- **风险**：裸乘15只提供候选而非事实；合并不叠加工时/工资。无法安全拆分同一行多项工作时仍要求整理原文。复制历史不证明WPS已粘贴；便携版未签名，需完整解压，家/厂电脑资料互不自动同步。
- **下一步**：下载上述成功构建的Portable，按验收步骤确认四个重点，再由用户审核；不自行合并。
- **PR链接**：未创建（GitHub GraphQL API Forbidden）。真实分支比较页：https://github.com/060123ggg/wechat-work-recorder/compare/feat/message-price-upgrade...fix/message-review-navigation?expand=1
