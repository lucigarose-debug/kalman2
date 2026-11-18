"""Filtro de Kalman (y suavizador RTS opcional) para trayectorias GPS.

Modelo
------
Las coordenadas geográficas se proyectan a un plano tangente local (metros,
equirectangular centrado en la trayectoria). Con Q y R diagonales, los ejes
este, norte y vertical son independientes, así que se filtra cada eje con un
modelo 1D:

* ``cv`` – velocidad constante. Estado [posición, velocidad]; el ruido del
  proceso es una aceleración blanca de desviación típica ``q`` (m/s²):
      Q = q² · [[dt⁴/4, dt³/2], [dt³/2, dt²]]
* ``rw`` – paseo aleatorio (posición constante). Estado [posición]; el ruido
  del proceso es una velocidad blanca de desviación típica ``q`` (m/s):
      Q = q² · dt

Medida: z = posición + ruido, R = r² (m²).

Como los ejes este y norte comparten Q, R, dt y las mismas decisiones de
actualización, su covarianza evoluciona igual: se calcula una sola vez y se
aplica a ambas columnas (más rápido y numéricamente idéntico).

``dt`` sale de las marcas de tiempo; si no las hay, se usa ``dt_default``.
El paso de "gating" descarta medidas cuya distancia de Mahalanobis a la
predicción supera ``gate`` (σ); tras 5 rechazos seguidos se fuerza la
actualización para que el filtro no se quede "perdido" tras un salto real.
"""
from __future__ import annotations

import math
import time as _time
from dataclasses import asdict, dataclass

import numpy as np

EARTH_RADIUS_M = 6_371_008.8
MAX_CONSECUTIVE_REJECTS = 5


@dataclass
class KalmanParams:
    model: str = "cv"          # "cv" | "rw"
    q: float = 0.5             # σ del ruido del proceso (m/s² en CV, m/s en RW)
    r: float = 5.0             # σ del ruido de medida horizontal (m)
    smoother: bool = False     # pasada hacia atrás Rauch–Tung–Striebel
    gate: float = 0.0          # rechazo de outliers en σ (0 = desactivado)
    filter_ele: bool = True    # filtrar también la elevación
    q_ele: float = 0.2         # σ ruido de proceso vertical
    r_ele: float = 10.0        # σ ruido de medida vertical (m)
    dt_default: float = 1.0    # s entre muestras si no hay tiempos
    vel0: float = 10.0         # σ inicial de la velocidad (m/s), solo CV

    LIMITS = {
        "q": (1e-4, 100.0), "r": (0.01, 1000.0), "gate": (0.0, 50.0),
        "q_ele": (1e-4, 100.0), "r_ele": (0.01, 1000.0),
        "dt_default": (1e-3, 3600.0), "vel0": (0.01, 500.0),
    }

    @classmethod
    def from_dict(cls, d: dict | None) -> "KalmanParams":
        d = d or {}
        p = cls()
        model = str(d.get("model", p.model)).lower()
        if model not in ("cv", "rw"):
            raise ValueError("model debe ser 'cv' o 'rw'.")
        p.model = model
        for key, (lo, hi) in cls.LIMITS.items():
            if key in d and d[key] is not None:
                try:
                    val = float(d[key])
                except (TypeError, ValueError):
                    raise ValueError(f"Parámetro '{key}' no numérico.") from None
                if not math.isfinite(val):
                    raise ValueError(f"Parámetro '{key}' no finito.")
                setattr(p, key, min(max(val, lo), hi))
        for key in ("smoother", "filter_ele"):
            if key in d:
                setattr(p, key, bool(d[key]))
        return p

    def to_dict(self) -> dict:
        out = asdict(self)
        out.pop("LIMITS", None)
        return out


# --------------------------------------------------------------------------- #
# Proyección local
# --------------------------------------------------------------------------- #
class LocalProjection:
    """Equirectangular centrada en la trayectoria. Biyectiva, así que la
    pequeña distorsión en rutas muy largas no afecta al ida-y-vuelta."""

    def __init__(self, lat: np.ndarray, lon: np.ndarray):
        self.lat0 = float(np.mean(lat))
        self.lon0 = float(np.mean(lon))
        self.k = math.pi / 180.0 * EARTH_RADIUS_M
        self.cos0 = math.cos(math.radians(self.lat0))

    def forward(self, lat, lon):
        x = (np.asarray(lon) - self.lon0) * self.k * self.cos0
        y = (np.asarray(lat) - self.lat0) * self.k
        return x, y

    def inverse(self, x, y):
        lat = np.asarray(y) / self.k + self.lat0
        lon = np.asarray(x) / (self.k * self.cos0) + self.lon0
        return lat, lon


