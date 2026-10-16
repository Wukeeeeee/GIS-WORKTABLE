"""Startup must reject missing, incompatible, or unimportable dependencies."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def checker(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[2] / 'scripts' / 'check_runtime.py'
    spec = importlib.util.spec_from_file_location('check_runtime', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / 'backend').mkdir()
    (tmp_path / 'backend' / 'requirements.txt').write_text('# 中文\nfastapi>=0.139.0\n', encoding='utf-8')
    monkeypatch.setattr(module, '__file__', str(tmp_path / 'scripts' / 'check_runtime.py'))
    monkeypatch.setattr(module.sys, 'version_info', (3, 13, 0))
    return module


def test_ready_environment(checker, monkeypatch):
    monkeypatch.setattr(checker.metadata, 'version', lambda name: '0.139.0')
    monkeypatch.setattr(checker.importlib, 'import_module', lambda name: None)
    assert checker.main() == 0


def test_missing_dependency(checker, monkeypatch):
    def missing(name):
        raise checker.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(checker.metadata, 'version', missing)
    assert checker.main() == 1


def test_incompatible_dependency(checker, monkeypatch):
    monkeypatch.setattr(checker.metadata, 'version', lambda name: '0.100.0')
    assert checker.main() == 1


def test_broken_native_import(checker, monkeypatch):
    monkeypatch.setattr(checker.metadata, 'version', lambda name: '0.139.0')
    def broken(name):
        raise ImportError('DLL load failed')
    monkeypatch.setattr(checker.importlib, 'import_module', broken)
    assert checker.main() == 1


def test_unsupported_python(checker, monkeypatch):
    monkeypatch.setattr(checker.sys, 'version_info', (3, 10, 0))
    assert checker.main() == 1
