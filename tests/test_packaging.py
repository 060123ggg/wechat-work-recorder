import os
import sys
from pathlib import Path

from wechat_work_recorder.ocr import TesseractOcr, bundled_tesseract


def test_source_run_uses_system_tesseract(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    assert bundled_tesseract() is None
    assert TesseractOcr().executable is None
    assert "TESSDATA_PREFIX" not in os.environ


def test_frozen_run_uses_bundled_tesseract_and_languages(monkeypatch, tmp_path):
    executable = tmp_path / "WeChatWorkRecorder.exe"
    binary = tmp_path / "tesseract" / "tesseract.exe"
    binary.parent.mkdir()
    binary.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    assert bundled_tesseract() == binary
    assert TesseractOcr().executable == str(binary)
    assert Path(os.environ["TESSDATA_PREFIX"]) == binary.parent / "tessdata"


def test_explicit_ocr_executable_does_not_change_language_location(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    assert TesseractOcr(executable=tmp_path / "other.exe").executable == str(tmp_path / "other.exe")
    assert "TESSDATA_PREFIX" not in os.environ
