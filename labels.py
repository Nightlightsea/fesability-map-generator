"""Label layout helpers: overlap checking and force-based nudging.

Kept apart from render.py so the drawing code stays readable.  Both work in
display space after a single figure draw, so they are fast even with 1.4 M
road pieces on the axes.
"""
import math
import os

import numpy as np


def check_layout(log, fig, ax, labels, markers, tag=""):
    """Flag label/label overlaps and markers hidden under label boxes.

    Layout is identical on every map of the same class (fixed offsets from
    fixed markers), so this runs once per layout class.
    """
    try:
        r = fig.canvas.get_renderer()
    except Exception:
        return
    try:
        fig.canvas.draw()  # bbox patches only get positioned during draw
        r = fig.canvas.get_renderer()
    except Exception:
        pass
    items = []
    for name, t in labels:
        bb = None
        try:
            bp = t.get_bbox_patch()
            if bp is not None:
                bb = bp.get_window_extent(renderer=r)
        except Exception:
            bb = None
        if bb is None:
            try:
                bb = t.get_window_extent(renderer=r)
            except TypeError:
                bb = t.get_window_extent()
        if bb.width > 0:
            # visible white label box (bbox patch extent, pad included;
            # Annotation.get_window_extent would also include the leader arrow)
            items.append((name, bb))
    if os.environ.get("ZODIAC_LAYOUT_DUMP"):
        for name, bb in items:
            log("    box [%s] %-22s x %4.0f..%4.0f  y %4.0f..%4.0f"
                % (tag, name.replace("\n", "/"), bb.x0, bb.x1, bb.y0, bb.y1))
        tr0 = ax.transData
        for name, (x, y) in markers:
            px, py = tr0.transform((x, y))
            log("    mark [%s] %-21s x %4.0f  y %4.0f"
                % (tag, name.replace("\n", "/"), px, py))
    n_bad = 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            na, a = items[i]
            nb, b = items[j]
            ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
            iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
            ov = ix * iy
            if ov > 0.25 * min(a.width * a.height, b.width * b.height) and ov > 60:
                log("  LAYOUT overlap [%s]: %s <-> %s (%.0f px^2)"
                    % (tag, na.replace("\n", "/"), nb.replace("\n", "/"), ov))
                n_bad += 1
    tr = ax.transData
    for name, (x, y) in markers:
        px, py = tr.transform((x, y))
        for n2, bb in items:
            if bb.x0 - 2 <= px <= bb.x1 + 2 and bb.y0 - 2 <= py <= bb.y1 + 2:
                log("  LAYOUT marker under label [%s]: %s under %s"
                    % (tag, name.replace("\n", "/"), n2.replace("\n", "/")))
                n_bad += 1
    if n_bad == 0:
        log("  layout check: clean (%s: %d labels, %d markers)"
            % (tag or "?", len(items), len(markers)))
    elif tag:
        log("  layout issues above are for: %s" % tag)


