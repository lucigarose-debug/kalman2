"""Rutas HTTP: interfaz, subida/estandarización y filtrado."""
from __future__ import annotations

import math

from flask import Blueprint, current_app, jsonify, render_template, request

from .kalman import KalmanParams, run_kalman, track_summary
from .parsers import EXTENSIONS, ParseError, parse_file

bp = Blueprint("main", __name__)


def _pack(lat, lon, ele, times):
    """Formato estándar de intercambio: [[lat, lon, ele|null, t|null], ...]."""
    return [
        [round(a, 7), round(o, 7),
         None if e is None else round(e, 2),
         None if t is None else round(t, 3)]
        for a, o, e, t in zip(lat, lon, ele, times)
    ]


def _unpack(points):
    max_points = current_app.config["MAX_POINTS"]
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("Se necesitan al menos 2 puntos.")
    if len(points) > max_points:
        raise ValueError(f"Demasiados puntos (máximo {max_points}).")
    lat, lon, ele, times = [], [], [], []
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            raise ValueError("Formato de punto no válido.")
        a, o = float(p[0]), float(p[1])
        if not (math.isfinite(a) and math.isfinite(o)):
            raise ValueError("Coordenadas no finitas.")
        lat.append(a)
        lon.append(o)
        ele.append(float(p[2]) if len(p) > 2 and p[2] is not None else None)
        times.append(float(p[3]) if len(p) > 3 and p[3] is not None else None)
    if any(t is None for t in times):
        times = [None] * len(times)
    return lat, lon, ele, times


@bp.get("/")
def index():
    cfg = current_app.config
    return render_template(
        "index.html",
        google_key=cfg["GOOGLE_MAPS_API_KEY"],
        google_map_id=cfg["GOOGLE_MAPS_MAP_ID"],
        defaults=KalmanParams().to_dict(),
        accept=",".join(sorted(EXTENSIONS)),
        max_mb=cfg["MAX_UPLOAD_MB"],
    )


@bp.get("/healthz")
def healthz():
    return jsonify(status="ok")


@bp.post("/api/upload")
def upload():
    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify(error="No se ha recibido ningún archivo."), 400
    data = f.read()
    try:
        track = parse_file(f.filename, data, current_app.config["MAX_POINTS"])
    except ParseError as exc:
        return jsonify(error=str(exc)), 422
    except Exception:  # archivos corruptos con errores imprevistos
        current_app.logger.exception("Fallo al leer %s", f.filename)
        return jsonify(error="No se pudo leer el archivo. ¿Es un CSV, GPX, KML o GeoJSON válido?"), 422

    return jsonify(
        name=f.filename,
        format=track.source_format,
        points=_pack(track.lat, track.lon, track.ele, track.time),
        summary=track_summary(track.lat, track.lon, track.ele, track.time),
        warnings=track.warnings,
    )


@bp.post("/api/filter")
def filter_track():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Se esperaba un cuerpo JSON."), 400
    try:
        lat, lon, ele, times = _unpack(body.get("points"))
        params = KalmanParams.from_dict(body.get("params"))
    except (TypeError, ValueError) as exc:
        return jsonify(error=str(exc)), 400

    result = run_kalman(lat, lon, ele, times, params)
    return jsonify(
        points=_pack(result["lat"], result["lon"], result["ele"], times),
        stats=result["stats"],
        params=params.to_dict(),
    )
