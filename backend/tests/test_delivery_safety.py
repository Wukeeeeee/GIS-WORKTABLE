"""Submission regressions: no unlocked startup or silent feature loss."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from backend import launcher
from backend.main import _export_shp_sync


def test_start_lock_timeout_never_spawns(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(launcher, 'probe', lambda port: None)
    ticks = iter([0, 16])
    monkeypatch.setattr(launcher.time, 'monotonic', lambda: next(ticks))
    spawn = Mock()
    monkeypatch.setattr(launcher.subprocess, 'Popen', spawn)
    with pytest.raises(RuntimeError, match='Startup lock is still held'):
        launcher.start_backend(8010)
    spawn.assert_not_called()


def test_mixed_geometry_export_rejects_feature_loss():
    root = Path(__file__).resolve().parents[2]
    data = json.loads((root / 'data/sample_delivery_test.geojson').read_text(encoding='utf-8'))
    result, error = _export_shp_sync(data, 'EPSG:4326', 'mixed')
    assert result is None
    assert '混合几何' in error
