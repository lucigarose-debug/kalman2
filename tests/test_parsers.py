import io
import json
import zipfile
from pathlib import Path

import pytest

from app.parsers import ParseError, parse_file

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.mark.parametrize("ext", ["csv", "gpx", "kml", "geojson"])
def test_samples_all_formats_equivalent(ext):
    t = parse_file(f"ruta.{ext}", (SAMPLES / f"ruta_ejemplo.{ext}").read_bytes())
    ref = parse_file("ruta.gpx", (SAMPLES / "ruta_ejemplo.gpx").read_bytes())
    assert len(t) == len(ref) > 100
    assert t.lat[10] == pytest.approx(ref.lat[10], abs=1e-7)
    assert t.lon[10] == pytest.approx(ref.lon[10], abs=1e-7)
    assert t.ele[10] == pytest.approx(ref.ele[10], abs=0.01)
    assert t.time[10] == pytest.approx(ref.time[10])


def test_csv_semicolon_decimal_comma_and_spanish_headers():
    data = (
        "Fecha;Hora;Latitud (°);Longitud (°);Altitud\n"
        "17/05/2026;08:30:00;40,4153;-3,6844;660\n"
        "17/05/2026;08:30:01;40,4154;-3,6845;661\n"
    ).encode("latin-1")
    t = parse_file("x.csv", data)
    assert len(t) == 2
    assert t.lat[0] == pytest.approx(40.4153)
    assert t.time[1] - t.time[0] == pytest.approx(1.0)
    assert t.ele == [660.0, 661.0]


def test_csv_epoch_ms_and_no_elevation():
    data = b"timestamp,lat,lng\n1779006600000,40.1,-3.1\n1779006602000,40.2,-3.2\n"
    t = parse_file("x.csv", data)
    assert t.time[1] - t.time[0] == pytest.approx(2.0)
    assert t.ele == [None, None]


def test_csv_missing_columns_raises():
    with pytest.raises(ParseError, match="latitud"):
        parse_file("x.csv", b"a,b\n1,2\n3,4\n")


def test_unsorted_times_are_sorted():
    data = b"time,lat,lon\n2026-01-01T00:00:02Z,40.2,-3\n2026-01-01T00:00:00Z,40.0,-3\n2026-01-01T00:00:01Z,40.1,-3\n"
    t = parse_file("x.csv", data)
    assert t.lat == [40.0, 40.1, 40.2]
    assert any("reordenado" in w for w in t.warnings)


def test_partial_times_are_dropped():
    data = b"time,lat,lon\n2026-01-01T00:00:00Z,40.0,-3\n,40.1,-3\n"
    t = parse_file("x.csv", data)
    assert t.time == [None, None]
    assert t.warnings


def test_invalid_coordinates_filtered():
    data = b"lat,lon\n40,-3\n95,-3\n0,0\n40.1,-3.1\n"
    t = parse_file("x.csv", data)
    assert len(t) == 2


def test_kml_linestring_and_kmz():
    kml = b"""<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>
    <Placemark><LineString><coordinates>-3.1,40.1,600 -3.2,40.2,610
    -3.3,40.3,620</coordinates></LineString></Placemark></Document></kml>"""
    t = parse_file("x.kml", kml)
    assert len(t) == 3 and t.lon[2] == -3.3 and t.ele[1] == 610

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("doc.kml", kml)
    t2 = parse_file("x.kmz", buf.getvalue())
    assert t2.lat == t.lat


def test_kml_points_with_timestamps():
    kml = b"""<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
    <Placemark><TimeStamp><when>2026-01-01T00:00:01Z</when></TimeStamp><Point><coordinates>-3.2,40.2</coordinates></Point></Placemark>
    <Placemark><TimeStamp><when>2026-01-01T00:00:00Z</when></TimeStamp><Point><coordinates>-3.1,40.1</coordinates></Point></Placemark>
    </Document></kml>"""
    t = parse_file("x.kml", kml)
    assert t.lat == [40.1, 40.2]


def test_kml_xxe_is_blocked():
    evil = b"""<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY x SYSTEM "file:///etc/passwd">]>
    <kml><Document><Placemark><LineString><coordinates>&x;</coordinates></LineString></Placemark></Document></kml>"""
    with pytest.raises(Exception):
        parse_file("x.kml", evil)


def test_geojson_points_feature_collection():
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"time": "2026-01-01T00:00:00Z", "altitude": 5},
         "geometry": {"type": "Point", "coordinates": [-3.1, 40.1]}},
        {"type": "Feature", "properties": {"time": "2026-01-01T00:00:05Z", "altitude": 6},
         "geometry": {"type": "Point", "coordinates": [-3.2, 40.2]}},
    ]}
    t = parse_file("x.geojson", json.dumps(gj).encode())
    assert t.ele == [5.0, 6.0]
    assert t.time[1] - t.time[0] == 5


def test_geojson_multilinestring_nested_times():
    gj = {"type": "Feature",
          "properties": {"coordTimes": [["2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z"],
                                        ["2026-01-01T00:00:02Z", "2026-01-01T00:00:03Z"]]},
          "geometry": {"type": "MultiLineString",
                       "coordinates": [[[-3.1, 40.1], [-3.2, 40.2]], [[-3.3, 40.3], [-3.4, 40.4]]]}}
    t = parse_file("x.json", json.dumps(gj).encode())
    assert len(t) == 4 and t.time[3] - t.time[0] == 3


def test_sniffing_without_extension():
    gpx = (SAMPLES / "ruta_ejemplo.gpx").read_bytes()
    assert len(parse_file("sin_extension", gpx)) > 100


def test_max_points():
    data = "lat,lon\n" + "\n".join(f"40.{i:05d},-3.0" for i in range(50))
    with pytest.raises(ParseError, match="máximo"):
        parse_file("x.csv", data.encode(), max_points=10)


def test_empty_file():
    with pytest.raises(ParseError):
        parse_file("x.gpx", b"")
