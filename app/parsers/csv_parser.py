"""Lectura de CSV/TXT con detección automática de separador y columnas."""
from __future__ import annotations

import csv
import io

from .common import ParseError, Track, normalize_key, parse_time, to_float

LAT_KEYS = ["lat", "latitude", "latitud", "lat_deg", "latitude_deg", "y_lat", "gps_lat", "y"]
LON_KEYS = ["lon", "lng", "long", "longitude", "longitud", "lon_deg", "longitude_deg",
            "x_lon", "gps_lon", "gps_lng", "x"]
ELE_KEYS = ["ele", "elevation", "elevacion", "alt", "altitude", "altitud", "height",
            "altura", "elev", "alt_m", "altitude_m", "elevation_m", "gps_alt", "z"]
TIME_KEYS = ["time", "timestamp", "datetime", "date_time", "fecha_hora", "utc", "time_utc",
             "timestamp_utc", "gps_time", "t", "tiempo", "epoch", "unix_time"]
DATE_KEYS = ["date", "fecha", "dia"]
CLOCK_KEYS = ["time", "hora", "clock"]


def _find(headers: list[str], candidates: list[str]) -> int | None:
    for cand in candidates:
        if cand in headers:
            return headers.index(cand)
    return None


def parse_csv(data: bytes) -> Track:
    text = _decode(data)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ParseError("El CSV está vacío o no tiene cabecera.")

    headers = [normalize_key(h) for h in rows[0]]
    i_lat, i_lon = _find(headers, LAT_KEYS), _find(headers, LON_KEYS)
    if i_lat is None or i_lon is None:
        raise ParseError(
            "No se encontraron columnas de latitud/longitud. Cabeceras admitidas, por ejemplo: "
            "lat, lon / latitude, longitude / latitud, longitud. Cabeceras leídas: "
            + ", ".join(rows[0])
        )
    i_ele = _find(headers, ELE_KEYS)
    i_time = _find(headers, TIME_KEYS)
    i_date = _find(headers, DATE_KEYS)
    i_clock = _find(headers, CLOCK_KEYS)
    # Fecha y hora en columnas separadas
    combine_date = i_date is not None and i_clock is not None and i_date != i_clock

    track = Track(source_format="csv")
    bad = 0
    for row in rows[1:]:
        try:
            lat, lon = to_float(row[i_lat]), to_float(row[i_lon])
        except IndexError:
            bad += 1
            continue
        if lat is None or lon is None:
            bad += 1
            continue
        ele = to_float(row[i_ele]) if i_ele is not None and i_ele < len(row) else None
        t = None
        if combine_date and max(i_date, i_clock) < len(row):
            t = parse_time(f"{row[i_date].strip()} {row[i_clock].strip()}")
        elif i_time is not None and i_time < len(row):
            t = parse_time(row[i_time])
        track.append(lat, lon, ele, t)
    if bad:
        track.warnings.append(f"Se ignoraron {bad} filas sin coordenadas numéricas.")
    return track


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ParseError("No se pudo decodificar el CSV (se esperaba UTF-8 o Latin-1).")
