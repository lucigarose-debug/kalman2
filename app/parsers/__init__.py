"""Despacho de parsers por extensión (con detección por contenido como respaldo)."""
from __future__ import annotations

import os

from .common import ParseError, Track, finalize
from .csv_parser import parse_csv
from .geojson_parser import parse_geojson
from .gpx_parser import parse_gpx
from .kml_parser import parse_kml

EXTENSIONS = {
    ".csv": parse_csv, ".txt": parse_csv, ".tsv": parse_csv,
    ".gpx": parse_gpx,
    ".kml": parse_kml, ".kmz": parse_kml,
    ".geojson": parse_geojson, ".json": parse_geojson,
}

__all__ = ["parse_file", "ParseError", "Track", "EXTENSIONS"]


def _sniff(data: bytes):
    head = data[:2048].lstrip().lower()
    if data[:2] == b"PK":
        return parse_kml
    if head.startswith(b"{"):
        return parse_geojson
    if b"<gpx" in head:
        return parse_gpx
    if b"<kml" in head:
        return parse_kml
    return parse_csv


def parse_file(filename: str, data: bytes, max_points: int = 200_000) -> Track:
    if not data:
        raise ParseError("El archivo está vacío.")
    ext = os.path.splitext(filename or "")[1].lower()
    parser = EXTENSIONS.get(ext) or _sniff(data)
    track = parser(data)
    return finalize(track, max_points)
