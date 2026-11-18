import math
import random

import numpy as np
import pytest

from app.kalman import KalmanParams, LocalProjection, run_kalman


def _straight_track(n=400, speed=5.0, sigma=6.0, outliers=(), seed=1):
    """Recta hacia el norte a velocidad constante + ruido gaussiano."""
    rnd = random.Random(seed)
    k = math.pi / 180 * 6_371_008.8
    lat0, lon0 = 40.0, -3.0
    cos0 = math.cos(math.radians(lat0))
    true_lat, true_lon, lat, lon = [], [], [], []
    for i in range(n):
        y = i * speed
        nx, ny = rnd.gauss(0, sigma), rnd.gauss(0, sigma)
        if i in outliers:
            nx += 150
        true_lat.append(lat0 + y / k)
        true_lon.append(lon0)
        lat.append(lat0 + (y + ny) / k)
        lon.append(lon0 + nx / (k * cos0))
    times = [float(i) for i in range(n)]
    return true_lat, true_lon, lat, lon, times


def _rmse(lat, lon, tlat, tlon):
    p = LocalProjection(np.array(tlat), np.array(tlon))
    x, y = p.forward(lat, lon)
    tx, ty = p.forward(tlat, tlon)
    return float(np.sqrt(np.mean((x - tx) ** 2 + (y - ty) ** 2)))


def test_projection_roundtrip():
    lat = np.array([40.0, 40.5, 41.0])
    lon = np.array([-3.0, -2.5, -2.0])
    p = LocalProjection(lat, lon)
    la, lo = p.inverse(*p.forward(lat, lon))
    assert np.allclose(la, lat) and np.allclose(lo, lon)


# RW no modela la velocidad: en movimiento tiene retraso, así que se le exige menos.
@pytest.mark.parametrize("model,q,factor", [("cv", 0.3, 0.7), ("rw", 5.0, 0.9)])
def test_filter_reduces_error(model, q, factor):
    tl, to, lat, lon, t = _straight_track()
    raw = _rmse(lat, lon, tl, to)
    res = run_kalman(lat, lon, [None] * len(lat), t, KalmanParams(model=model, q=q, r=6))
    assert _rmse(res["lat"], res["lon"], tl, to) < factor * raw


def test_smoother_beats_forward_filter():
    tl, to, lat, lon, t = _straight_track()
    fwd = run_kalman(lat, lon, [None] * len(lat), t, KalmanParams(q=0.3, r=6))
    rts = run_kalman(lat, lon, [None] * len(lat), t, KalmanParams(q=0.3, r=6, smoother=True))
    assert _rmse(rts["lat"], rts["lon"], tl, to) < _rmse(fwd["lat"], fwd["lon"], tl, to)


def test_gating_rejects_outliers():
    outl = {50, 120, 250, 333}
    tl, to, lat, lon, t = _straight_track(outliers=outl)
    no_gate = run_kalman(lat, lon, [None] * len(lat), t, KalmanParams(q=0.3, r=6))
    gate = run_kalman(lat, lon, [None] * len(lat), t, KalmanParams(q=0.3, r=6, gate=4))
    assert gate["stats"]["rejected"] >= len(outl)
    assert _rmse(gate["lat"], gate["lon"], tl, to) < _rmse(no_gate["lat"], no_gate["lon"], tl, to)


def test_huge_r_flattens_small_q_follows():
    tl, to, lat, lon, t = _straight_track()
    tight = run_kalman(lat, lon, [None] * len(lat), t, KalmanParams(q=50, r=0.1))
    assert tight["stats"]["rms_dev_m"] < 0.5  # sigue casi exactamente a las medidas
    smooth = run_kalman(lat, lon, [None] * len(lat), t, KalmanParams(q=0.05, r=50))
    assert smooth["stats"]["rms_dev_m"] > 3


def test_without_timestamps_uses_dt_default():
    _, _, lat, lon, _ = _straight_track(n=50)
    res = run_kalman(lat, lon, [None] * 50, [None] * 50, KalmanParams(dt_default=2.0))
    assert res["stats"]["used_timestamps"] is False
    assert len(res["lat"]) == 50


def test_elevation_filter_with_gaps():
    _, _, lat, lon, t = _straight_track(n=60)
    ele = [None, None] + [600 + random.gauss(0, 5) for _ in range(58)]
    ele[30] = None
    res = run_kalman(lat, lon, ele, t, KalmanParams(filter_ele=True, smoother=True))
    assert res["ele"][0] is None and res["ele"][1] is None
    assert res["ele"][30] is not None  # predicho a través del hueco
    assert np.std([e for e in res["ele"] if e is not None]) < 5


def test_params_validation_and_clamping():
    p = KalmanParams.from_dict({"q": 1e9, "r": -1, "model": "CV", "smoother": 1})
    assert p.q == 100.0 and p.r == 0.01 and p.model == "cv" and p.smoother is True
    with pytest.raises(ValueError):
        KalmanParams.from_dict({"model": "foo"})
    with pytest.raises(ValueError):
        KalmanParams.from_dict({"q": "abc"})
