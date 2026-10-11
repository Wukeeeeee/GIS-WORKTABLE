"""Launchers must never reuse a healthy service from another project."""
import json
from unittest.mock import MagicMock

import pytest

from backend import launcher


@pytest.mark.parametrize("payload, expected", [
    ({"status": "ok", "service": "soc-workbench"}, False),
    ({"status": "ok"}, False),
    ({**launcher.health_identity(), "workspace": "another-checkout"}, False),
    (launcher.health_identity(), True),
    ([], False),
])
def test_probe_requires_service_and_workspace(monkeypatch, payload, expected):
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    monkeypatch.setattr(launcher.urllib.request, "build_opener", lambda *args: opener)
    assert bool(launcher.probe(8000)) is expected


def test_default_port_conflict_does_not_switch_ports(monkeypatch):
    monkeypatch.delenv("GIS_PORT", raising=False)
    monkeypatch.setattr(launcher, "port_available", lambda port: port >= 8002)
    monkeypatch.setattr(launcher, "probe", lambda port: None)
    with pytest.raises(RuntimeError, match="Port 8000"):
        launcher.select_port()


def test_port_selection_reuses_current_checkout(monkeypatch):
    monkeypatch.delenv("GIS_PORT", raising=False)
    monkeypatch.setattr(launcher, "port_available", lambda port: False)
    monkeypatch.setattr(launcher, "probe", lambda port: launcher.health_identity() if port == 8000 else None)
    assert launcher.select_port() == 8000


def test_default_port_and_explicit_override(monkeypatch):
    monkeypatch.delenv("GIS_PORT", raising=False)
    monkeypatch.setattr(launcher, "port_available", lambda port: True)
    assert launcher.select_port() == 8000
    monkeypatch.setenv("GIS_PORT", "8002")
    assert launcher.select_port() == 8002


def test_explicit_port_conflict_fails(monkeypatch):
    monkeypatch.setenv("GIS_PORT", "8000")
    monkeypatch.setattr(launcher, "port_available", lambda port: False)
    monkeypatch.setattr(launcher, "probe", lambda port: None)
    with pytest.raises(RuntimeError):
        launcher.select_port()


def test_stop_ignores_foreign_services(monkeypatch):
    monkeypatch.delenv("GIS_PORT", raising=False)
    monkeypatch.setattr("sys.argv", ["launcher", "stop"])
    monkeypatch.setattr(launcher, "probe", lambda port: None)
    kill = MagicMock()
    monkeypatch.setattr(launcher.os, "kill", kill)
    launcher.main()
    kill.assert_not_called()
