"""Load and validate points.json into typed, derived structures.

The data file is the single place to edit scenes, towns, suspects, colors and
paths.  This module turns it into a `Data` object with everything the rest of
the program needs: resolved paths, per-map limits/render caps, and stable IDs
(S1.., town numbers, suspect letters) that stay identical on every map.
"""
import json
import os
from dataclasses import dataclass, field


class DataError(Exception):
    """points.json failed validation; the message names the exact field."""


def _numnum(obj, ctx):
    if (not isinstance(obj, (list, tuple)) or len(obj) != 2
            or not all(isinstance(v, (int, float)) for v in obj)):
        raise DataError("%s: expected [lat, lon], got %r" % (ctx, obj))
    return float(obj[0]), float(obj[1])


def _offset(obj, ctx, default):
    if obj is None:
        return tuple(default)
    return tuple(_numnum(obj, ctx))


@dataclass(frozen=True)
class Scene:
    key: str
    name: str
    short: str
    label: str
    ll: tuple
    win: float
    wp: str
    label_offset: tuple


@dataclass(frozen=True)
class Town:
    name: str
    ll: tuple
    tier: str
    label_offset: tuple
    marker_ll: tuple


@dataclass(frozen=True)
class Suspect:
    label: str
    ll: tuple
    tier: str
    label_offset: tuple
    marker_ll: tuple


@dataclass
class Data:
    constants: dict
    colors: dict
    scenes: list
    towns: list
    suspects: list
    maps: list
    cross_check: list
    paths: dict
    events: list = field(default_factory=list)
    chains: list = field(default_factory=list)
    # derived (filled by load)
    scene_by_key: dict = field(default_factory=dict)
    event_by_key: dict = field(default_factory=dict)
    frontier: list = field(default_factory=list)
    reference: list = field(default_factory=list)
    town_by_name: dict = field(default_factory=dict)
    keys: list = field(default_factory=list)
    limits: dict = field(default_factory=dict)
    caps: dict = field(default_factory=dict)
    scene_ids: dict = field(default_factory=dict)
    town_ids: dict = field(default_factory=dict)
    suspect_ids: dict = field(default_factory=dict)

    def limit_of(self, key):
        return self.limits["comb"] if key == "comb" else self.limits[key]

    def name_of(self, key):
        return self.scene_by_key[key].name if key in self.scene_by_key else "all four attacks"


def _resolve_paths(raw, base):
    defaults = {
        "tiles_dir": "tiles",
        "osrm_cache": "osrm_cache.json",
        "figures_dir": "figures",
        "report": os.path.join("cache", "report.txt"),
    }
    merged = dict(defaults)
    if isinstance(raw, dict):
        merged.update({k: v for k, v in raw.items() if v})
    out = {}
    for k, v in merged.items():
        v = str(v)
        out[k] = v if os.path.isabs(v) else os.path.abspath(os.path.join(base, v))
    return out


def _merge(base, override):
    """One-level merge: dict-valued keys (constants, colors, paths) merge
    key-by-key; lists and scalars are replaced whole."""
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = dict(out[k])
            merged.update(v)
            out[k] = merged
        else:
            out[k] = v
    return out


