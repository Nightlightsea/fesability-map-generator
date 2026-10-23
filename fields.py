"""Travel-time fields and render pieces.

Stage 2 of the pipeline: one Dijkstra per scene, calibrated against the OSRM
candidate matrix from the source project; the combined field is the solver
formula min_L = max_i(drive_i - window_i) + overhead evaluated on the graph.
Each scene's calibrated field is cached (cache/fields.npz) keyed by
(ll, window, waypoint) + network + speed table, so editing one scene only
recomputes that scene.

Stage 3 splits every kept road edge into <= max_piece_m pieces carrying the
per-map time values (NaN where an edge is not drawn on that map); cached in
cache/pieces.npz so re-rendering after label/point edits is instant.
"""
import hashlib
import json
import math
import os

import numpy as np

from . import geo, roads, settings


def scene_record(scene):
    return {"ll": list(scene.ll), "win": scene.win, "wp": scene.wp}


def _speed_sig():
    return hashlib.md5(json.dumps(settings.SPEED_MODERN, sort_keys=True)
                       .encode()).hexdigest()


def fields_signature(graph, data):
    payload = {
        "graph": graph.sig,
        "speed": _speed_sig(),
        "scenes": [scene_record(s) for s in data.scenes],
        "limit": data.constants["limit"],
        "overhead": data.constants["overhead"],
    }
    return hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def osrm_minutes(osrm, name, wp):
    """OSRM drive time in minutes for candidate `name` -> waypoint `wp`."""
    if not osrm or wp is None:
        return None
    wp_index, cand = osrm
    entry = cand.get(name)
    col = wp_index.get(wp)
    if entry is None or col is None:
        return None
    return float(entry["to_wp"][col]) / 60.0


def load_osrm(path, log):
    """(wp_index, candidates) from a 00_fetch_osrm.py cache, or None."""
    if not os.path.exists(path):
        log("  osrm cache not found at %s: fields computed uncalibrated" % path)
        return None
    try:
        with open(path, encoding="utf-8") as f:
            cache = json.load(f)
        wp_index = {n: i for i, n in enumerate(cache.get("waypoints", []))}
        return wp_index, cache.get("candidates", {})
    except Exception as exc:
        log("  osrm cache unreadable (%s): fields computed uncalibrated" % exc)
        return None


def calibrate(log, data, scene, times, graph, osrm, header=True):
    """Mean OSRM/graph ratio over the frontier towns; None if impossible."""
    ratios = []
    if header:
        log("  %s (window %.0f min -> drive limit %.0f min)  snapped %.0f m off"
            % (scene.name, scene.win, data.limits[scene.key],
               geo.nearest(graph.la, graph.lo, scene.ll)[1] * 1000))
    if osrm is None or scene.wp is None:
        log("    no OSRM data: leaving times uncalibrated (scale 1.0)")
        return None, ratios
    log("    %-16s %9s %10s %7s" % ("town", "OSRM_min", "graph_min", "ratio"))
    for town in data.frontier:
        nid, _ = geo.nearest(graph.la, graph.lo, town.ll)
        g = float(times[nid])
        osrm_min = osrm_minutes(osrm, town.name, scene.wp)
        if osrm_min is None:
            continue
        if math.isfinite(g) and g > 0.5:
            ratios.append(osrm_min / g)
            log("    %-16s %9.1f %10.1f %7.3f"
                % (town.name, osrm_min, g, osrm_min / g))
        else:
            log("    %-16s %9.1f %10s %7s  (unreachable!)"
                % (town.name, osrm_min, "--", "--"))
    return (sum(ratios) / len(ratios) if ratios else None), ratios


