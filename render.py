"""Draw one feasibility map: road field + labelled markers, or the clean
variant with a right-hand key panel.

All colors, labels, offsets, IDs and values come from points.json (via the
`Data` object) and the computed meta; this module only decides layout.
"""
import math
import os
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import (BoundaryNorm, LinearSegmentedColormap,
                                ListedColormap)
from matplotlib.lines import Line2D

from . import geo, labels


def feasible_cmap(data):
    return LinearSegmentedColormap.from_list(
        "feas", [(t, c) for t, c in data.colors["feas_stops"]])


def band_rgba(data, cmap, v, vmin, vmax):
    """Quantize values into nbands gamma-warped color bands."""
    nbands = data.constants["nbands"]
    gamma = data.constants["gamma"]
    w = np.clip((v - vmin) / (vmax - vmin), 0.0, 1.0) ** gamma
    band = np.clip((w * nbands).astype(np.int32), 0, nbands - 1)
    rgba = cmap((band + 0.5) / nbands)
    return rgba, band


def _arrow(off, color):
    if max(abs(off[0]), abs(off[1])) >= 16:
        return dict(arrowstyle="-", color=color, lw=0.7, alpha=0.85,
                    shrinkA=4, shrinkB=5, zorder=8)
    return None


def _shown_value(val, limit):
    """Nudge values that would print as the limit but sit beyond it."""
    return math.ceil(val) if (val > limit and round(val) <= limit) else val


def _place_pos(point):
    return point.marker_ll if point.marker_ll else point.ll