# --------------------------------------------------------------------------- #
# Núcleos 1D (covarianza compartida entre las m columnas de Z)
# --------------------------------------------------------------------------- #
def _kf_cv(Z, dts, q, r, gate, vel0, smooth):
    """Z: lista de N filas con m valores (fila con algún None = sin medida)."""
    n, m = len(Z), len(Z[0])
    measured = [all(v is not None for v in row) for row in Z]
    if not any(measured):
        return [None] * n, 0
    first = measured.index(True)
    q2, r2 = q * q, r * r

    pos = list(Z[first])
    vel = [0.0] * m
    a, b, c = r2, 0.0, vel0 * vel0           # P = [[a, b], [b, c]]

    out_pos = [None] * n
    xf_p, xf_v = [None] * n, [None] * n      # estados filtrados
    xp_p, xp_v = [None] * n, [None] * n      # estados predichos
    Pf, Pp = [None] * n, [None] * n          # covarianzas (a, b, c)
    rejected, consecutive = 0, 0

    for k in range(first, n):
        if k > first:
            dt = dts[k]
            pos = [pos[j] + vel[j] * dt for j in range(m)]
            dt2 = dt * dt
            a = a + 2 * dt * b + dt2 * c + q2 * dt2 * dt2 / 4
            b = b + dt * c + q2 * dt2 * dt / 2
            c = c + q2 * dt2
        xp_p[k], xp_v[k], Pp[k] = pos[:], vel[:], (a, b, c)

        if measured[k]:
            S = a + r2
            y = [Z[k][j] - pos[j] for j in range(m)]
            accept = True
            if gate > 0 and k > first:
                d = math.sqrt(sum(v * v for v in y) / S)
                if d > gate and consecutive < MAX_CONSECUTIVE_REJECTS:
                    accept = False
            if accept:
                consecutive = 0
                K1, K2 = a / S, b / S
                pos = [pos[j] + K1 * y[j] for j in range(m)]
                vel = [vel[j] + K2 * y[j] for j in range(m)]
                a, b, c = (1 - K1) * a, (1 - K1) * b, c - K2 * b
            else:
                consecutive += 1
                rejected += 1
        xf_p[k], xf_v[k], Pf[k] = pos[:], vel[:], (a, b, c)
        out_pos[k] = pos[:]

    if smooth and n - first > 1:
        sp, sv = xf_p[n - 1][:], xf_v[n - 1][:]
        out_pos[n - 1] = sp[:]
        for k in range(n - 2, first - 1, -1):
            dt = dts[k + 1]
            fa, fb, fc = Pf[k]
            A, B, Cc = Pp[k + 1]
            # M = P_f · Fᵀ ; G = M · P_pred⁻¹
            m11, m12, m21, m22 = fa + fb * dt, fb, fb + fc * dt, fc
            det = A * Cc - B * B
            if det <= 1e-18:
                out_pos[k] = xf_p[k][:]
                sp, sv = xf_p[k][:], xf_v[k][:]
                continue
            i11, i12, i22 = Cc / det, -B / det, A / det
            g11 = m11 * i11 + m12 * i12
            g12 = m11 * i12 + m12 * i22
            g21 = m21 * i11 + m22 * i12
            g22 = m21 * i12 + m22 * i22
            new_p, new_v = [], []
            for j in range(m):
                dp = sp[j] - xp_p[k + 1][j]
                dv = sv[j] - xp_v[k + 1][j]
                new_p.append(xf_p[k][j] + g11 * dp + g12 * dv)
                new_v.append(xf_v[k][j] + g21 * dp + g22 * dv)
            sp, sv = new_p, new_v
            out_pos[k] = sp[:]
    return out_pos, rejected