def compute_scene(log, data, graph, adj, scene, osrm):
    """Dijkstra from one scene + calibration -> (field float32, scale, snap_m)."""
    src, snap_m = geo.nearest(graph.la, graph.lo, scene.ll)
    times = roads.dijkstra(adj, src)
    scale, ratios = calibrate(log, data, scene, times, graph, osrm)
    if scale is None:
        log("    no usable calibration pairs: scale 1.0")
        scale = 1.0
    else:
        log("    calibration scale = %.3f  (mean OSRM/graph over the frontier)"
            % scale)
    field = (times * scale).astype(np.float32)
    n_reached = int(np.isfinite(field).sum())
    n_reach = int(np.sum(field <= data.limits[scene.key]))
    log("    nodes within this map's limit: %d of %d (%.0f%%)"
        % (n_reach, n_reached, 100.0 * n_reach / n_reached))
    return field, scale, snap_m


def combined_field(data, scene_fields):
    stack = np.vstack([scene_fields[s.key] for s in data.scenes])
    wins = np.array([s.win for s in data.scenes], dtype=np.float32)[:, None]
    comb = np.max(stack - wins, axis=0) + np.float32(data.constants["overhead"])
    return comb.astype(np.float32)


def _sensitivity(log, data, graph, osrm, modern_field, modern_scale):
    """First-scene rerun on the 1969 speed table; calibration absorbs most of it."""
    scene = data.scenes[0]
    log("  period-speed sensitivity (1969 table, %s only):" % scene.short)
    log("    SPEED69 = %s" % json.dumps(settings.SPEED_1969))
    adj69 = graph.adjacency(settings.SPEED_1969)
    src, _ = geo.nearest(graph.la, graph.lo, scene.ll)
    t69 = roads.dijkstra(adj69, src)
    scale69, ratios = calibrate(log, data, scene, t69, graph, osrm, header=False)
    if scale69 is None:
        lines = ["  period-speed sensitivity unavailable (no OSRM pairs)"]
        for line in lines:
            log(line)
        return lines, None
    deltas = []
    for town in data.frontier:
        nid, _ = geo.nearest(graph.la, graph.lo, town.ll)
        g69 = float(t69[nid])
        g_mod = float(modern_field[nid])
        if math.isfinite(g69) and math.isfinite(g_mod):
            deltas.append(g69 * scale69 - g_mod)
    max_delta = max(abs(d) for d in deltas) if deltas else float("nan")
    lines = [
        "    1969 calibration scale = %.3f (vs %.3f modern); "
        "town |delta| <= %.1f min" % (scale69, modern_scale, max_delta),
        "    -> the OSRM fit absorbs period-wide slowdowns; only class-mix",
        "       differences survive (max %.1f min over the frontier towns)"
        % max_delta,
    ]
    for line in lines:
        log(line)
    return lines, max_delta


class FieldsResult:
    def __init__(self, fields, scales, snap_m, sens_lines, sens_max_delta,
                 recomputed, sig):
        self.fields = fields
        self.scales = scales
        self.snap_m = snap_m
        self.sens_lines = sens_lines
        self.sens_max_delta = sens_max_delta
        self.recomputed = recomputed
        self.sig = sig


