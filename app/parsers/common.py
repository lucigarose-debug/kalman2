"""Formato estándar de trayectoria y utilidades compartidas por los parsers."""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dateutil import parser as dateutil_parser


class ParseError(ValueError):
    """Error controlado de lectura: el mensaje se muestra al usuario."""


@dataclass
class Track:
    """Trayectoria estandarizada.

    lat, lon en grados WGS84; ele en metros (None si falta);
    time en segundos epoch UTC (None si falta).
    """

    lat: list[float] = field(default_factory=list)
    lon: list[float] = field(default_factory=list)
    ele: list[float | None] = field(default_factory=list)
    time: list[float | None] = field(default_factory=list)
    source_format: str = ""
    warnings: list[str] = field(default_factory=list)

    def append(self, lat, lon, ele=None, t=None) -> None:
        self.lat.append(float(lat))
        self.lon.append(float(lon))
        self.ele.append(None if ele is None else float(ele))
        self.time.append(t)

    def __len__(self) -> int:
        return len(self.lat)


# --------------------------------------------------------------------------- #
# Tiempo
# --------------------------------------------------------------------------- #
def parse_time(value) -> float | None:
    """Convierte casi cualquier representación de tiempo a segundos epoch UTC.

    - Números grandes: epoch en ms (>1e11) o s (>1e8).
    - Números pequeños: segundos relativos (se aceptan tal cual).
    - Cadenas: ISO 8601 o cualquier formato que entienda dateutil.
    Las fechas sin zona horaria se interpretan como UTC.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if not s or s.lower() in {"nan", "none", "null"}:
            return None
        try:
            num = float(s)
        except ValueError:
            num = None
        if num is not None and math.isfinite(num):
            return num / 1000.0 if abs(num) > 1e11 else num
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = dateutil_parser.parse(s)
            except (ValueError, OverflowError, TypeError):
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


# --------------------------------------------------------------------------- #
# Números
# --------------------------------------------------------------------------- #
def to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        f = float(value)
    else:
        s = str(value).strip().replace(" ", "")
        if not s:
            return None
        # Coma decimal europea ("40,4168") si no hay punto.
        if "," in s and "." not in s:
            s = s.replace(",", ".")
        try:
            f = float(s)
        except ValueError:
            return None
    return f if math.isfinite(f) else None


def normalize_key(name: str) -> str:
    """'Latitud (°)' -> 'latitud'; 'Elevación_m' -> 'elevacion_m'."""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = re.sub(r"\(.*?\)|\[.*?\]", "", s).strip().lower()
    s = re.sub(r"[\s\-]+", "_", s)
    return s.strip("_")


# --------------------------------------------------------------------------- #
# Validación y limpieza final (común a todos los formatos)
# --------------------------------------------------------------------------- #
def finalize(track: Track, max_points: int) -> Track:
    if len(track) == 0:
        raise ParseError("No se encontraron coordenadas en el archivo.")

    # 1) Coordenadas válidas
    keep = [
        i for i in range(len(track))
        if -90 <= track.lat[i] <= 90 and -180 <= track.lon[i] <= 180
        and not (track.lat[i] == 0 and track.lon[i] == 0)
    ]
    dropped = len(track) - len(keep)
    if dropped:
        track.warnings.append(f"Se descartaron {dropped} puntos con coordenadas no válidas.")
    if len(keep) < 2:
        raise ParseError("La trayectoria necesita al menos 2 puntos válidos.")
    _select(track, keep)

    # 2) Tiempos: o todos o ninguno
    n_time = sum(t is not None for t in track.time)
    if 0 < n_time < len(track):
        track.warnings.append(
            f"Solo {n_time} de {len(track)} puntos tienen tiempo; se ignoran los tiempos "
            "y se usará un intervalo fijo entre muestras."
        )
        track.time = [None] * len(track)
    elif n_time == len(track):
        order = sorted(range(len(track)), key=lambda i: track.time[i])
        if order != list(range(len(track))):
            track.warnings.append("Los puntos no estaban ordenados por tiempo; se han reordenado.")
            _select(track, order)

    # 3) Elevación: si casi no hay, se descarta
    n_ele = sum(e is not None for e in track.ele)
    if 0 < n_ele < 0.5 * len(track):
        track.warnings.append("Menos de la mitad de los puntos tienen elevación; se ignora.")
        track.ele = [None] * len(track)

    # 4) Límite de tamaño
    if len(track) > max_points:
        raise ParseError(
            f"La trayectoria tiene {len(track)} puntos; el máximo admitido es {max_points}."
        )
    return track


def _select(track: Track, idx: list[int]) -> None:
    track.lat = [track.lat[i] for i in idx]
    track.lon = [track.lon[i] for i in idx]
    track.ele = [track.ele[i] for i in idx]
    track.time = [track.time[i] for i in idx]
