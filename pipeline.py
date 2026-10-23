"""Pipeline: data -> graph -> fields -> pieces -> places -> render -> report.

Run `python -m feasibility_map` from the project root.  Each stage caches to
feasibility_map/cache/ and only recomputes what changed:

  graph   rebuilt when a tile file's size/mtime changes
  fields  per scene, keyed by (ll, window, waypoint) + network + speed table
  pieces  rebuilt when fields, caps or max_piece_m change
"""
import copy
import glob
import math
import os

from . import basemap as basemap_mod
from . import datamodel, fields, geo, render, reports, roads, settings, timeline


class Report:
    """Console + report file logger (callable)."""

    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self.fh = open(path, "w", encoding="utf-8")

    def __call__(self, s=""):
        print(s)
        self.fh.write(s + "\n")
        self.fh.flush()

    def close(self):
        self.fh.close()


def compute_places(data, graph, fields_dict):
    """Displayed-marker node -> per-map time values + binding scene."""
    places = {}
    for town in data.frontier + data.reference:
        ll = town.marker_ll if town.marker_ll else town.ll
        nid, _ = geo.nearest(graph.la, graph.lo, ll)
        pv = {}
        for k in data.keys:
            v = float(fields_dict[k][nid])
            pv[k] = None if not math.isfinite(v) else v
        if all(pv[k] is not None for k in data.keys[:-1]):
            parts = {k: pv[k] - data.scene_by_key[k].win
                     for k in data.keys[:-1]}
            pv["bind"] = max(parts, key=parts.get)
        places[town.name] = pv
    return places


def log_cross_check(log, data, graph, fields_dict, osrm):
    log()
    log("  named-place cross-check (OSRM vs calibrated graph, min):")
    worst = 0.0
    for name, ll in data.cross_check:
        nid, _ = geo.nearest(graph.la, graph.lo, ll)
        row = ["    %-20s" % name]
        for sc in data.scenes:
            g = float(fields_dict[sc.key][nid])
            g = None if not math.isfinite(g) else g
            om = fields.osrm_minutes(osrm, name, sc.wp)
            if om is None:
                txt = "%.1f" % g if g is not None else "--"
                row.append(" %s %5s/%5s" % (sc.short, "n/a", txt))
            else:
                txt = "%.1f" % g if g is not None else "  --"
                row.append(" %s %5.1f/%5s" % (sc.short, om, txt))
                if g is not None:
                    worst = max(worst, abs(g - om))
        log("".join(row))
    log("      max |OSRM - graph| = %.1f min" % worst)


def log_place_values(log, data, places):
    log()
    log("  place values (graph time at the displayed marker):")
    for town in data.frontier + data.reference:
        pv = places[town.name]
        shown = {}
        for k in data.keys:
            v = pv.get(k)
            if v is None:
                continue
            shown[k] = reports.showed_value(v, data.limit_of(k))
        log("    %-18s %s" % (town.name,
                              " ".join("%s=%.0f" % (k, shown[k])
                                       for k in data.keys if k in shown)))


def log_reading(log, data, places):
    log()
    log("READING")
    log("-" * 74)
    frontier = data.frontier
    for sc in data.scenes:
        limit = data.limits[sc.key]
        n_in = sum(1 for t in frontier
                   if places[t.name].get(sc.key) is not None
                   and places[t.name][sc.key] <= limit)
        log("  %-9s %d/%d frontier towns within its %.0f min limit"
            % (sc.key, n_in, len(frontier), limit))
    limit = data.constants["limit"]
    n_in = sum(1 for t in frontier
               if places[t.name].get("comb") is not None
               and places[t.name]["comb"] <= limit)
    log("  %-9s %d/%d frontier towns within L=%.0f"
        % ("comb", n_in, len(frontier), limit))
    bind_count = {}
    for t in frontier:
        b = places[t.name].get("bind")
        if b:
            bind_count[data.scene_by_key[b].short] = \
                bind_count.get(data.scene_by_key[b].short, 0) + 1
    if bind_count:
        log("  Binding scene over the frontier: %s"
            % ", ".join("%s %d" % (k, v)
                        for k, v in sorted(bind_count.items(),
                                           key=lambda x: -x[1])))
    beyond = [t.name for t in data.reference
              if places[t.name].get("comb") is not None
              and places[t.name]["comb"] > limit]
    if beyond:
        vals = ", ".join("%s %.0f" % (t.name, places[t.name]["comb"])
                         for t in data.reference if t.name in beyond)
        log("  Reference cities beyond L on the combined map: %s" % vals)
    return bind_count


def log_caveats(log, data, fields_result):
    log()
    log("CAVEATS")
    log("-" * 74)
    for bullet in reports.caveat_lines(data, fields_result):
        for i, line in enumerate(bullet.split("\n")):
            log(("  - " if i == 0 else "    ") + line)