def draw_side_key(fig, data, meta, key, limit, is_comb, vmin, cmap):
    """Right-hand key panel for the '_clean' map variants: every name and
    value the labelled version draws over the map is listed here instead."""
    from matplotlib.patches import Rectangle

    kx = fig.add_axes([0.675, 0.055, 0.31, 0.865])
    kx.set_axis_off()
    kx.set_xlim(0.0, 1.0)
    kx.set_ylim(0.0, 1.0)
    navy = (11 / 255, 61 / 255, 145 / 255)
    pv = meta["places"]

    def town_sort(t):
        v = pv.get(t.name, {}).get(key)
        return 1e9 if v is None else v

    rows = []
    rows.append((1.7, "title", "KEY  (IDs match map markers)"))
    rows.append((1.35, "head", "crime scenes  (S1-S%d)" % len(data.scenes)))
    for sc in data.scenes:
        active = (key == sc.key)
        parts = sc.label.split("\n")
        name = parts[0]
        date = parts[1] if len(parts) > 1 else ""
        rows.append((1.0, "scene",
                     (data.scene_ids[sc.key], name, date, active,
                      data.colors["scene_active"] if active
                      else data.colors["scene"])))
    rows.append((1.35, "head",
                 "towns - %s, limit %.0f min"
                 % ("min loiter L required" if is_comb
                    else "drive time from %s" % data.scene_by_key[key].name,
                    limit)))
    for t in sorted(data.frontier, key=town_sort):
        val = pv.get(t.name, {}).get(key)
        rows.append((1.0, "place", (t.name, val, val is not None and val <= limit,
                                    True)))
    rows.append((1.35, "head", "reference cities  (small dot)"))
    for t in sorted(data.reference, key=town_sort):
        val = pv.get(t.name, {}).get(key)
        rows.append((1.0, "place", (t.name, val, val is not None and val <= limit,
                                    False)))
    last_letter = chr(ord("A") + len(data.suspects) - 1)
    rows.append((1.35, "head",
                 "suspects A-%s (documented bases)" % last_letter))
    for sus in data.suspects:
        rows.append((1.0, "sus",
                     (data.suspect_ids[sus.label], sus.label.replace("\n", " "),
                      sus.tier)))
    n_front = len(data.frontier)
    n_ref = len(data.reference)
    rows.append((1.35, "head", "road color"))
    rows.append((2.6, "grad", None))
    rows.append((2.4, "note",
                 "IDs match map markers: S# = crime scene, 1-%d = frontier\n"
                 "town, %d-%d = reference city, letter = suspect; green =\n"
                 "within limit, red = beyond, black roads = infeasible"
                 % (n_front, n_front + 1, n_front + n_ref)))

    total = sum(u for u, _, _ in rows)
    step = 0.98 / total
    y = 1.0
    for unit, kind, payload in rows:
        y -= 0.5 * unit * step
        if kind == "title":
            kx.text(0.02, y, payload, fontsize=12.5, fontweight="bold",
                    color=navy, va="center")
        elif kind == "head":
            kx.text(0.02, y, payload, fontsize=10, fontweight="bold",
                    color=navy, va="center")
        elif kind == "scene":
            sid, name, date, active, col = payload
            kx.scatter([0.05], [y], s=70 if active else 48, marker="*",
                       c=col, edgecolors="k", linewidths=0.5, zorder=4)
            kx.text(0.10, y, "%s  %s" % (sid, name)
                    + ("  (field origin)" if active else ""),
                    fontsize=9, fontweight="bold" if active else "normal",
                    va="center")
            kx.text(0.99, y, date, fontsize=8, color="0.35", ha="right",
                    va="center")
        elif kind == "place":
            name, val, ok, big = payload
            idx = data.town_ids[name]
            if val is None:
                kx.scatter([0.05], [y], s=46 if big else 26, c="0.7",
                           edgecolors="k", linewidths=0.5 if big else 0.4,
                           zorder=4)
                kx.text(0.10, y, "%2d  %s" % (idx, name),
                        fontsize=9 if big else 8.5,
                        color="0.1" if big else "0.35", va="center")
                kx.text(0.99, y, "unreachable", fontsize=7.5, color="0.45",
                        ha="right", va="center")
            else:
                shown = _shown_value(val, limit)
                kx.scatter([0.05], [y], s=46 if big else 26,
                           c=data.colors["ok"] if ok else data.colors["fail"],
                           edgecolors="k", linewidths=0.5 if big else 0.4,
                           zorder=4)
                kx.text(0.10, y, "%2d  %s" % (idx, name),
                        fontsize=9 if big else 8.5,
                        color="0.1" if big else "0.35", va="center")
                kx.text(0.90, y, "%.0f" % shown, fontsize=9, fontweight="bold",
                        color=data.colors["ok_text"] if ok
                        else data.colors["fail_text"],
                        ha="right", va="center")
                kx.text(0.99, y, "min", fontsize=7.5, color="0.45", ha="right",
                        va="center")
        elif kind == "sus":
            sid, name, tier = payload
            kx.scatter([0.05], [y], s=32, marker="D",
                       c=data.colors["suspect"][tier],
                       edgecolors="k", linewidths=0.4, zorder=4)
            kx.text(0.10, y, "%s  %s" % (sid, name),
                    fontsize=9, color=data.colors["suspect"][tier],
                    va="center")
        elif kind == "grad":
            strip, _ = band_rgba(data, cmap, np.linspace(vmin, limit, 128),
                                 vmin, limit)
            kx.imshow(strip.reshape(1, -1, 4),
                      extent=[0.11, 0.70, y - 0.022, y + 0.022],
                      aspect="auto", zorder=3)
            kx.add_patch(Rectangle((0.72, y - 0.022), 0.27, 0.044,
                                   fc="#141414", ec="k", lw=0.4, zorder=3))
            kx.text(0.11, y + 0.026, "%.0f  / faster" % vmin, fontsize=7.5,
                    va="bottom")
            kx.text(0.70, y + 0.026, "%.0f min limit" % limit, fontsize=7.5,
                    ha="right", va="bottom")
            kx.text(0.855, y, "black: beyond", fontsize=7.5, ha="center",
                    va="center", color="w")
        elif kind == "note":
            kx.text(0.02, y, payload, fontsize=8, color="0.35", va="center")
        y -= 0.5 * unit * step


