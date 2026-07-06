import numpy as np
from shapely.geometry import box

from philly_fair_measure.diagnostics.aerial_change import (
    TILE_PX,
    TilePair,
    _polygon_mask,
    _quantile_match,
    _square_bbox,
    change_metrics,
)


def test_square_bbox_pads_and_floors():
    # a 5m-wide rowhome parcel gets the 30m context floor
    tiny = box(-75.16, 39.95, -75.16006, 39.95004)
    lon0, lat0, lon1, lat1 = _square_bbox(tiny)
    height_m = (lat1 - lat0) * 111_132.0
    assert 29.0 < height_m < 31.0
    width_m = (lon1 - lon0) * 111_132.0 * np.cos(np.deg2rad(39.95))
    assert abs(width_m - height_m) < 0.5  # square in meters


def test_quantile_match_kills_illumination_shift():
    rng = np.random.default_rng(0)
    early = rng.uniform(0.2, 0.8, (64, 64))
    late = early * 0.6 + 0.3  # same scene, different exposure
    matched = _quantile_match(late, early)
    assert np.abs(matched - early).mean() < 0.01


def test_change_metrics_separate_change_from_none():
    rng = np.random.default_rng(1)
    scene = rng.uniform(0.2, 0.8, (TILE_PX, TILE_PX))
    geom = box(-75.16, 39.95, -75.1595, 39.9504)
    bbox = _square_bbox(geom)
    mask = _polygon_mask(geom, bbox)
    assert mask.any() and not mask.all()

    noisy = scene + rng.normal(0, 0.01, scene.shape)
    same = change_metrics(TilePair("p", "control", scene, noisy, mask))
    changed_scene = scene.copy()
    changed_scene[mask] = rng.uniform(0.2, 0.8, int(mask.sum()))  # structure replaced
    changed = change_metrics(TilePair("p", "demolition", scene, changed_scene, mask))

    for metric in ("score_ssim", "score_corr", "score_mad"):
        assert changed[metric] > same[metric] * 2, metric
