"""Cached Esri WorldStreetMap basemap for the map extent (optional layer)."""
import json
import os

import numpy as np

from . import geo, settings


def get_basemap(log, data, cache_dir, enabled=True, fetch=True):
    """(image, mercator_extent) or (None, None); disk-cached per bbox+zoom."""
    from matplotlib import image as mpimg

    png = os.path.join(cache_dir, "basemap.png")
    meta_path = os.path.join(cache_dir, "basemap_meta.json")
    meta = None
    if os.path.exists(meta_path) and os.path.exists(png):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            meta = None
    ok = (meta is not None
          and meta.get("bbox") == list(data.constants["bbox"])
          and meta.get("zoom") == data.constants["zoom"])
    if ok:
        log("  basemap: cache hit (%s)" % meta.get("source", "?"))
        return mpimg.imread(png), [float(x) for x in meta["extent"]]
    if not (enabled and fetch):
        log("  basemap: not available (disabled, no cache)")
        return None, None
    w, e, s, n = geo.bbox_extent(data.constants["bbox"])
    try:
        import contextily as ctx
        import contextily.tile as ctx_tile
        ctx_tile.USER_AGENT = settings.USER_AGENT
        img, ext = ctx_tile.bounds2img(
            w, s, e, n, zoom=data.constants["zoom"],
            source=ctx.providers.Esri.WorldStreetMap, use_cache=True)
        ext = [float(x) for x in ext]
        arr = img
        if arr.dtype != np.uint8:
            arr = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
        from PIL import Image
        os.makedirs(cache_dir, exist_ok=True)
        Image.fromarray(arr).save(png)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"bbox": list(data.constants["bbox"]),
                       "zoom": data.constants["zoom"],
                       "source": "Esri.WorldStreetMap", "extent": ext}, f)
        log("  basemap: fetched Esri.WorldStreetMap zoom=%d and cached"
            % data.constants["zoom"])
        return mpimg.imread(png), ext
    except Exception as exc:
        log("  basemap unavailable (%s); field on white" % exc)
        return None, None
