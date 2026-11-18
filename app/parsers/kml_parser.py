"""Lectura de KML/KMZ: gx:Track, LineString o Placemarks puntuales con TimeStamp."""
from __future__ import annotations

import io
import zipfile

from defusedxml import ElementTree as ET  # protege contra XML malicioso (XXE, bombs)

from .common import ParseError, Track, parse_time, to_float


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(el, name):
    return [c for c in el if _local(c.tag) == name]


def _iter(el, name):
    return (c for c in el.iter() if _local(c.tag) == name)


def parse_kml(data: bytes) -> Track:
    if data[:2] == b"PK":  # KMZ = zip con un .kml dentro
        data = _extract_kmz(data)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ParseError(f"KML no válido: {exc}") from exc

    track = Track(source_format="kml")

    # 1) gx:Track (registros con tiempo, p. ej. Google Earth / Locus / OsmAnd)
    for gx_track in _iter(root, "Track"):
        whens = [w.text for w in _children(gx_track, "when")]
        coords = [c.text for c in _children(gx_track, "coord")]
        for i, c in enumerate(coords):
            parts = (c or "").split()
            if len(parts) < 2:
                continue
            lon, lat = to_float(parts[0]), to_float(parts[1])
            ele = to_float(parts[2]) if len(parts) > 2 else None
            t = parse_time(whens[i]) if i < len(whens) else None
            if lat is not None and lon is not None:
                track.append(lat, lon, ele, t)
    if len(track):
        return track

    # 2) LineString (rutas sin tiempo)
    for ls in _iter(root, "LineString"):
        for coord_el in _children(ls, "coordinates"):
            _append_coord_string(track, coord_el.text)
    if len(track):
        return track

    # 3) Placemarks con Point (cada uno puede llevar TimeStamp/when)
    for pm in _iter(root, "Placemark"):
        point = next(_iter(pm, "Point"), None)
        if point is None:
            continue
        coord_el = next(_iter(point, "coordinates"), None)
        when_el = next(_iter(pm, "when"), None)
        t = parse_time(when_el.text) if when_el is not None else None
        if coord_el is not None:
            _append_coord_string(track, coord_el.text, t)
    return track


def _append_coord_string(track: Track, text: str | None, t=None) -> None:
    for tup in (text or "").split():
        parts = tup.split(",")
        if len(parts) < 2:
            continue
        lon, lat = to_float(parts[0]), to_float(parts[1])
        ele = to_float(parts[2]) if len(parts) > 2 else None
        if lat is not None and lon is not None:
            track.append(lat, lon, ele, t)


def _extract_kmz(data: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
            if not names:
                raise ParseError("El KMZ no contiene ningún archivo .kml.")
            name = "doc.kml" if "doc.kml" in names else names[0]
            info = zf.getinfo(name)
            if info.file_size > 50 * 1024 * 1024:
                raise ParseError("El KML dentro del KMZ es demasiado grande.")
            return zf.read(name)
    except zipfile.BadZipFile as exc:
        raise ParseError("KMZ corrupto.") from exc
