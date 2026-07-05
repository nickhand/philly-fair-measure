import numpy as np
from scipy.sparse.csgraph import connected_components
from sklearn.neighbors import radius_neighbors_graph

from philly_assessments.features.market_areas import (
    CONTIGUITY_RADIUS_M,
    MIN_SPLIT_PARCELS,
    _enforce_contiguity,
)


def _components(pts: np.ndarray) -> int:
    graph = radius_neighbors_graph(pts, radius=CONTIGUITY_RADIUS_M, mode="connectivity")
    n, _ = connected_components(graph, directed=False)
    return int(n)


def test_enforce_contiguity_splits_large_disconnected_pocket():
    rng = np.random.default_rng(0)
    n = MIN_SPLIT_PARCELS + 30
    blob_a = rng.normal([0.0, 0.0], 40, (n, 2))
    blob_b = rng.normal([5000.0, 0.0], 40, (n, 2))  # 5 km away: a separate blob
    xy = np.vstack([blob_a, blob_b])
    assigned = np.zeros(2 * n, dtype=np.int64)  # one label spanning both blobs

    new, parent = _enforce_contiguity(assigned, xy, 1)

    assert len(set(new[:n].tolist())) == 1  # blob A is one area
    assert len(set(new[n:].tolist())) == 1  # blob B is one area
    assert new[0] != new[n]  # the two disconnected blobs are now different areas
    assert parent[int(new[n])] == 0  # the split-off area inherits parent cluster 0
    for a in set(new.tolist()):
        assert _components(xy[new == a]) == 1  # every area is a single connected blob


def test_enforce_contiguity_merges_small_stray():
    rng = np.random.default_rng(1)
    body = rng.normal([0.0, 0.0], 40, (200, 2))  # area 0 body
    other = rng.normal([600.0, 0.0], 40, (200, 2))  # area 1, ~600 m away
    stray = np.array([[610.0, 5.0]])  # 1 parcel of area 0 sitting inside area 1
    xy = np.vstack([body, other, stray])
    assigned = np.array([0] * 200 + [1] * 200 + [0], dtype=np.int64)

    new, parent = _enforce_contiguity(assigned, xy, 2)

    assert len(parent) == 2  # a single stray does not mint a new area
    assert new[-1] == 1  # the stray merged into the nearer area (1), not left in 0
