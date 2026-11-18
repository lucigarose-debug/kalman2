"""Lectura de GPX (tracks, rutas o waypoints) con gpxpy."""
from __future__ import annotations

import gpxpy
import gpxpy.gpx

from .common import ParseError, Track, parse_time


def parse_gpx(data: bytes) -> Track:
    try:
        gpx = gpxpy.parse(data.decode("utf-8-sig", errors="replace"))
    except (gpxpy.gpx.GPXException, ValueError) as exc:
        raise ParseError(f"GPX no válido: {exc}") from exc

    track = Track(source_format="gpx")
    # Prioridad: tracks > rutas > waypoints
    for trk in gpx.tracks:
        for seg in trk.segments:
            for p in seg.points:
                track.append(p.latitude, p.longitude, p.elevation, parse_time(p.time))
    if len(track) == 0:
        for rte in gpx.routes:
            for p in rte.points:
                track.append(p.latitude, p.longitude, p.elevation, parse_time(p.time))
    if len(track) == 0:
        for p in gpx.waypoints:
            track.append(p.latitude, p.longitude, p.elevation, parse_time(p.time))
    n_seg = sum(len(t.segments) for t in gpx.tracks)
    if n_seg > 1:
        track.warnings.append(f"El GPX tiene {n_seg} segmentos; se han concatenado.")
    return track