def load_or_compute(log, data, graph, osrm, cache_dir, recompute=False):
    """Per-scene calibrated fields with per-scene cache reuse."""
    os.makedirs(cache_dir, exist_ok=True)
    npz_path = os.path.join(cache_dir, "fields.npz")
    meta_path = os.path.join(cache_dir, "fields_meta.json")
    sig = fields_signature(graph, data)
    speed_sig = _speed_sig()

    prev_meta = {}
    prev_arrays = {}
    if not recompute and os.path.exists(npz_path) and os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                prev_meta = json.load(f)
            z = np.load(npz_path)
            prev_arrays = {k[2:]: z[k] for k in z.files}
        except Exception as exc:
            log("  fields cache unreadable (%s); recomputing" % exc)
            prev_meta, prev_arrays = {}, {}
    base_ok = (prev_meta.get("graph") == graph.sig
               and prev_meta.get("speed") == speed_sig)
    prev_arrays = prev_arrays if base_ok else {}

    log()
    log("2. SHORTEST-PATH TIMES FROM EACH SCENE + OSRM CALIBRATION")
    log("-" * 74)
    adj = graph.adjacency(settings.SPEED_MODERN)
    fields = {}
    scales = {}
    snap_m = {}
    recomputed = set()
    for scene in data.scenes:
        rec = scene_record(scene)
        cached_rec = (prev_meta.get("scenes") or {}).get(scene.key)
        if scene.key in prev_arrays and cached_rec == rec:
            fields[scene.key] = prev_arrays[scene.key]
            scales[scene.key] = prev_meta["scales"][scene.key]
            snap_m[scene.key] = prev_meta["snap_m"][scene.key]
            log("  %s: field reused from cache (scale %.3f, limit %.0f min); "
                "use --recompute to rebuild"
                % (scene.key, scales[scene.key], data.limits[scene.key]))
            continue
        log()
        field, scale, snap = compute_scene(log, data, graph, adj, scene, osrm)
        fields[scene.key] = field
        scales[scene.key] = scale
        snap_m[scene.key] = snap
        recomputed.add(scene.key)

    fields["comb"] = combined_field(data, fields)
    comb = fields["comb"]
    n_reached = int(np.isfinite(comb).sum())
    n_ok = int(np.sum(comb <= data.constants["limit"]))
    log()
    log("  combined field min_L = max_i[drive_i - window_i] + %.0f overhead"
        % data.constants["overhead"])
    log("  nodes satisfying all %d attacks at L=%d: %d of %d (%.0f%%)"
        % (len(data.scenes), int(data.constants["limit"]), n_ok, n_reached,
           100.0 * n_ok / max(1, n_reached)))

    if data.scenes[0].key in recomputed:
        sens_lines, sens_delta = _sensitivity(
            log, data, graph, osrm, fields[data.scenes[0].key],
            scales[data.scenes[0].key])
    else:
        sens_lines = prev_meta.get("sens_lines") or []
        sens_delta = prev_meta.get("sens_max_delta")
        if sens_lines:
            log("  period-speed sensitivity (cached):")
            for line in sens_lines:
                log(line)

    save = recomputed or not (os.path.exists(npz_path)
                              and os.path.exists(meta_path))
    if save:
        np.savez_compressed(
            npz_path, **{("t_%s" % k): fields[k]
                         for k in data.keys if k != "comb"})
        meta = {
            "graph": graph.sig,
            "speed": speed_sig,
            "sig": sig,
            "scenes": {s.key: scene_record(s) for s in data.scenes},
            "scales": {k: float(v) for k, v in scales.items()},
            "snap_m": {k: float(v) for k, v in snap_m.items()},
            "sens_lines": sens_lines,
            "sens_max_delta": sens_delta,
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1)
    return FieldsResult(fields, scales, snap_m, sens_lines, sens_delta,
                        recomputed, sig)


