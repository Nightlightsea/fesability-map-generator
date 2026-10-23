"""Small geometry helpers: haversine, Web Mercator, node snapping."""
import math

import numpy as np

EARTH_R_KM = 6371.0


def hav(a, b):
    """Great-circle distance in km between (lat, lon) pairs."""
    la1, lo1 = a
    la2, lo2 = b
    x = math.radians(lo2 - lo1) * math.cos(math.radians((la1 + la2) / 2.0))
    y = math.radians(la2 - la1)
    return EARTH_R_KM * math.hypot(x, y)


def mercator(lat, lon):
    """(lat, lon) -> Web Mercator metres, matching contextily basemaps."""
    x = lon * 20037508.34 / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    return x, y * 20037508.34 / 180.0


def bbox_extent(bbox, pad=0.02):
    """Mercator extent [west, east, south, north] of a (S, W, N, E) bbox."""
    s0, w0, n1, e1 = bbox
    xs, ys = [], []
    for la, lo in [(s0, w0), (s0, e1), (n1, w0), (n1, e1)]:
        x, y = mercator(la, lo)
        xs.append(x)
        ys.append(y)
    return min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad


def nearest(la, lo, latlon):
    """Index of the node closest to latlon; returns (index, distance_m)."""
    t_lat, t_lon = latlon
    x = np.radians(lo - t_lon) * math.cos(math.radians(t_lat))
    y = np.radians(la - t_lat)
    d = np.hypot(x, y)
    j = int(np.argmin(d))
    return j, EARTH_R_KM * float(d[j])
