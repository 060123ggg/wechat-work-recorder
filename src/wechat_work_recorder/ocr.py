"""OCR 接口和本地 Tesseract 适配器。"""
import os
import sys
import io
import subprocess
from pathlib import Path
from typing import Protocol
from PIL import Image


class OcrEngine(Protocol):
    def recognize(self, image: Image.Image) -> str: ...


class TesseractOcr:
    def __init__(self, executable: str | Path | None = None, language: str = "chi_sim+eng"):
        bundled = bundled_tesseract()
        self.executable = str(executable or bundled) if executable or bundled else None
        self.bundle_directory = bundled.parent if executable is None and bundled else None
        self.language = language
        # 安装包内的 OCR 与语言数据随程序分发；源码运行仍沿用本机 PATH。
        if executable is None and bundled:
            os.environ["TESSDATA_PREFIX"] = str(bundled.parent / "tessdata")

    def recognize(self, image: Image.Image) -> str:
        if self.bundle_directory:
            # Windows Tesseract uses narrow paths for tessdata/input files. Keep
            # these arguments ASCII; Python starts it with a Unicode-aware cwd.
            # PNG via stdin also avoids Chinese Windows user/TEMP path problems.
            buffer = io.BytesIO()
            image.save(buffer, format='PNG')
            return self._run_bundled('stdin', 'stdout', '-l', self.language,
                                     '--tessdata-dir', 'tessdata', image=buffer.getvalue())
        import pytesseract
        if self.executable:
            pytesseract.pytesseract.tesseract_cmd = self.executable
        return pytesseract.image_to_string(image, lang=self.language)

    def available_languages(self) -> set[str]:
        if self.bundle_directory:
            output = self._run_bundled('--list-langs', '--tessdata-dir', 'tessdata')
            return {line.strip() for line in output.splitlines()[1:] if line.strip()}
        import pytesseract
        if self.executable:
            pytesseract.pytesseract.tesseract_cmd = self.executable
        return set(pytesseract.get_languages(config=''))

    def _run_bundled(self, *arguments, image=None):
        environment = dict(os.environ, TESSDATA_PREFIX='tessdata')
        result = subprocess.run([self.executable, *arguments], cwd=self.bundle_directory,
            env=environment, input=image, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=120, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            detail = result.stderr.decode('utf-8', errors='replace')[-2000:]
            raise RuntimeError(f'本地OCR失败（{result.returncode}）：{detail}')
        return result.stdout.decode('utf-8')


def bundled_tesseract() -> Path | None:
    """仅在冻结后的 Windows 程序旁查找随包分发的 OCR。"""
    if not getattr(sys, "frozen", False):
        return None
    path = Path(sys.executable).resolve().parent / "tesseract" / "tesseract.exe"
    return path if path.is_file() else None