def load(path, override=None):
    """Load `path`, optionally overlaid with a test override file.

    The override is a partial points file (usually one small experiment per
    file); dict-valued keys merge key-by-key, everything else replaces.
    """
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    if override is not None:
        with open(override, encoding="utf-8") as fh:
            over = json.load(fh)
        if not isinstance(over, dict):
            raise DataError("%s: a test file must be a JSON object" % override)
        raw = _merge(raw, over)
    base = os.path.dirname(os.path.abspath(path))

    const = raw.get("constants") or {}
    try:
        constants = {
            "limit": float(const["limit"]),
            "overhead": float(const["overhead"]),
            "gamma": float(const["gamma"]),
            "nbands": int(const["nbands"]),
            "max_piece_m": float(const["max_piece_m"]),
            "offscreen_factor": float(const.get("offscreen_factor", 1.6)),
            "bbox": tuple(float(v) for v in const["bbox"]),
            "tiles": int(const["tiles"]),
            "zoom": int(const["zoom"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise DataError("constants: missing or invalid value for %s" % exc)

    colors = raw.get("colors") or {}

    scenes = []
    for i, s in enumerate(raw.get("scenes") or []):
        ctx = "scenes[%d]" % i
        try:
            key = str(s["key"])
            win = float(s["win"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DataError("%s: missing key/win (%s)" % (ctx, exc))
        if win <= 0:
            raise DataError("%s.win: must be > 0" % ctx)
        scenes.append(Scene(
            key=key,
            name=str(s.get("name", key)),
            short=str(s.get("short", key)),
            label=str(s.get("label", s.get("name", key))),
            ll=_numnum(s.get("ll"), ctx + ".ll"),
            win=win,
            wp=str(s["wp"]) if s.get("wp") else None,
            label_offset=_offset(s.get("label_offset"), ctx + ".label_offset", (25, -36)),
        ))
    if len({s.key for s in scenes}) != len(scenes):
        raise DataError("scenes: duplicate keys")

    towns = []
    for i, t in enumerate(raw.get("towns") or []):
        ctx = "towns[%d] (%s)" % (i, t.get("name", "?"))
        tier = str(t.get("tier", "frontier"))
        if tier not in ("frontier", "reference"):
            raise DataError("%s.tier: must be 'frontier' or 'reference', got %r" % (ctx, tier))
        towns.append(Town(
            name=str(t["name"]),
            ll=_numnum(t.get("ll"), ctx + ".ll"),
            tier=tier,
            label_offset=_offset(t.get("label_offset"), ctx + ".label_offset", (12, 10)),
            marker_ll=_numnum(t["marker_ll"], ctx + ".marker_ll") if t.get("marker_ll") else None,
        ))
    if len({t.name for t in towns}) != len(towns):
        raise DataError("towns: duplicate names")

    suspect_tiers = colors.get("suspect") or {}
    suspects = []
    for i, s in enumerate(raw.get("suspects") or []):
        ctx = "suspects[%d] (%s)" % (i, s.get("label", "?").replace("\n", "/"))
        tier = str(s.get("tier", ""))
        if tier not in suspect_tiers:
            raise DataError("%s.tier: %r is not a key of colors.suspect (%s)"
                            % (ctx, tier, sorted(suspect_tiers)))
        suspects.append(Suspect(
            label=str(s["label"]),
            ll=_numnum(s.get("ll"), ctx + ".ll"),
            tier=tier,
            label_offset=_offset(s.get("label_offset"), ctx + ".label_offset", (8, -12)),
            marker_ll=_numnum(s["marker_ll"], ctx + ".marker_ll") if s.get("marker_ll") else None,
        ))

    town_by_name = {t.name: t for t in towns}
    cross_check = []
    for i, entry in enumerate(raw.get("cross_check") or []):
        if isinstance(entry, str):
            if entry not in town_by_name:
                raise DataError("cross_check[%d]: %r is not a town name" % (i, entry))
            cross_check.append((entry, town_by_name[entry].ll))
        else:
            cross_check.append((str(entry["name"]),
                                _numnum(entry.get("ll"), "cross_check[%d].ll" % i)))

    events = []
    for i, e in enumerate(raw.get("events") or []):
        ctx = "events[%d]" % i
        if not isinstance(e, dict) or not e.get("key"):
            raise DataError("%s: every event needs a 'key'" % ctx)
        events.append({
            "key": str(e["key"]),
            "name": str(e.get("name", e["key"])),
            "kind": str(e.get("kind", "event")),
            "waypoint": str(e["waypoint"]) if e.get("waypoint") else None,
            "ll": _numnum(e["ll"], ctx + ".ll") if e.get("ll") else None,
            "t": str(e["t"]) if e.get("t") else None,
            "note": str(e.get("note", "")),
        })
    if len({e["key"] for e in events}) != len(events):
        raise DataError("events: duplicate keys")

    chains = []
    for i, ch in enumerate(raw.get("chains") or []):
        ctx = "chains[%d]" % i
        try:
            chains.append({
                "from": str(ch["from"]),
                "to": str(ch["to"]),
                "gap_min": float(ch["gap_min"]),
                "note": str(ch.get("note", "")),
            })
        except (KeyError, TypeError, ValueError) as exc:
            raise DataError("%s: needs from/to/gap_min (%s)" % (ctx, exc))

    data = Data(
        constants=constants,
        colors=colors,
        scenes=scenes,
        towns=towns,
        suspects=suspects,
        maps=[(str(k), str(p)) for k, p in (raw.get("maps") or [])],
        cross_check=cross_check,
        paths=_resolve_paths(raw.get("paths"), base),
        events=events,
        chains=chains,
    )

    valid_keys = {s.key for s in scenes} | {"comb"}
    for k, _png in data.maps:
        if k not in valid_keys:
            raise DataError("maps: key %r is neither a scene key nor 'comb'" % k)
    if not scenes:
        raise DataError("scenes: at least one scene is required")

    data.scene_by_key = {s.key: s for s in scenes}
    data.event_by_key = {e["key"]: e for e in events}
    data.keys = [s.key for s in scenes] + ["comb"]
    limit = constants["limit"]
    data.limits = {s.key: limit + s.win - constants["overhead"] for s in scenes}
    data.limits["comb"] = limit
    off = constants["offscreen_factor"]
    data.caps = {k: v * off for k, v in data.limits.items()}

    data.frontier = [t for t in towns if t.tier == "frontier"]
    data.reference = [t for t in towns if t.tier == "reference"]
    data.town_by_name = town_by_name

    data.scene_ids = {s.key: "S%d" % (i + 1) for i, s in enumerate(scenes)}
    order = sorted(data.frontier, key=lambda t: t.name) \
        + sorted(data.reference, key=lambda t: t.name)
    data.town_ids = {t.name: i + 1 for i, t in enumerate(order)}
    data.suspect_ids = {s.label: chr(ord("A") + i)
                        for i, s in enumerate(suspects)}
    return data
