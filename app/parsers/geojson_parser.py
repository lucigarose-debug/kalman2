"""Lectura de GeoJSON: LineString/MultiLineString o colecciones de Points."""
from __future__ import annotations

import json

from .common import ParseError, Track, normalize_key, parse_time, to_float

# Convenciones habituales para tiempos por vértice en propiedades de líneas
LINE_TIME_KEYS = ["coordTimes", "coord_times", "times", "timestamps", "time"]
POINT_TIME_KEYS = ["time", "timestamp", "datetime", "date_time", "fecha_hora", "utc", "t"]
POINT_ELE_KEYS = ["ele", "elevation", "alt", "altitude", "altitud", "elevacion"]


def parse_geojson(data: bytes) -> Track:
    try:
        obj = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParseError(f"GeoJSON no válido: {exc}") from exc

    features = list(_features(obj))
    if not features:
        raise ParseError("El GeoJSON no contiene geometrías.")

    lines = [(g, p) for g, p in features if g.get("type") in ("LineString", "MultiLineString")]
    points = [(g, p) for g, p in features if g.get("type") == "Point"]

    track = Track(source_format="geojson")
    if lines:
        for geom, props in lines:
            parts = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
            times = _line_times(props)
            nested = bool(times) and isinstance(times[0], list)  # coordTimes por parte
            k = 0
            for i_part, part in enumerate(parts):
                sub = times[i_part] if nested and i_part < len(times) else None
                for j, c in enumerate(part):
                    t = None
                    if nested:
                        t = parse_time(sub[j]) if sub is not None and j < len(sub) else None
                    elif times is not None and k < len(times):
                        t = parse_time(times[k])
                    _append_position(track, c, t)
                    k += 1
    else:
        for geom, props in points:
            norm = {normalize_key(k): v for k, v in (props or {}).items()}
            t = next((parse_time(norm[k]) for k in POINT_TIME_KEYS if k in norm), None)
            ele_prop = next((to_float(norm[k]) for k in POINT_ELE_KEYS if k in norm), None)
            _append_position(track, geom["coordinates"], t, ele_prop)
    return track


def _features(obj):
    """Genera (geometry, properties) para cualquier tipo de objeto GeoJSON."""
    t = obj.get("type") if isinstance(obj, dict) else None
    if t == "FeatureCollection":
        for f in obj.get("features", []):
            yield from _features(f)
    elif t == "Feature":
        geom = obj.get("geometry") or {}
        if geom.get("type") == "GeometryCollection":
            for g in geom.get("geometries", []):
                yield g, obj.get("properties") or {}
        elif geom:
            yield geom, obj.get("properties") or {}
    elif t == "GeometryCollection":
        for g in obj.get("geometries", []):
            yield g, {}
    elif t in ("Point", "LineString", "MultiLineString", "MultiPoint"):
        if t == "MultiPoint":
            for c in obj.get("coordinates", []):
                yield {"type": "Point", "coordinates": c}, {}
        else:
            yield obj, {}


def _line_times(props: dict):
    for key in LINE_TIME_KEYS:
        val = props.get(key)
        if isinstance(val, list) and val:
            return val
    return None


def _append_position(track: Track, c, t, ele_override=None) -> None:
    if not isinstance(c, (list, tuple)) or len(c) < 2:
        return
    lon, lat = to_float(c[0]), to_float(c[1])
    ele = to_float(c[2]) if len(c) > 2 else ele_override
    if lat is not None and lon is not None:
        track.append(lat, lon, ele, t)
