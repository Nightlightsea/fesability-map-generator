"""Per-figure simulation reports written next to the rendered PNGs.

Every rendered map gets a plain-text report describing exactly what was
simulated for that figure: what the field is, the scene geometry, the road
network, the OSRM calibration fit, coverage counts, per-place values, the
reading of the map and the standing caveats.  This module also hosts the
caveat text shared with the run log and the display-rounding helper used by
both.
"""
import hashlib
import math
import os
import time

import numpy as np

from . import fields as fields_mod
from . import geo


def showed_value(val, limit):
    """Match the renderer's display rounding (a hair over the limit)."""
    return math.ceil(val) if (val > limit and round(val) <= limit) else val


def caveat_lines(data, fields_result):
    """Shared caveat bullets (used by the run log and the figure reports).

    Each bullet may span several wrapped lines; consumers prefix the first
    line with '- ' and indent the continuations.
    """
    fr = fields_result
    limit = data.constants["limit"]
    bullets = [
        "modern OSM road geometry + free-flow speeds, calibrated to OSRM;\n"
        "not a 1969 network.",
    ]
    if fr.sens_max_delta is not None and math.isfinite(fr.sens_max_delta):
        bullets.append(
            "period-speed sensitivity: a 1969 speed table shifts frontier-town\n"
            "times by <=%.1f min after refitting -- the calibration absorbs\n"
            "period-wide slowdowns, only class-mix differences survive."
            % fr.sens_max_delta)
    else:
        bullets.append(
            "period-speed sensitivity not computed in this run (rerun with\n"
            "--recompute to calculate it).")
    bullets += [
        "no open street-level 1969 network exists for the US (digital street\n"
        "files begin with TIGER in the mid-1980s); historical checking means\n"
        "USGS TopoView quad scans + Caltrans archives.",
        "graph times are snapped to nearest OSM node (~tens of m); per-scene\n"
        "drive limits %s = L + window - overhead."
        % "/".join("%.0f" % data.limits[s.key] for s in data.scenes),
        "map extent is the wider Bay Area bbox %s; roads beyond the\n"
        "%.0f min render cap are not drawn (pure void)."
        % (data.constants["bbox"], limit * data.constants["offscreen_factor"]),
    ]
    return bullets


def _md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _num(v, fmt="%.0f"):
    if v is None:
        return "--"
    v = float(v)
    return fmt % v if math.isfinite(v) else "unreachable"


