"""PyInstaller 入口；保持应用模块的相对导入不变。"""
from wechat_work_recorder.app import main


if __name__ == "__main__":
    raise SystemExit(main())
