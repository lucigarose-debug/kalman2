"""Genera una trayectoria GPS sintética con ruido y outliers en los 4 formatos.

Uso:  python scripts/make_samples.py  ->  sample_data/ruta_ejemplo.{csv,gpx,kml,geojson}

La ruta "verdadera" recorre el entorno del Parque del Retiro (Madrid) en bici a
~5 m/s, muestreada a 1 Hz. Se añade ruido gaussiano (σ = 6 m horizontal,
σ = 8 m vertical) y un 1 % de saltos grandes (40–90 m) para probar el gating.
"""
from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

R = 6_371_008.8
OUT = Path(__file__).resolve().parent.parent / "sample_data"

WAYPOINTS = [  # (lat, lon)
    (40.41530, -3.68440), (40.42050, -3.68820), (40.42070, -3.67980),
    (40.41700, -3.67760), (40.41120, -3.67890), (40.40850, -3.68350),
    (40.41080, -3.68900), (40.41530, -3.68440),
]


def truth(speed=5.0, hz=1.0):
    lat0 = WAYPOINTS[0][0]
    kx = math.pi / 180 * R * math.cos(math.radians(lat0))
    ky = math.pi / 180 * R
    pts = [((lo - WAYPOINTS[0][1]) * kx, (la - lat0) * ky) for la, lo in WAYPOINTS]
    out, step = [], speed / hz
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(seg / step))
        for i in range(n):
            f = i / n
            out.append((x1 + f * (x2 - x1), y1 + f * (y2 - y1)))
    lat = [WAYPOINTS[0][0] + y / ky for _, y in out]
    lon = [WAYPOINTS[0][1] + x / kx for x, _ in out]
    return lat, lon, kx, ky


def main(seed=42):
    random.seed(seed)
    lat, lon, kx, ky = truth()
    n = len(lat)
    t0 = datetime(2026, 5, 17, 8, 30, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        nx, ny = random.gauss(0, 6), random.gauss(0, 6)
        if random.random() < 0.01:
            ang, mag = random.uniform(0, 2 * math.pi), random.uniform(40, 90)
            nx, ny = nx + mag * math.cos(ang), ny + mag * math.sin(ang)
        ele_true = 660 + 12 * math.sin(i / n * 2 * math.pi)
        rows.append({
            "lat": round(lat[i] + ny / ky, 7),
            "lon": round(lon[i] + nx / kx, 7),
            "ele": round(ele_true + random.gauss(0, 8), 1),
            "time": (t0 + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    OUT.mkdir(exist_ok=True)

    # CSV
    with open(OUT / "ruta_ejemplo.csv", "w", encoding="utf-8") as f:
        f.write("time,latitude,longitude,elevation\n")
        for r in rows:
            f.write(f"{r['time']},{r['lat']},{r['lon']},{r['ele']}\n")

    # GPX
    trkpts = "\n".join(
        f'      <trkpt lat="{r["lat"]}" lon="{r["lon"]}"><ele>{r["ele"]}</ele>'
        f'<time>{r["time"]}</time></trkpt>' for r in rows)
    (OUT / "ruta_ejemplo.gpx").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="gps-kalman-app" xmlns="http://www.topografix.com/GPX/1/1">\n'
        '  <trk><name>Ruta de ejemplo</name><trkseg>\n'
        f'{trkpts}\n  </trkseg></trk>\n</gpx>\n', encoding="utf-8")

    # KML (gx:Track)
    whens = "\n".join(f"        <when>{r['time']}</when>" for r in rows)
    coords = "\n".join(f"        <gx:coord>{r['lon']} {r['lat']} {r['ele']}</gx:coord>" for r in rows)
    (OUT / "ruta_ejemplo.kml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">\n'
        '  <Document><name>Ruta de ejemplo</name>\n    <Placemark><name>Track</name>\n'
        f'      <gx:Track>\n{whens}\n{coords}\n      </gx:Track>\n'
        '    </Placemark>\n  </Document>\n</kml>\n', encoding="utf-8")

    # GeoJSON (LineString + coordTimes)
    gj = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"name": "Ruta de ejemplo", "coordTimes": [r["time"] for r in rows]},
        "geometry": {"type": "LineString",
                     "coordinates": [[r["lon"], r["lat"], r["ele"]] for r in rows]},
    }]}
    (OUT / "ruta_ejemplo.geojson").write_text(json.dumps(gj), encoding="utf-8")
    print(f"{n} puntos escritos en {OUT}")


if __name__ == "__main__":
    main()