def _kf_rw(Z, dts, q, r, gate, smooth):
    n, m = len(Z), len(Z[0])
    measured = [all(v is not None for v in row) for row in Z]
    if not any(measured):
        return [None] * n, 0
    first = measured.index(True)
    q2, r2 = q * q, r * r
    pos, P = list(Z[first]), r2
    out_pos = [None] * n
    xf, xp, Pf, Pp = [None] * n, [None] * n, [None] * n, [None] * n
    rejected, consecutive = 0, 0

    for k in range(first, n):
        if k > first:
            P = P + q2 * dts[k]
        xp[k], Pp[k] = pos[:], P
        if measured[k]:
            S = P + r2
            y = [Z[k][j] - pos[j] for j in range(m)]
            accept = True
            if gate > 0 and k > first:
                d = math.sqrt(sum(v * v for v in y) / S)
                if d > gate and consecutive < MAX_CONSECUTIVE_REJECTS:
                    accept = False
            if accept:
                consecutive = 0
                K = P / S
                pos = [pos[j] + K * y[j] for j in range(m)]
                P = (1 - K) * P
            else:
                consecutive += 1
                rejected += 1
        xf[k], Pf[k] = pos[:], P
        out_pos[k] = pos[:]

    if smooth and n - first > 1:
        s = xf[n - 1][:]
        for k in range(n - 2, first - 1, -1):
            G = Pf[k] / Pp[k + 1] if Pp[k + 1] > 0 else 0.0
            s = [xf[k][j] + G * (s[j] - xp[k + 1][j]) for j in range(m)]
            out_pos[k] = s[:]
    return out_pos, rejected


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def _time_steps(times, dt_default: float) -> list[float]:
    n = len(times)
    if n and all(t is not None for t in times):
        return [0.0] + [max(0.0, times[k] - times[k - 1]) for k in range(1, n)]
    return [0.0] + [dt_default] * (n - 1)


def _path_length(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.sum(np.hypot(np.diff(x), np.diff(y))))


def run_kalman(lat, lon, ele, times, params: KalmanParams) -> dict:
    t0 = _time.perf_counter()
    lat_a, lon_a = np.asarray(lat, float), np.asarray(lon, float)
    proj = LocalProjection(lat_a, lon_a)
    x, y = proj.forward(lat_a, lon_a)
    dts = _time_steps(times, params.dt_default)

    Z = [[float(xi), float(yi)] for xi, yi in zip(x, y)]
    if params.model == "cv":
        est, rejected = _kf_cv(Z, dts, params.q, params.r, params.gate, params.vel0,
                               params.smoother)
    else:
        est, rejected = _kf_rw(Z, dts, params.q, params.r, params.gate, params.smoother)
    fx = np.array([e[0] for e in est])
    fy = np.array([e[1] for e in est])
    flat, flon = proj.inverse(fx, fy)

    fele = list(ele)
    if params.filter_ele and any(e is not None for e in ele):
        Ze = [[e] if e is not None else [None] for e in ele]
        if params.model == "cv":
            est_e, _ = _kf_cv(Ze, dts, params.q_ele, params.r_ele, 0.0, 1.0, params.smoother)
        else:
            est_e, _ = _kf_rw(Ze, dts, params.q_ele, params.r_ele, 0.0, params.smoother)
        fele = [e[0] if e is not None else None for e in est_e]

    dev = np.hypot(fx - x, fy - y)
    stats = {
        "n": len(lat_a),
        "rejected": rejected,
        "length_raw_m": round(_path_length(x, y), 1),
        "length_filtered_m": round(_path_length(fx, fy), 1),
        "rms_dev_m": round(float(np.sqrt(np.mean(dev ** 2))), 2),
        "max_dev_m": round(float(np.max(dev)), 2),
        "used_timestamps": all(t is not None for t in times),
        "elapsed_ms": round((_time.perf_counter() - t0) * 1000, 1),
    }
    return {"lat": flat.tolist(), "lon": flon.tolist(), "ele": fele, "stats": stats}


def track_summary(lat, lon, ele, times) -> dict:
    lat_a, lon_a = np.asarray(lat, float), np.asarray(lon, float)
    x, y = LocalProjection(lat_a, lon_a).forward(lat_a, lon_a)
    has_time = all(t is not None for t in times)
    has_ele = any(e is not None for e in ele)
    out = {
        "n": len(lat_a),
        "has_time": has_time,
        "has_ele": has_ele,
        "length_m": round(_path_length(x, y), 1),
        "bounds": [[float(lat_a.min()), float(lon_a.min())],
                   [float(lat_a.max()), float(lon_a.max())]],
    }
    if has_time:
        dur = times[-1] - times[0]
        out["duration_s"] = round(dur, 1)
        out["median_dt_s"] = round(float(np.median(np.diff(times))), 3) if len(times) > 1 else None
        out["start_utc"] = times[0]
    if has_ele:
        e = [v for v in ele if v is not None]
        out["ele_min"], out["ele_max"] = round(min(e), 1), round(max(e), 1)
    return out