def nudge_labels(log, fig, ax, items, markers, tag=""):
    """Force-directed label cleanup: push overlapping label boxes and boxes
    covering markers apart, then bake the final offsets into the annotations
    (leader lines follow automatically).

    items: list of (name, annotation).  Box sizes are measured once; the
    simulation then runs in display space without re-rasterizing the road
    pieces, so it is cheap.  Each label springs back toward its tuned home
    offset via a distance cap, so nudging only moves what collides.
    """
    if not items:
        return
    try:
        fig.canvas.draw()  # bbox patches are only positioned during draw
        r = fig.canvas.get_renderer()
    except Exception:
        return
    pt = fig.dpi / 72.0  # points -> display px
    tr = ax.transData

    infos = []
    for name, ann in items:
        try:
            bp = ann.get_bbox_patch()
            bb = bp.get_window_extent(renderer=r) if bp is not None else None
        except Exception:
            bb = None
        if bb is None or bb.width <= 0:
            continue
        home = tuple(float(v) for v in ann.get_position())  # offset points
        anchor = tr.transform(ann.xy)
        ref = np.array([anchor[0] + home[0] * pt, anchor[1] + home[1] * pt])
        center = np.array([(bb.x0 + bb.x1) / 2.0, (bb.y0 + bb.y1) / 2.0])
        infos.append({"name": name, "ann": ann, "home": home,
                      "anchor": anchor, "wh": (bb.width, bb.height),
                      "delta": center - ref, "pos": list(home)})

    mark_px = [np.array(tr.transform((x, y))) for _n, (x, y) in markers]
    margin = 3.0  # px of clear space that must remain between boxes/markers
    mark_r = 4.0  # markers drawn as stars/diamonds/dots are not points

    def box_of(it):
        x, y = it["pos"]
        cx = it["anchor"][0] + x * pt + it["delta"][0]
        cy = it["anchor"][1] + y * pt + it["delta"][1]
        w, h = it["wh"]
        return cx - w / 2.0, cx + w / 2.0, cy - h / 2.0, cy + h / 2.0

    def violations(boxes):
        n = 0
        for i in range(len(infos)):
            x0a, x1a, y0a, y1a = boxes[i]
            for j in range(i + 1, len(infos)):
                x0b, x1b, y0b, y1b = boxes[j]
                ix = min(x1a, x1b) - max(x0a, x0b) + margin
                iy = min(y1a, y1b) - max(y0a, y0b) + margin
                if ix > 0 and iy > 0:
                    n += 1
        for x0, x1, y0, y1 in boxes:
            for mp in mark_px:
                ix = min(x1, mp[0] + mark_r) - max(x0, mp[0] - mark_r) + margin
                iy = min(y1, mp[1] + mark_r) - max(y0, mp[1] - mark_r) + margin
                if ix > 0 and iy > 0:
                    n += 1
        return n

    caps = [max(35.0, 1.9 * math.hypot(*it["home"])) for it in infos]
    damp = 0.7
    best_n = None
    best_pos = None
    stall = 0
    prev_best = None
    for itn in range(200):
        boxes = [box_of(it) for it in infos]
        nv = violations(boxes)
        if best_n is None or nv < best_n:
            best_n = nv
            best_pos = [list(it["pos"]) for it in infos]
        if nv == 0:
            break
        # deadlock escape: pairwise forces cancel (a badge wedged between two
        # markers); after a stall, jolt every label in a violation sideways
        if prev_best is not None and best_n >= prev_best:
            stall += 1
        else:
            stall = 0
        prev_best = best_n
        if stall > 25:
            stall = 0
            in_conflict = set()
            for i in range(len(infos)):
                for j in range(i + 1, len(infos)):
                    x0a, x1a, y0a, y1a = boxes[i]
                    x0b, x1b, y0b, y1b = boxes[j]
                    if min(x1a, x1b) - max(x0a, x0b) + margin > 0 \
                            and min(y1a, y1b) - max(y0a, y0b) + margin > 0:
                        in_conflict.add(i)
                        in_conflict.add(j)
            for i, bb in enumerate(boxes):
                x0, x1, y0, y1 = bb
                for mp in mark_px:
                    if min(x1, mp[0] + mark_r) - max(x0, mp[0] - mark_r) \
                            + margin > 0 \
                            and min(y1, mp[1] + mark_r) - max(y0, mp[1] - mark_r) \
                            + margin > 0:
                        in_conflict.add(i)
            for i in sorted(in_conflict):
                # cheap deterministic pseudo-random direction per iteration
                ang = ((itn * 7 + i * 13) % 360) * math.pi / 180.0
                step = 7.0 / pt
                infos[i]["pos"][0] += math.cos(ang) * step
                infos[i]["pos"][1] += math.sin(ang) * step
        moved = False
        for i in range(len(infos)):
            for j in range(i + 1, len(infos)):
                x0a, x1a, y0a, y1a = boxes[i]
                x0b, x1b, y0b, y1b = boxes[j]
                ix = min(x1a, x1b) - max(x0a, x0b) + margin
                iy = min(y1a, y1b) - max(y0a, y0b) + margin
                if ix <= 0 or iy <= 0:
                    continue
                # push along the axis of least penetration
                pa, pb = list(infos[i]["pos"]), list(infos[j]["pos"])
                if ix < iy:
                    push = damp * 0.5 * (ix + 1.0) / pt
                    sgn = -1.0 if (x0a + x1a) <= (x0b + x1b) else 1.0
                    pa[0] += sgn * push
                    pb[0] -= sgn * push
                else:
                    push = damp * 0.5 * (iy + 1.0) / pt
                    sgn = -1.0 if (y0a + y1a) <= (y0b + y1b) else 1.0
                    pa[1] += sgn * push
                    pb[1] -= sgn * push
                infos[i]["pos"], infos[j]["pos"] = pa, pb
                boxes[i], boxes[j] = box_of(infos[i]), box_of(infos[j])
                moved = True
        for i, it in enumerate(infos):
            x0, x1, y0, y1 = boxes[i]
            for mp in mark_px:
                mx0, mx1 = mp[0] - mark_r, mp[0] + mark_r
                my0, my1 = mp[1] - mark_r, mp[1] + mark_r
                ix = min(x1, mx1) - max(x0, mx0) + margin
                iy = min(y1, my1) - max(y0, my0) + margin
                if ix <= 0 or iy <= 0:
                    continue
                if ix < iy:
                    sgn = -1.0 if (x0 + x1) <= (mx0 + mx1) else 1.0
                    it["pos"][0] += sgn * (ix + 1.0) / pt
                else:
                    sgn = -1.0 if (y0 + y1) <= (my0 + my1) else 1.0
                    it["pos"][1] += sgn * (iy + 1.0) / pt
                boxes[i] = box_of(it)
                moved = True
        for it, cap in zip(infos, caps):
            hx, hy = it["home"]
            dx, dy = it["pos"][0] - hx, it["pos"][1] - hy
            d = math.hypot(dx, dy)
            if d > cap:
                it["pos"] = [hx + dx / d * cap, hy + dy / d * cap]
        if not moved:
            break
    # restore the cleanest state reached (damped pushes can overshoot)
    if best_pos is not None:
        for it, p in zip(infos, best_pos):
            it["pos"] = p
    resid = violations([box_of(it) for it in infos])
    if resid and os.environ.get("ZODIAC_LAYOUT_DUMP"):
        boxes = [box_of(it) for it in infos]
        for i in range(len(infos)):
            x0a, x1a, y0a, y1a = boxes[i]
            for j in range(i + 1, len(infos)):
                x0b, x1b, y0b, y1b = boxes[j]
                ix = min(x1a, x1b) - max(x0a, x0b) + margin
                iy = min(y1a, y1b) - max(y0a, y0b) + margin
                if ix > 0 and iy > 0:
                    log("    nudge-hit [%s] %s | %s  pen=(%.1f, %.1f) px"
                        % (tag, infos[i]["name"].replace("\n", "/"),
                           infos[j]["name"].replace("\n", "/"), ix, iy))
        for i, it in enumerate(infos):
            x0, x1, y0, y1 = boxes[i]
            for k, mp in enumerate(mark_px):
                ix = min(x1, mp[0] + mark_r) - max(x0, mp[0] - mark_r) + margin
                iy = min(y1, mp[1] + mark_r) - max(y0, mp[1] - mark_r) + margin
                if ix > 0 and iy > 0:
                    log("    nudge-hit [%s] %s covers marker %s"
                        "  pen=(%.1f, %.1f) mk=(%.1f,%.1f)"
                        % (tag, it["name"].replace("\n", "/"), markers[k][0],
                           ix, iy, mp[0], mp[1]))

    n_moved = 0
    max_d = 0.0
    for it in infos:
        p = it["pos"]
        d = math.hypot(p[0] - it["home"][0], p[1] - it["home"][1])
        if d > 0.5:
            n_moved += 1
            max_d = max(max_d, d)
            it["ann"].set_position((p[0], p[1]))
    if n_moved:
        log("  nudge [%s]: %d/%d labels adjusted (max %.0f pt)"
            % (tag, n_moved, len(infos), max_d))
    if resid:
        log("  nudge [%s]: %d clearance violation(s) remain" % (tag, resid))