def write_map_report(log, data, graph, fres, pieces, pieces_meta, places,
                     bind_counts, osrm, key, png_name, figures_dir, data_path,
                     test_path=None, chains_rows=None):
    """Write <png base>_report.txt for one map; returns the file path."""
    is_comb = key == "comb"
    limit = data.limit_of(key)
    base = png_name[:-4] if png_name.lower().endswith(".png") else png_name
    path = os.path.join(figures_dir, base + "_report.txt")

    out = []

    def w(s=""):
        out.append(s)

    def sec(title):
        w()
        w(title)
        w("-" * 78)

    w("=" * 78)
    w("%s -- SIMULATION REPORT" % base.upper())
    if is_comb:
        w("Combined residence-feasibility field (all four canonical attacks)")
    else:
        sc = data.scene_by_key[key]
        w("Residence-feasibility field: calibrated drive time to %s (%s)"
          % (sc.name, sc.short))
    w("=" * 78)
    w("figure    : %s (+ _clean variant, identical computation)" % png_name)
    w("generated : %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    w("input     : %s (md5 %s)" % (data_path, _md5_file(data_path)))
    if test_path:
        w("test      : %s (md5 %s)" % (test_path, _md5_file(test_path)))
    w("caches    : graph %s / fields %s / pieces %s"
      % (graph.sig[:12], fres.sig[:12], pieces_meta["sig"][:12]))

    sec("1. WHAT WAS SIMULATED")
    if is_comb:
        w("  field      : combined constraint field")
        w("               min_L = max_i(drive_i - window_i) + %.0f min overhead"
          % data.constants["overhead"])
        w("  meaning    : minimum pre-attack loiter time L this location would")
        w("               need to reach all four attacks on time (feasible")
        w("               when min_L <= %.0f min)" % limit)
        for sc in data.scenes:
            w("  scene      : %-9s window %.0f min -> drive limit %.0f min"
              % (sc.short, sc.win, data.limits[sc.key]))
        w("  color ramp : green (low L) -> red at %.0f min; black beyond"
          % limit)
        w("  color scale starts at %.0f min (lowest min_L drawn)"
          % pieces_meta["comb_vmin"])
    else:
        sc = data.scene_by_key[key]
        w("  field      : calibrated drive time to %s (%s)"
          % (sc.name, sc.short))
        w("  scene site : %.5f, %.5f  (snapped %.0f m to nearest road node)"
          % (sc.ll[0], sc.ll[1], fres.snap_m.get(key, 0.0) * 1000.0))
        w("  drive limit: L %.0f + window %.0f - overhead %.0f = %.0f min;"
          % (data.constants["limit"], sc.win, data.constants["overhead"],
             limit))
        w("               black beyond = infeasible")

    sec("2. ROAD NETWORK")
    for line in graph.stats_lines:
        w("  " + line.strip())
    w("  tiles      : %d cached Overpass tiles in %s"
      % (data.constants["tiles"] ** 2, data.paths["tiles_dir"]))

    sec("3. TRAVEL TIMES + CALIBRATION")
    if is_comb:
        w("  per-scene calibrated fields feed the formula; scales fitted as")
        w("  mean(OSRM / graph) over the 10 frontier towns:")
        for sc in data.scenes:
            w("    %-9s scale %s  (snapped %.0f m)"
              % (sc.short, _num(fres.scales.get(sc.key), "%.3f"),
                 fres.snap_m.get(sc.key, 0.0) * 1000.0))
        w("  OSRM cross-check, calibrated graph vs OSRM (min):")
        worst = 0.0
        for name, ll in data.cross_check:
            nid, _ = geo.nearest(graph.la, graph.lo, ll)
            row = "    %-20s" % name
            for sc in data.scenes:
                g = float(fres.fields[sc.key][nid])
                om = fields_mod.osrm_minutes(osrm, name, sc.wp)
                row += " %s %5s/%5s" % (
                    sc.short,
                    "--" if om is None else "%.1f" % om,
                    "--" if not math.isfinite(g) else "%.1f" % g)
                if om is not None and math.isfinite(g):
                    worst = max(worst, abs(g - om))
            w(row)
        w("    max |OSRM - graph| = %.1f min" % worst)
    else:
        sc = data.scene_by_key[key]
        scale = fres.scales.get(key)
        w("  method     : one-to-all Dijkstra from the snapped scene node over")
        w("               the directed graph (free-flow class speeds, one-way")
        w("               streets respected)")
        w("  calibration: one global scale = mean(OSRM / graph minimum) over")
        w("               the 10 frontier towns = %s" % _num(scale, "%.3f"))
        w("  frontier-town fit (graph times before scaling):")
        w("    %-16s %9s %9s %7s" % ("town", "OSRM_min", "graph_min", "ratio"))
        for town in data.frontier:
            nid, _ = geo.nearest(graph.la, graph.lo, town.ll)
            cal = float(fres.fields[key][nid])
            om = fields_mod.osrm_minutes(osrm, town.name, sc.wp)
            if not math.isfinite(cal):
                w("    %-16s %9s %9s %7s"
                  % (town.name, _num(om, "%.1f"), "--", "--"))
                continue
            unc = cal / scale if scale else float("nan")
            if om is not None and unc > 0.5:
                w("    %-16s %9.1f %9.1f %7.3f"
                  % (town.name, om, unc, om / unc))
            else:
                w("    %-16s %9s %9.1f %7s"
                  % (town.name, _num(om, "%.1f"), unc, "--"))
        w("  OSRM cross-check at named places, calibrated graph (min):")
        worst = 0.0
        for name, ll in data.cross_check:
            nid, _ = geo.nearest(graph.la, graph.lo, ll)
            g = float(fres.fields[key][nid])
            om = fields_mod.osrm_minutes(osrm, name, sc.wp)
            w("    %-20s OSRM %6s / graph %6s" % (
                name,
                "--" if om is None else "%.1f" % om,
                "--" if not math.isfinite(g) else "%.1f" % g))
            if om is not None and math.isfinite(g):
                worst = max(worst, abs(g - om))
        w("    max |OSRM - graph| = %.1f min (this scene)" % worst)

    sec("4. COVERAGE")
    field = fres.fields[key]
    n_reached = int(np.isfinite(field).sum())
    n_in = int(np.sum(field <= limit))
    ki = pieces_meta["keys"].index(key)
    v = pieces["vals"][ki]
    valid = ~np.isnan(v)
    n_drawn = int(valid.sum())
    n_black = int((v[valid] > limit).sum())
    if is_comb:
        w("  nodes satisfying all four attacks (min_L <= %.0f): %d of %d (%.0f%%)"
          % (limit, n_in, n_reached, 100.0 * n_in / max(1, n_reached)))
    else:
        w("  nodes reachable from the scene: %d" % n_reached)
        w("  nodes within %.0f min: %d (%.0f%% of reachable)"
          % (limit, n_in, 100.0 * n_in / max(1, n_reached)))
    w("  drawn road pieces: %d ; beyond limit (black): %d"
      % (n_drawn, n_black))
    w("  render cap: %.0f min (roads beyond are not drawn)"
      % data.caps[key])

    sec("5. PLACE VALUES")
    if is_comb:
        w("  value = minimum pre-attack loiter L required at the displayed")
        w("  marker (min); * = feasible (<= %.0f)" % limit)
    else:
        w("  value = calibrated drive time at the displayed marker (min);")
        w("  * = within the %.0f min limit" % limit)
    for label, towns in (("frontier towns", data.frontier),
                         ("reference cities", data.reference)):
        w("  %s:" % label)
        for town in towns:
            val = places[town.name].get(key)
            if val is None:
                w("    %-18s --" % town.name)
            else:
                star = " *" if val <= limit else ""
                w("    %-18s %3.0f%s" % (town.name,
                                         showed_value(val, limit), star))
    w()
    n_within = sum(1 for t in data.frontier
                   if places[t.name].get(key) is not None
                   and places[t.name][key] <= limit)
    w("  reading: %d/%d frontier towns within the %.0f min limit"
      % (n_within, len(data.frontier), limit))
    if is_comb:
        parts = ", ".join("%s %d" % (short, n)
                          for short, n in sorted(bind_counts.items(),
                                                 key=lambda x: -x[1]))
        if parts:
            w("  binding scene over the frontier: %s" % parts)
        beyond = [t.name for t in data.reference
                  if places[t.name].get(key) is not None
                  and places[t.name][key] > limit]
        if beyond:
            w("  reference cities beyond the limit: %s"
              % ", ".join("%s %.0f" % (n, places[n][key]) for n in beyond))

    if chains_rows:
        sec("6. TIMELINE CHAINS (scenario)")
        w("  drive = physical travel between the two named waypoints (OSRM")
        w("  waypoint matrix; town-name endpoints use the calibrated graph")
        w("  place value). gap = time available between the two events.")
        w("  PASS when drive <= gap. Verification-only; not a field constraint.")
        for row in chains_rows:
            w(row)

    sec("7. CAVEATS")
    for bullet in caveat_lines(data, fres):
        for i, line in enumerate(bullet.split("\n")):
            w(("  - " if i == 0 else "    ") + line)

    if key == data.scenes[0].key and fres.sens_lines:
        sec("8. PERIOD-SPEED SENSITIVITY (this scene)")
        for line in fres.sens_lines:
            w("  " + line.strip())

    w()
    w("=" * 78)
    w("end of report")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    log("  report: %s" % path)
    return path
