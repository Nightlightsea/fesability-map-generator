"""Road network: Overpass tiles -> directed index graph -> cached Dijkstra.

The network is fetched once as a grid of Overpass JSON tiles (cached as plain
files), assembled into an index-based directed graph (u/v/distance/class), and
saved to cache/graph.npz.  The graph is rebuilt only when a tile file changes.
Adjacency (times by road class) is built in memory per speed table; Dijkstra
runs straight off flat arrays.
"""
import hashlib
import json
import os
import time
from heapq import heappop, heappush

import numpy as np
import requests

from . import geo, settings


class Graph:
    def __init__(self, la, lo, u, v, d_km, hw, class_names, stats_lines, sig):
        self.la = la
        self.lo = lo
        self.u = u
        self.v = v
        self.d_km = d_km
        self.hw = hw
        self.class_names = class_names
        self.stats_lines = stats_lines
        self.sig = sig

    @property
    def n_nodes(self):
        return len(self.la)

    @property
    def n_edges(self):
        return len(self.u)

    def adjacency(self, speed_table):
        return Adjacency(self, speed_table)


class Adjacency:
    """CSR-style weighted adjacency; times in minutes for one speed table."""

    def __init__(self, graph, speed_table):
        speeds = np.array([speed_table[n] for n in graph.class_names])
        w = graph.d_km / speeds[graph.hw] * 60.0
        order = np.argsort(graph.u, kind="stable")
        counts = np.bincount(graph.u, minlength=graph.n_nodes)
        self.n = graph.n_nodes
        self.starts = np.concatenate(([0], np.cumsum(counts))).tolist()
        self.heads = graph.v[order].tolist()
        self.weights = w[order].tolist()


def dijkstra(adj, src):
    """Shortest travel times (minutes) from node index `src`; inf = unreached."""
    t = np.full(adj.n, np.inf)
    t[src] = 0.0
    starts, heads, weights = adj.starts, adj.heads, adj.weights
    pq = [(0.0, src)]
    while pq:
        tu, u = heappop(pq)
        if tu > t[u]:
            continue
        for i in range(starts[u], starts[u + 1]):
            v = heads[i]
            nv = tu + weights[i]
            if nv < t[v]:
                t[v] = nv
                heappush(pq, (nv, v))
    return t


def tile_bounds(bbox, tiles):
    s0, w0, n1, e1 = bbox
    dlat = (n1 - s0) / tiles
    dlon = (e1 - w0) / tiles
    for i in range(tiles):
        for j in range(tiles):
            yield (s0 + i * dlat, w0 + j * dlon,
                   s0 + (i + 1) * dlat, w0 + (j + 1) * dlon)


def tiles_signature(tiles_dir, n_tiles):
    """Hash of tile sizes/mtimes by index: changes when the network does.

    Deliberately path-independent so the whole package folder can be moved
    or copied without invalidating the graph/fields/pieces caches.
    """
    parts = []
    for idx in range(n_tiles):
        path = os.path.join(tiles_dir, "tile_%02d.json" % idx)
        if os.path.exists(path):
            st = os.stat(path)
            parts.append("%02d:%d:%.1f" % (idx, st.st_size, st.st_mtime))
        else:
            parts.append("%02d:missing" % idx)
    parts.append(settings.ROAD_CLASS_REGEX)
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def fetch_tile(log, tiles_dir, idx, bounds):
    os.makedirs(tiles_dir, exist_ok=True)
    path = os.path.join(tiles_dir, "tile_%02d.json" % idx)
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        log("  tile %02d: cached (%.1f MB)" % (idx, os.path.getsize(path) / 1e6))
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    s, w, n, e = bounds
    query = ('[out:json][timeout:180];'
             'way["highway"~"%s"](%.4f,%.4f,%.4f,%.4f);out geom;'
             % (settings.ROAD_CLASS_REGEX, s, w, n, e))
    for attempt in range(10):
        host = settings.OVERPASS_HOSTS[attempt % len(settings.OVERPASS_HOSTS)]
        try:
            r = requests.post(host, data={"data": query},
                              headers=settings.HTTP_HEADERS, timeout=180)
            if r.ok:
                data = r.json()
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                log("  tile %02d: fetched %d ways from %s (%.1f MB)"
                    % (idx, len(data.get("elements", [])),
                       host.split("//")[1].split("/")[0],
                       os.path.getsize(path) / 1e6))
                return data
            log("  tile %02d: HTTP %d from %s (attempt %d)"
                % (idx, r.status_code, host, attempt))
        except Exception as exc:
            log("  tile %02d: %s %s (attempt %d)"
                % (idx, type(exc).__name__, exc, attempt))
        time.sleep(8 * (attempt + 1))
    raise RuntimeError("tile %d failed on all hosts" % idx)


