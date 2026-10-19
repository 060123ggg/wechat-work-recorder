"""OCR 接口和本地 Tesseract 适配器。"""
import os
import sys
from pathlib import Path
from typing import Protocol
from PIL import Image


class OcrEngine(Protocol):
    def recognize(self, image: Image.Image) -> str: ...


class TesseractOcr:
    def __init__(self, executable: str | Path | None = None, language: str = "chi_sim+eng"):
        bundled = bundled_tesseract()
        self.executable = str(executable or bundled) if executable or bundled else None
        self.language = language
        # 安装包内的 OCR 与语言数据随程序分发；源码运行仍沿用本机 PATH。
        if executable is None and bundled:
            os.environ["TESSDATA_PREFIX"] = str(bundled.parent / "tessdata")

    def recognize(self, image: Image.Image) -> str:
        import pytesseract
        if self.executable:
            pytesseract.pytesseract.tesseract_cmd = self.executable
        return pytesseract.image_to_string(image, lang=self.language)


def bundled_tesseract() -> Path | None:
    """仅在冻结后的 Windows 程序旁查找随包分发的 OCR。"""
    if not getattr(sys, "frozen", False):
        return None
    path = Path(sys.executable).resolve().parent / "tesseract" / "tesseract.exe"
    return path if path.is_file() else None
