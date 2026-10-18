"""OCR 接口和本地 Tesseract 适配器。"""
from pathlib import Path
from typing import Protocol
from PIL import Image


class OcrEngine(Protocol):
    def recognize(self, image: Image.Image) -> str: ...


class TesseractOcr:
    def __init__(self, executable: str | Path | None = None, language: str = "chi_sim+eng"):
        self.executable = str(executable) if executable else None
        self.language = language

    def recognize(self, image: Image.Image) -> str:
        import pytesseract
        if self.executable:
            pytesseract.pytesseract.tesseract_cmd = self.executable
        return pytesseract.image_to_string(image, lang=self.language)