def _save_png(log, fig, out_png, attempts=8):
    """Save a figure via a temp file and atomic replace.

    Windows occasionally refuses to (re)open a freshly written PNG for
    many seconds (antivirus scanner, indexer, cloud sync: Errno 22 or a
    sharing violation), so retry both the temp write and the replace with
    growing backoff instead of trusting a single open().
    """
    tmp = out_png + ".part.png"
    try:
        for attempt in range(attempts):
            try:
                fig.savefig(tmp, dpi=150)
                break
            except OSError as exc:
                if attempt == attempts - 1:
                    raise
                log("  save retry %d/%d (write) %s: %s"
                    % (attempt + 1, attempts, os.path.basename(out_png), exc))
                time.sleep(1.5 * (attempt + 1))
        for attempt in range(attempts):
            try:
                os.replace(tmp, out_png)
                return
            except OSError as exc:
                if attempt == attempts - 1:
                    raise
                log("  save retry %d/%d (replace) %s: %s"
                    % (attempt + 1, attempts, os.path.basename(out_png), exc))
                time.sleep(1.5 * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def render_map(log, data, meta, pieces, key, png_name, base, figures_dir,
               clean=False):
    """Render one map (labelled or clean) to figures_dir/png_name."""
    cmap = feasible_cmap(data)
    is_comb = key == "comb"
    ki = meta["keys"].index(key)
    limit = data.limit_of(key)
    vmin = meta.get("comb_vmin", 0.0) if is_comb else 0.0
    vals = pieces["vals"][ki]
    m = np.isfinite(vals)
    v = vals[m]
    segs = pieces["segs"][m]
    widths = pieces["widths"][m]
    order = np.argsort(-v, kind="stable")
    v = v[order]
    segs = segs[order]
    widths = widths[order]
    n_black = int((v > limit).sum())

    rgba, _band = band_rgba(data, cmap, v, vmin, limit)
    rgba[v > limit] = (0.08, 0.08, 0.08, 0.95)  # black: feasibility zero

    fig = plt.figure(figsize=(17, 14))
    ax = fig.add_axes([0.04, 0.07, 0.63 if clean else 0.93, 0.85])
    w, e, s, n = geo.bbox_extent(data.constants["bbox"])
    ax.set_xlim(w, e)
    ax.set_ylim(s, n)
    ax.set_aspect("equal")
    ax.set_axis_off()

    if base is not None:
        img, ext = base
        ax.imshow(img, extent=ext, alpha=0.85, interpolation="bilinear",
                  zorder=1, aspect="equal")

    lc = LineCollection(segs, colors=rgba, linewidths=widths,
                        capstyle="round", antialiased=True, zorder=2)
    ax.add_collection(lc)
    label_items = []
    markers = []

    # ---- crime scenes (all of them on every map) --------------------------
    for sc in data.scenes:
        mx, my = geo.mercator(*sc.ll)
        active = (key == sc.key)
        ax.scatter([mx], [my], s=270 if active else 130, marker="*",
                   c=data.colors["scene_active"] if active
                   else data.colors["scene"],
                   edgecolors="k", linewidths=1.0, zorder=8)
        if clean:
            ann = ax.annotate(data.scene_ids[sc.key], (mx, my), xytext=(7, 4),
                              textcoords="offset points", fontsize=6.5,
                              fontweight="bold", color="#111111", ha="left",
                              va="bottom", zorder=9,
                              bbox=dict(boxstyle="round,pad=0.12", fc="white",
                                        ec="#c41e1e", alpha=0.95, lw=0.45))
            label_items.append((sc.short + " badge", ann))
        else:
            off = tuple(sc.label_offset)
            ann = ax.annotate(sc.label, (mx, my),
                              fontsize=9 if active else 7.5,
                              fontweight="bold", xytext=off,
                              textcoords="offset points", zorder=10,
                              arrowprops=_arrow(off, "#c41e1e" if active else "k"),
                              bbox=dict(boxstyle="round,pad=0.22", fc="white",
                                        ec="#c41e1e" if active else "k",
                                        alpha=0.92, lw=0.8))
            label_items.append((sc.short + " scene", ann))
        markers.append((sc.short + " star", (mx, my)))

    # ---- towns (frontier + reference) -------------------------------------
    for town in data.frontier + data.reference:
        pv = meta["places"].get(town.name)
        if not pv or pv.get(key) is None:
            continue
        val = pv[key]
        la, lo = _place_pos(town)
        mx, my = geo.mercator(la, lo)
        ok = val <= limit
        col = data.colors["ok"] if ok else data.colors["fail"]
        txt = data.colors["ok_text"] if ok else data.colors["fail_text"]
        big = town.tier == "frontier"
        ax.scatter([mx], [my], s=70 if big else 46, c=col, edgecolors="k",
                   linewidths=0.7, zorder=7)
        shown = _shown_value(val, limit)
        if clean:
            idx = data.town_ids[town.name]
            if big:
                ax.text(mx, my, str(idx), fontsize=6, fontweight="bold",
                        color="white", ha="center", va="center", zorder=9)
            else:
                ann = ax.annotate(str(idx), (mx, my), xytext=(5, 4),
                                  textcoords="offset points", fontsize=6,
                                  fontweight="bold", color="#111111",
                                  ha="left", va="bottom", zorder=9,
                                  bbox=dict(boxstyle="round,pad=0.12",
                                            fc="white", ec="0.45", alpha=0.9,
                                            lw=0.4))
                label_items.append((town.name + " badge", ann))
        else:
            label = "%s\n%.0f min" % (town.name, shown)
            off = tuple(town.label_offset)
            ann = ax.annotate(label, (mx, my), fontsize=8 if big else 7.5,
                              fontweight="bold" if big else "normal",
                              xytext=off, textcoords="offset points",
                              color=txt, zorder=10,
                              arrowprops=_arrow(off, col),
                              bbox=dict(boxstyle="round,pad=0.18", fc="white",
                                        ec=col, alpha=0.92, lw=0.6))
            label_items.append((town.name, ann))
        markers.append((town.name + " dot", (mx, my)))

    # ---- suspects ---------------------------------------------------------
    for sus in data.suspects:
        la, lo = _place_pos(sus)
        mx, my = geo.mercator(la, lo)
        c = data.colors["suspect"][sus.tier]
        ax.scatter([mx], [my], s=64, c=c, marker="D", edgecolors="k",
                   linewidths=0.6, zorder=8)
        short = sus.label.split("\n")[0]
        if clean:
            ann = ax.annotate(data.suspect_ids[sus.label], (mx, my),
                              xytext=(5, 3), textcoords="offset points",
                              fontsize=6, fontweight="bold", color="#111111",
                              ha="left", va="bottom", zorder=9,
                              bbox=dict(boxstyle="round,pad=0.12", fc="white",
                                        ec=c, alpha=0.9, lw=0.45))
            label_items.append((short + " badge", ann))
        else:
            off = tuple(sus.label_offset)
            ann = ax.annotate(sus.label, (mx, my), fontsize=7, xytext=off,
                              textcoords="offset points", color=c, zorder=10,
                              arrowprops=_arrow(off, c),
                              bbox=dict(boxstyle="round,pad=0.16", fc="white",
                                        ec=c, alpha=0.92, lw=0.6))
            label_items.append((sus.label, ann))
        markers.append((short + " diamond", (mx, my)))

    # ---- colorbar (labelled maps; clean maps use the side-key gradient) ---
    if not clean:
        nbands = data.constants["nbands"]
        gamma = data.constants["gamma"]
        edges_b = vmin + (limit - vmin) \
            * (np.arange(nbands + 1) / nbands) ** (1.0 / gamma)
        bcolors = cmap((np.arange(nbands) + 0.5) / nbands)
        norm_b = BoundaryNorm(edges_b, nbands)
        sm = plt.cm.ScalarMappable(cmap=ListedColormap(bcolors), norm=norm_b)
        sm.set_array([])
        cax = fig.add_axes([0.04, 0.30, 0.016, 0.42])
        cbar = fig.colorbar(sm, cax=cax)
        if is_comb:
            cbar.set_label("minimum pre-attack loiter L required (min)",
                           fontsize=10)
            tk0 = int(math.ceil(vmin / 5.0) * 5)
            cbar.set_ticks(list(range(tk0, int(limit) + 1, 5)))
        else:
            cbar.set_label("drive time to %s (min)"
                           % data.scene_by_key[key].name, fontsize=10)
            cbar.set_ticks([0, 15, 30, 45, 60, 75])
        cbar.ax.tick_params(labelsize=9)
        cax.text(0.5, -0.14, "black: > %d min\n(feasibility = 0)" % limit,
                 transform=cax.transAxes, ha="center", va="top", fontsize=8.5,
                 color="#333333")

    # ---- marker legend (labelled maps only) -------------------------------
    if not clean:
        if is_comb:
            handles = [
                Line2D([0], [0], marker="*", color="w",
                       markerfacecolor=data.colors["scene"],
                       markeredgecolor="k", markersize=11,
                       label="canonical scenes"),
            ]
        else:
            handles = [
                Line2D([0], [0], marker="*", color="w",
                       markerfacecolor=data.colors["scene_active"],
                       markeredgecolor="k", markersize=15,
                       label="%s (field origin)"
                       % data.scene_by_key[key].name),
                Line2D([0], [0], marker="*", color="w",
                       markerfacecolor=data.colors["scene"],
                       markeredgecolor="k", markersize=11,
                       label="other canonical scenes"),
            ]
        handles += [
            Line2D([0], [0], marker="o", color="w",
                   markerfacecolor=data.colors["ok"],
                   markeredgecolor="k", markersize=8,
                   label="place within this map's %.0f min limit" % limit),
            Line2D([0], [0], marker="o", color="w",
                   markerfacecolor=data.colors["fail"],
                   markeredgecolor="k", markersize=8,
                   label="place beyond this map's limit"),
        ]
        tier_legend = data.colors.get("tier_legend") or {}
        for tier, color in data.colors["suspect"].items():
            handles.append(Line2D(
                [0], [0], marker="D", color="w", markerfacecolor=color,
                markersize=7, markeredgecolor="k",
                label=tier_legend.get(tier, "Suspect (%s)" % tier.upper())))
        leg = ax.legend(handles=handles, loc="lower right", fontsize=8.5,
                        framealpha=0.95)
        leg.set_zorder(11)

    limit_const = data.constants["limit"]
    if is_comb:
        title = ("Four-attack residence feasibility on real roads: minimum "
                 "pre-attack loiter each road needs\n"
                 "min_L = max_i[drive_i - window_i] + %g min overhead  ->  "
                 "red = %d min limit  ->  black = infeasible  |  "
                 "the solver frontier, mapped"
                 % (data.constants["overhead"], int(limit_const)))
    else:
        sc = data.scene_by_key[key]
        title = ("Residence feasibility as a travel-time field: drive time "
                 "to %s\n"
                 "red = %.0f min drive limit (= L %d + window %g - overhead "
                 "%g)  ->  black = beyond  |  OSM roads x OSRM-calibrated "
                 "Dijkstra"
                 % (sc.name, limit, int(limit_const), sc.win,
                    data.constants["overhead"]))
    if clean:
        # ax is only 0.63 wide on clean maps -> ax.set_title overflows the
        # figure's left edge; center on the full figure instead
        fig.text(0.5, 0.975, title, fontsize=13.5, fontweight="bold",
                 ha="center", va="top", zorder=11)
    else:
        ax.set_title(title, fontsize=13.5, fontweight="bold", pad=12)

    if is_comb and meta.get("bind_counts"):
        parts = ", ".join("%s %d" % (k, v)
                          for k, v in sorted(meta["bind_counts"].items(),
                                             key=lambda x: -x[1]))
        fig.text(0.05, 0.095,
                 "binds: %s\n(per-town binding scene; details in the report)"
                 % parts,
                 fontsize=8.5, color="0.15", va="bottom", ha="left", zorder=11,
                 bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="0.6",
                           alpha=0.92, lw=0.6))

    # push colliding labels/markers apart before anything is baked in
    labels.nudge_labels(log, fig, ax, label_items, markers,
                        tag=key + (" clean" if clean else ""))

    if clean:
        draw_side_key(fig, data, meta, key, limit, is_comb, vmin, cmap)
    elif key in (data.maps[0][0], "comb"):
        # combined-map town labels carry the bind suffix -> wider boxes,
        # so its layout is checked separately from the per-scene maps
        labels.check_layout(log, fig, ax, label_items, markers, tag=key)

    out_png = os.path.join(figures_dir, png_name)
    _save_png(log, fig, out_png)
    plt.close(fig)
    log("  %s: %d pieces drawn, %d black, wrote %s"
        % (key, len(v), n_black, out_png))
    return out_png
