# Windows 安装包任务交接

- **任务目标**：从 WPS 整合版制作无需另装 Python 的 Windows 安装程序，保留 PR #4 与 WPS 三段复制功能。
- **实际修改**：新增 PyInstaller + Inno Setup 配置、Windows Actions 构建/安装后冒烟测试；安装包携带 Tesseract 和中英文 OCR 数据；冻结程序自动选用随包 OCR；README 增加下载与安装说明。未改工资计算、解析或真实账本写入。
- **涉及文件**：`.github/workflows/windows-installer.yml`、`packaging/windows/`、`src/wechat_work_recorder/ocr.py`、`src/wechat_work_recorder/app.py`、`tests/test_packaging.py`、`README.md`、本文件。
- **未完成事项**：安装包尚未代码签名；Windows 用户实机操作仍待验证。
- **测试情况**：云端自动测试 131 项通过；`git diff --check` 和 Python 编译检查通过。Linux 上 PyInstaller 实际构建成功，打包程序在提供中英文语言数据后通过启动冒烟测试。[Windows Actions 运行 #3](https://github.com/060123ggg/wechat-work-recorder/actions/runs/39232714724) 成功：131 项自动测试、Windows 打包、随包 OCR 启动、安装包编译、静默安装后启动以及安装包上传均通过。截图 OCR 准确率、桌面快捷方式、私有设置持久化和 WPS 粘贴仍需 Windows 人工验证。
- **潜在风险**：第三方 Windows Tesseract 由 Chocolatey 构建时安装；F 列含横杠货号仍应预设为文本；软件无法检查 WPS 当前选区及公式。程序不读取或改写真实工资账本。
- **下一步建议**：先核查 Actions 成功生成安装包，再在 Windows 64 位电脑安装并用工资表副本回归测试。
- **PR 链接**：待创建后填写真实链接。
