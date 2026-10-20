"""HTTP regressions for the user-controlled upload filename boundary."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import main


@pytest.mark.parametrize("client_filename", [r"..\..\escape.geojson", "../../escape.geojson"])
def test_upload_filename_cannot_escape_upload_directory(tmp_path, monkeypatch, client_filename):
    output_dir = tmp_path / "workspace-output"
    upload_dir = output_dir / "uploads"
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(main, "_register_layer", lambda *_args, **_kwargs: {})
    payload = b'{"type":"FeatureCollection","features":[]}'

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": (client_filename, payload, "application/geo+json")},
        )

    assert response.status_code == 200
    assert response.json()["name"] == "escape.geojson"
    assert (upload_dir / "escape.geojson").read_bytes() == payload
    assert not (output_dir / "escape.geojson").exists()
