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


def frozen_ocr_in_chinese_directory(monkeypatch, tmp_path):
    root = tmp_path / '微信记工助手 测试版'
    binary = root / 'tesseract' / 'tesseract.exe'
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(root / 'WeChatWorkRecorder.exe'))
    monkeypatch.delenv('TESSDATA_PREFIX', raising=False)
    return TesseractOcr(), root


def test_bundled_ocr_streams_image_without_chinese_temp_or_tessdata_arguments(monkeypatch, tmp_path):
    import subprocess
    from PIL import Image
    engine, root = frozen_ocr_in_chinese_directory(monkeypatch, tmp_path)
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, '识别结果'.encode('utf-8'), b'')
    monkeypatch.setattr(subprocess, 'run', run)
    previous_cwd = Path.cwd()
    assert engine.recognize(Image.new('RGB', (20, 20), 'white')) == '识别结果'
    command, kwargs = calls[0]
    assert command[1:] == ['stdin', 'stdout', '-l', 'chi_sim+eng', '--tessdata-dir', 'tessdata']
    assert kwargs['input'].startswith(b'\x89PNG\r\n\x1a\n')
    assert kwargs['cwd'] == root / 'tesseract'
    assert kwargs['env']['TESSDATA_PREFIX'] == 'tessdata'
    assert Path.cwd() == previous_cwd  # No process-wide chdir or user data moves.
    assert Path(os.environ['TESSDATA_PREFIX']) == root / 'tesseract' / 'tessdata'


def test_bundled_language_check_uses_same_safe_directory(monkeypatch, tmp_path):
    import subprocess
    engine, root = frozen_ocr_in_chinese_directory(monkeypatch, tmp_path)
    def run(command, **kwargs):
        assert command[1:] == ['--list-langs', '--tessdata-dir', 'tessdata']
        assert kwargs['cwd'] == root / 'tesseract' and kwargs['env']['TESSDATA_PREFIX'] == 'tessdata'
        return subprocess.CompletedProcess(command, 0, b'List of available languages (2):\nchi_sim\neng\n', b'')
    monkeypatch.setattr(subprocess, 'run', run)
    assert engine.available_languages() == {'chi_sim', 'eng'}


def test_bundled_ocr_failure_preserves_reason(monkeypatch, tmp_path):
    import subprocess
    import pytest
    from PIL import Image
    engine, _ = frozen_ocr_in_chinese_directory(monkeypatch, tmp_path)
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs: subprocess.CompletedProcess(command, 1, b'', b'language data missing'))
    with pytest.raises(RuntimeError, match='language data missing'):
        engine.recognize(Image.new('RGB', (20, 20), 'white'))
