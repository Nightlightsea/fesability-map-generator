"""Timeline chains: physical checks between timed waypoints of the case.

Each chain verifies that the killer could move from one timed point to the
next within the available gap (attack -> phone call, murder -> letter
postmark, faire venue -> attack).  Endpoints resolve by name, in order:

  1. scene key        -> the scene's OSRM waypoint
  2. event key        -> the event's `waypoint`
  3. OSRM waypoint    -> itself (wp_matrix in the cached osrm_cache.json)
  4. town name (from) -> scene key (to): the calibrated graph place value
     (drive from the town's displayed marker to the scene) already computed
     for the maps.

Anything else prints n/a with the reason.  Chains are verification-only:
they do not constrain the feasibility fields.
"""
import json
import math
import os


def load_wp_matrix(path):
    """(waypoint_index, matrix) from the OSRM cache, or None."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            cache = json.load(f)
        wps = cache.get("waypoints") or []
        matrix = cache.get("wp_matrix") or []
        if len(matrix) != len(wps) or not wps:
            return None
        return {n: i for i, n in enumerate(wps)}, matrix
    except Exception:
        return None


def _waypoint(data, name, wp_index):
    if name in data.scene_by_key:
        wp = data.scene_by_key[name].wp
        return wp if wp in wp_index else None
    ev = data.event_by_key.get(name)
    if ev is not None:
        wp = ev.get("waypoint")
        return wp if wp in wp_index else None
    return name if name in wp_index else None


def chain_rows(data, wp_data, places):
    """One formatted row per chain: drive vs gap, PASS/FAIL or n/a."""
    rows = []
    for ch in data.chains:
        f, t = ch["from"], ch["to"]
        gap = ch["gap_min"]
        note = "  " + ch["note"] if ch["note"] else ""
        drive, src = None, None
        if wp_data is not None:
            wp_index, wp_matrix = wp_data
            fw = _waypoint(data, f, wp_index)
            tw = _waypoint(data, t, wp_index)
            if fw is not None and tw is not None:
                drive = float(wp_matrix[wp_index[fw]][wp_index[tw]]) / 60.0
                src = "wp_matrix"
        if drive is None:
            if (t in data.scene_by_key and f in data.town_by_name
                    and places.get(f, {}).get(t) is not None):
                drive = float(places[f][t])
                src = "graph"
        if drive is None or not math.isfinite(drive):
            rows.append("    %-24s -> %-18s drive     --  gap %5.0f  n/a%s"
                        % (f, t, gap, note))
            continue
        slack = gap - drive
        rows.append("    %-24s -> %-18s drive %6.1f  gap %5.0f  slack %+7.1f  %s  [%s]%s"
                    % (f, t, drive, gap, slack,
                       "PASS" if slack >= 0 else "FAIL", src, note))
    return rows