def pieces_signature(fields_sig, data):
    payload = {
        "fields": fields_sig,
        "caps": {k: float(v) for k, v in data.caps.items()},
        "max_piece_m": data.constants["max_piece_m"],
    }
    return hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def build_pieces(log, data, graph, fields):
    """Split kept edges into <= max_piece_m pieces with per-map time values."""
    keys = list(fields)
    caps = data.caps
    max_piece_m = data.constants["max_piece_m"]
    segs = []
    widths = []
    vals = {k: [] for k in keys}
    seen = set()
    n_kept = 0
    u_all, v_all = graph.u, graph.v
    for i in range(graph.n_edges):
        a, b = int(u_all[i]), int(v_all[i])
        if a == b:
            continue
        pair = (a, b) if a < b else (b, a)
        if pair in seen:
            continue
        seen.add(pair)
        keep = {}
        for k in keys:
            f = fields[k]
            tu = f[a]
            tv = f[b]
            if not (np.isfinite(tu) and np.isfinite(tv)):
                continue
            if min(tu, tv) > caps[k]:
                continue
            keep[k] = (float(tu), float(tv))
        if not keep:
            continue
        n_kept += 1
        fam = graph.class_names[graph.hw[i]].replace("_link", "")
        width = settings.LINE_WIDTH.get(fam, settings.LINE_WIDTH["residential"])
        d_m = float(graph.d_km[i]) * 1000.0
        n = max(1, int(math.ceil(d_m / max_piece_m)))
        la0, lo0 = graph.la[a], graph.lo[a]
        la1, lo1 = graph.la[b], graph.lo[b]
        x0, y0 = geo.mercator(la0, lo0)
        x1, y1 = geo.mercator(la1, lo1)
        for p in range(n):
            f0 = p / n
            f1 = (p + 1) / n
            segs.append(((x0 + (x1 - x0) * f0, y0 + (y1 - y0) * f0),
                         (x0 + (x1 - x0) * f1, y0 + (y1 - y0) * f1)))
            widths.append(width)
        for k in keys:
            if k in keep:
                tu, tv = keep[k]
                vals[k].extend(
                    tu + (tv - tu) * ((p / n + (p + 1) / n) / 2.0)
                    for p in range(n))
            else:
                vals[k].extend([np.nan] * n)
    segs = np.array(segs, dtype=np.float32).reshape(-1, 2, 2)
    widths = np.array(widths, dtype=np.float32)
    vals = np.array([vals[k] for k in keys], dtype=np.float32)
    return {"segs": segs, "widths": widths, "vals": vals}, n_kept


def load_or_build_pieces(log, data, graph, fields_result, cache_dir,
                         recompute=False):
    """Cached render pieces; rebuilt when fields, caps or code change."""
    npz_path = os.path.join(cache_dir, "pieces.npz")
    meta_path = os.path.join(cache_dir, "pieces_meta.json")
    sig = pieces_signature(fields_result.sig, data)
    log()
    log("3. ROAD PIECES (shared geometry, per-map time arrays)")
    log("-" * 74)
    if not recompute and os.path.exists(npz_path) and os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("sig") == sig:
                z = np.load(npz_path)
                pieces = {k: z[k] for k in z.files}
                for line in meta.get("lines", []):
                    log(line)
                log("  piece cache: reused %s (set --recompute to rebuild)"
                    % os.path.basename(npz_path))
                return pieces, meta
        except Exception as exc:
            log("  piece cache unreadable (%s); rebuilding" % exc)
    pieces, n_kept = build_pieces(log, data, graph, fields_result.fields)
    keys = list(fields_result.fields)
    lines = []
    for i, k in enumerate(keys):
        v = pieces["vals"][i]
        valid = ~np.isnan(v)
        limit = data.limit_of(k)
        lines.append("  %-9s %8d pieces drawn (%.2f M undirected edges kept), "
                     "%d beyond limit"
                     % (k, int(valid.sum()), n_kept / 1e6,
                        int((v[valid] > limit).sum())))
    comb_v = pieces["vals"][keys.index("comb")]
    finite = comb_v[np.isfinite(comb_v)]
    limit = data.constants["limit"]
    if finite.size:
        comb_vmin = max(20.0, math.floor((float(finite.min()) - 2.0) / 5.0) * 5.0)
        if comb_vmin >= limit - 10:
            comb_vmin = limit - 20
    else:
        comb_vmin = 0.0
    lines.append("  combined color scale starts at %.0f min (lowest min_L on "
                 "the map)" % comb_vmin)
    for line in lines:
        log(line)
    meta = {
        "sig": sig,
        "keys": keys,
        "comb_vmin": float(comb_vmin),
        "n_edges_kept": n_kept,
        "lines": lines,
    }
    os.makedirs(cache_dir, exist_ok=True)
    np.savez_compressed(npz_path, **pieces)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    return pieces, meta
