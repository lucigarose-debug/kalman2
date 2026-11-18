from pathlib import Path

import pytest

from app import create_app

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _upload(client, name):
    with open(SAMPLES / name, "rb") as f:
        return client.post("/api/upload", data={"file": (f, name)},
                           content_type="multipart/form-data")


def test_index_and_health(client):
    assert client.get("/healthz").get_json() == {"status": "ok"}
    html = client.get("/").get_data(as_text=True)
    assert "GPS Kalman Lab" in html and "app-config" in html


@pytest.mark.parametrize("name", ["ruta_ejemplo.csv", "ruta_ejemplo.gpx",
                                  "ruta_ejemplo.kml", "ruta_ejemplo.geojson"])
def test_upload_then_filter(client, name):
    r = _upload(client, name)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["summary"]["has_time"] and body["summary"]["has_ele"]
    pts = body["points"]
    assert len(pts[0]) == 4

    f = client.post("/api/filter", json={"points": pts, "params": {"q": 0.5, "r": 6, "smoother": True}})
    assert f.status_code == 200, f.get_json()
    out = f.get_json()
    assert len(out["points"]) == len(pts)
    assert out["params"]["smoother"] is True
    assert out["stats"]["length_filtered_m"] < out["stats"]["length_raw_m"]


def test_upload_errors(client):
    r = client.post("/api/upload", data={}, content_type="multipart/form-data")
    assert r.status_code == 400
    from io import BytesIO
    r = client.post("/api/upload", data={"file": (BytesIO(b"foo,bar\n1,2\n"), "x.csv")},
                    content_type="multipart/form-data")
    assert r.status_code == 422 and "latitud" in r.get_json()["error"]


def test_filter_bad_input(client):
    assert client.post("/api/filter", data="no json").status_code == 400
    assert client.post("/api/filter", json={"points": [[1, 2]]}).status_code == 400
    r = client.post("/api/filter", json={"points": [[40, -3], [40.1, -3.1]], "params": {"model": "x"}})
    assert r.status_code == 400


def test_too_large(client):
    client.application.config["MAX_CONTENT_LENGTH"] = 1000
    from io import BytesIO
    r = client.post("/api/upload", data={"file": (BytesIO(b"x" * 5000), "x.csv")},
                    content_type="multipart/form-data")
    assert r.status_code == 413