def build_graph(log, elements):
    """Assemble Overpass ways into an index-based directed graph."""
    class_names = tuple(settings.SPEED_MODERN.keys())
    class_code = {name: i for i, name in enumerate(class_names)}
    node_index = {}
    la_list, lo_list = [], []
    edge_map = {}
    seen_ways = set()
    cls_count = {}
    n_ways = n_dup = n_skip = 0
    for el in elements:
        if el.get("type") != "way":
            continue
        wid = el.get("id")
        if wid in seen_ways:
            n_dup += 1
            continue
        seen_ways.add(wid)
        tags = el.get("tags") or {}
        hw = tags.get("highway")
        if hw not in class_code:
            n_skip += 1
            continue
        ids = el.get("nodes") or []
        geom = el.get("geometry") or []
        if len(ids) < 2 or len(ids) != len(geom):
            n_skip += 1
            continue
        n_ways += 1
        cls_count[hw] = cls_count.get(hw, 0) + 1
        oneway = tags.get("oneway", "")
        bidir = oneway not in ("yes", "1", "true", "-1")
        idxs = []
        for i, nid in enumerate(ids):
            j = node_index.get(nid)
            if j is None:
                j = len(la_list)
                node_index[nid] = j
                la_list.append(geom[i]["lat"])
                lo_list.append(geom[i]["lon"])
            idxs.append(j)
        code = class_code[hw]
        for i in range(len(idxs) - 1):
            a, b = idxs[i], idxs[i + 1]
            d = geo.hav((la_list[a], lo_list[a]), (la_list[b], lo_list[b]))
            if d < 1e-6:
                continue
            if bidir or oneway != "-1":
                e = (a, b)
                if e not in edge_map or edge_map[e][0] > d:
                    edge_map[e] = (d, code)
            if bidir or oneway == "-1":
                e = (b, a)
                if e not in edge_map or edge_map[e][0] > d:
                    edge_map[e] = (d, code)
    keys = list(edge_map.keys())
    u = np.fromiter((k[0] for k in keys), dtype=np.int32, count=len(keys))
    v = np.fromiter((k[1] for k in keys), dtype=np.int32, count=len(keys))
    d_km = np.fromiter((edge_map[k][0] for k in keys), dtype=np.float32,
                       count=len(keys))
    hw = np.fromiter((edge_map[k][1] for k in keys), dtype=np.uint8,
                     count=len(keys))
    la = np.array(la_list, dtype=np.float64)
    lo = np.array(lo_list, dtype=np.float64)
    stats_lines = [
        "  graph: %d ways (%d dup-skipped, %d non-drivable), "
        "%d nodes, %d directed edges"
        % (n_ways, n_dup, n_skip, len(la), len(keys)),
        "  ways by class: %s"
        % ", ".join("%s=%d" % (k, cls_count[k]) for k in settings.HW_FAMILY
                    if k in cls_count),
    ]
    for line in stats_lines:
        log(line)
    return Graph(la, lo, u, v, d_km, hw, class_names, stats_lines, "")


def _graph_cache_paths(cache_dir):
    return (os.path.join(cache_dir, "graph.npz"),
            os.path.join(cache_dir, "graph_meta.json"))


def load_or_build_graph(log, data, cache_dir, rebuild=False):
    """Cached graph; rebuilt automatically when a tile file changes."""
    npz_path, meta_path = _graph_cache_paths(cache_dir)
    n_tiles = data.constants["tiles"] ** 2
    sig = tiles_signature(data.paths["tiles_dir"], n_tiles)
    if not rebuild and os.path.exists(npz_path) and os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("sig") == sig:
                z = np.load(npz_path)
                graph = Graph(z["la"], z["lo"], z["u"], z["v"], z["d"],
                              z["hw"], tuple(z["class_names"].tolist()),
                              meta.get("stats_lines", []), sig)
                log("  graph cache: reused %s (%d nodes, %d edges)"
                    % (os.path.basename(npz_path), graph.n_nodes, graph.n_edges))
                for line in graph.stats_lines:
                    log(line)
                return graph
        except Exception as exc:
            log("  graph cache unreadable (%s); rebuilding" % exc)
    log("1. ROAD NETWORK (Overpass API, %dx%d tiles, cached in %s)"
        % (data.constants["tiles"], data.constants["tiles"],
           data.paths["tiles_dir"]))
    log("-" * 74)
    elements = []
    for idx, bounds in enumerate(tile_bounds(data.constants["bbox"],
                                             data.constants["tiles"])):
        tile = fetch_tile(log, data.paths["tiles_dir"], idx, bounds)
        elements.extend(tile.get("elements", []))
    graph = build_graph(log, elements)
    graph.sig = sig
    os.makedirs(cache_dir, exist_ok=True)
    np.savez_compressed(npz_path, la=graph.la, lo=graph.lo, u=graph.u,
                        v=graph.v, d=graph.d_km, hw=graph.hw,
                        class_names=np.array(graph.class_names))
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"sig": sig, "stats_lines": graph.stats_lines}, f, indent=1)
    return graph