def run(args):
    data = datamodel.load(args.data,
                          override=getattr(args, "test_override", None))
    outdir = getattr(args, "outdir", None)
    if outdir:
        if not os.path.isabs(outdir):
            outdir = os.path.join(os.path.dirname(os.path.abspath(args.data)),
                                  outdir)
        outdir = os.path.abspath(outdir)
        data.paths["figures_dir"] = outdir
        data.paths["report"] = os.path.join(outdir, "report.txt")
    report = Report(data.paths["report"])
    log = report
    only = {k.strip() for k in (args.only or "").split(",") if k.strip()}
    if only:
        bad = only - set(data.keys)
        if bad:
            raise SystemExit("unknown map key(s): %s (known: %s)"
                             % (sorted(bad), data.keys))
    written = []
    try:
        log("=" * 74)
        log("RESIDENCE-FEASIBILITY FIELD MAPS (standalone program)")
        dataline = os.path.abspath(args.data)
        if getattr(args, "test_override", None):
            dataline += "  + test %s" % os.path.abspath(args.test_override)
        log("data     : %s" % dataline)
        log("figures  : %s" % data.paths["figures_dir"])
        limit = data.constants["limit"]
        log("limit L = %.0f min  |  windows %s  |  overhead %g min  |  bbox %s"
            % (limit,
               "/".join("%s %g" % (s.short, s.win) for s in data.scenes),
               data.constants["overhead"], data.constants["bbox"]))
        log("scenes %d  |  frontier towns %d  |  reference towns %d  |  "
            "suspects %d"
            % (len(data.scenes), len(data.frontier), len(data.reference),
               len(data.suspects)))
        log("=" * 74)
        log()

        osrm = fields.load_osrm(data.paths["osrm_cache"], log)
        graph = roads.load_or_build_graph(log, data, settings.CACHE_DIR,
                                          rebuild=args.rebuild_graph)
        fields_result = fields.load_or_compute(log, data, graph, osrm,
                                               settings.CACHE_DIR,
                                               recompute=args.recompute)
        log_cross_check(log, data, graph, fields_result.fields, osrm)
        pieces, pieces_meta = fields.load_or_build_pieces(
            log, data, graph, fields_result, settings.CACHE_DIR,
            recompute=args.recompute)

        places = compute_places(data, graph, fields_result.fields)
        log_place_values(log, data, places)
        bind_counts = log_reading(log, data, places)
        chain_rows = timeline.chain_rows(
            data, timeline.load_wp_matrix(data.paths["osrm_cache"]), places)
        if chain_rows:
            log()
            log("  timeline chains (drive vs available gap, PASS = drive <= gap):")
            for row in chain_rows:
                log(row)
        log_caveats(log, data, fields_result)

        meta = {
            "keys": pieces_meta["keys"],
            "comb_vmin": pieces_meta["comb_vmin"],
            "scales": fields_result.scales,
            "snap_m": fields_result.snap_m,
            "places": places,
            "bind_counts": bind_counts,
            "chains": chain_rows,
        }

        log()
        log("4. RENDER")
        log("-" * 74)
        base = basemap_mod.get_basemap(log, data, settings.CACHE_DIR,
                                       enabled=not args.no_basemap)
        os.makedirs(data.paths["figures_dir"], exist_ok=True)
        failed = []
        report_paths = []
        for key, png in data.maps:
            if only and key not in only:
                continue
            rendered_any = False
            for name, clean in ((png, False),
                                (png.replace(".png", "_clean.png"), True)):
                try:
                    written.append(render.render_map(
                        log, data, meta, pieces, key, name, base,
                        data.paths["figures_dir"], clean=clean))
                    rendered_any = True
                except Exception as exc:
                    failed.append((name, exc))
                    log("  FAILED %s: %s" % (name, exc))
            if rendered_any:
                try:
                    report_paths.append(reports.write_map_report(
                        log, data, graph, fields_result, pieces, pieces_meta,
                        places, bind_counts, osrm, key, png,
                        data.paths["figures_dir"], args.data,
                        getattr(args, "test_override", None),
                        chains_rows=meta.get("chains")))
                except Exception as exc:
                    failed.append((png + " report", exc))
                    log("  FAILED report for %s: %s" % (key, exc))
        log()
        if failed:
            log("done: %d PNGs, %d figure reports written, %d FAILED"
                % (len(written), len(report_paths), len(failed)))
            for name, exc in failed:
                log("  - %s: %s" % (name, exc))
        else:
            log("done: %d PNGs, %d figure reports written"
                % (len(written), len(report_paths)))
        print()
        print("report : %s" % report.path)
        for p in written:
            print("figure : %s" % p)
        for p in report_paths:
            print("figreport: %s" % p)
        if failed:
            return 1
    finally:
        report.close()
    return 0


def run_tests(args):
    """Batch runner: every FOLDER/*.json is a partial override of the base
    points file (--data); each test gets its own output folder.
    """
    folder = os.path.abspath(args.run_tests)
    if not os.path.isdir(folder):
        raise SystemExit("--run-tests: not a folder: %s" % folder)
    if not os.path.isfile(args.data):
        raise SystemExit("--run-tests: base points file not found: %s"
                         % args.data)
    tests = sorted(glob.glob(os.path.join(folder, "*.json")))
    if not tests:
        raise SystemExit("--run-tests: no *.json test files in %s" % folder)
    base_out = None
    if getattr(args, "outdir", None):
        base_out = args.outdir
        if not os.path.isabs(base_out):
            base_out = os.path.join(
                os.path.dirname(os.path.abspath(args.data)), base_out)
        base_out = os.path.abspath(base_out)
    results = []
    for test in tests:
        name = os.path.splitext(os.path.basename(test))[0]
        sub = copy.copy(args)
        sub.test_override = test
        sub.outdir = os.path.join(base_out if base_out else folder, name)
        print("=" * 74)
        print("TEST %s  (%s)" % (name, test))
        try:
            code = run(sub)
            info = os.path.join(sub.outdir, "report.txt")
        except (ValueError, datamodel.DataError, OSError) as exc:
            code = 1
            info = "%s: %s" % (type(exc).__name__, exc)
            print("test %s FAILED: %s" % (name, info))
        results.append((name, code, info))
    failed = [r for r in results if r[1]]
    print()
    print("=" * 74)
    print("tests: %d run, %d ok, %d failed"
          % (len(results), len(results) - len(failed), len(failed)))
    for name, code, info in results:
        print("  %-28s %s" % (name, "ok" if code == 0 else "FAILED"))
    return 1 if failed else 0
