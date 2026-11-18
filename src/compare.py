"""Compare the City Park Boundary polygons against OSM park areas.

Pulls park-like areas from OpenStreetMap (Overpass) within Guelph, then for
each kept City polygon checks whether an OSM area overlaps it. The result is
written to data/gaps.geojson:

  * "missing"     -- no OSM park area overlaps the City polygon (add it to OSM);
  * "mismatch"    -- one overlaps, but its (present) OSM name differs;
  * "unnamed"     -- one overlaps but the OSM area has no name (add one);
  * "placeholder" -- a park the City has not named ("Unnamed Neighbourhood
                     Park") that is any of the above; that string is not a name,
                     so it gets its own category instead of being offered as one.

Beside those, amenities.py adds a feature per park amenity OSM lacks -- lots
without capacity, splash pads, disc golf, permanent restrooms -- from the City's
Park Location and Restrooms layers and a second Overpass query.

Overlap is tested with pure-Python centroid-in-polygon checks (both
directions) after a bounding-box prefilter -- enough for a review tool, no GIS
dependency. A flaky Overpass falls back to the cached response, but only after
every mirror has been tried several times -- see _load_osm.
"""

import json
import re
import time

import requests
from layerkit.geom import bbox_overlap as _bbox_overlap
from layerkit.geom import point_in_ring as _point_in_ring
from layerkit.geom import relation_outer_loops as _relation_outer_loops
from layerkit import overpass
# Raised by overpass.load_osm; callers and tests name it as compare's.
from layerkit.overpass import OsmUnavailable  # noqa: F401

from src import config, history
from src.slim import is_placeholder


def compare():
    """Build data/gaps.geojson + summary from City vs OSM. Returns the summary."""
    data, osm_date, from_cache = _load_osm()
    rings = _osm_rings(data)
    print(f"OSM park-area rings: {len(rings):,}")
    city = list(_city_features())
    print(f"City polygons:       {len(city):,}")

    gaps, counts = _match(city, rings)
    amenity_gaps, amenity_counts, amenity_stale = _amenities(city)
    _write_gaps(gaps + amenity_gaps)
    from_cache = from_cache or amenity_stale

    summary = {"osm_rings": len(rings), "city": len(city),
               "osm_date": osm_date, "osm_stale": from_cache, **counts,
               **amenity_counts}
    with open(config.GAPS_COUNT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(
        f"Gaps: {counts['missing']:,} missing, {counts['mismatch']:,} mismatch, "
        f"{counts['unnamed']:,} unnamed OSM, "
        f"{counts['placeholder']:,} placeholder-named"
    )
    if amenity_counts:
        print(
            f"Amenities: {amenity_counts['nocapacity']:,} lots without capacity, "
            f"{amenity_counts['nosplashpad']:,} splash pads, "
            f"{amenity_counts['nodiscgolf']:,} disc golf, "
            f"{amenity_counts['notoilet']:,} permanent restrooms"
        )
    if from_cache:
        print(f"NOTE: compared against cached OSM data from {osm_date}, "
              f"not a live Overpass fetch.")
    history.record(summary)
    return summary


def _amenities(city):
    """(gaps, counts, from_cache) for the park amenity statuses.

    Nothing at all -- no counts, so no history points -- when the City layers
    were never fetched or no mirror answered and there is no cache: a skipped
    check must not read as zero gaps.
    """
    from src import amenities  # here, not at the top: amenities imports compare

    layers = amenities.load_city()
    if layers is None:
        print("Amenities: no Park Location / Restrooms copy in data/; skipped.")
        return [], {}, False
    try:
        data, _osm_date, from_cache = _load_amenity_osm()
    except OsmUnavailable as e:
        print(f"Amenities: skipped ({e}).")
        return [], {}, False
    gaps, counts = amenities.check(city, *layers, data.get("elements", []))
    return gaps, counts, from_cache


# --- OSM source -------------------------------------------------------------

def _overpass_query(at=None):
    """The Overpass QL for park-like areas; ``at`` (ISO instant) asks for OSM
    as it stood then -- an attic query, used by the history backfill."""
    s, w, n, e = config.GUELPH_BBOX
    bbox = f"{s},{w},{n},{e}"
    parts = []
    for key, values in config.OSM_AREA_TAGS.items():
        rx = "|".join(values)
        parts.append(f'  way["{key}"~"^({rx})$"]({bbox});')
        parts.append(f'  relation["{key}"~"^({rx})$"]({bbox});')
    # "out geom" (body verbosity) so RELATIONS carry their members + geometry;
    # "out tags geom" would strip member lists and silently drop every relation.
    settings = "[out:json][timeout:180]"
    if at:
        settings += f'[date:"{at}"]'
    return settings + ";\n(\n" + "\n".join(parts) + "\n);\nout geom;"


def _amenity_query():
    """The Overpass QL for the park amenities: lots, toilets, splash pads, disc
    golf. Centres only -- every check is a point against a polygon."""
    s, w, n, e = config.GUELPH_BBOX
    bbox = f"({s},{w},{n},{e})"
    parts = [f"  {sel}{bbox};" for sel in config.OSM_AMENITY_SELECTORS]
    return "[out:json][timeout:180];\n(\n" + "\n".join(parts) + "\n);\nout center;"


def _load_amenity_osm():
    return _load_osm(_amenity_query(), config.OSM_AMENITY_CACHE_PATH,
                     config.OSM_AMENITY_FETCH_PATH,
                     config.OSM_AMENITY_MIN_ELEMENTS, "park amenities")


def _load_osm(query=None, cache_path=None, fetch_path=None, min_elements=None,
              what="park areas"):
    """Return (data, osm_date, from_cache) for OSM park areas.

    The arguments default to the park-area query and its cache; the amenity
    query passes its own (see _load_amenity_osm), so the two caches never mix.

    The fetch -- every mirror, the list retried, then the cache -- is
    layerkit.overpass.load_osm; the reasons for each rule are written there.
    """
    return overpass.load_osm(
        query or _overpass_query(), what=what,
        urls=config.OVERPASS_URLS, rounds=config.OVERPASS_ROUNDS,
        round_wait=config.OVERPASS_ROUND_WAIT,
        cache_path=cache_path or config.OSM_CACHE_PATH,
        fetch_path=fetch_path or config.OSM_FETCH_PATH,
        try_one=lambda url, q: _try_overpass(url, q, min_elements),
        undated=None)


def _try_overpass(url, query, min_elements=None):
    """One attempt at one mirror; None if it failed or answered implausibly."""
    if min_elements is None:
        min_elements = config.OSM_MIN_ELEMENTS
    return overpass.try_overpass(
        url, query, user_agent=config.USER_AGENT,
        timeout=config.OVERPASS_TIMEOUT,
        min_elements=min_elements,
        max_age_days=config.OSM_MAX_AGE_DAYS)


def _load_cache(cache_path=None, fetch_path=None):
    """(data, osm_date) for the cached Overpass reply, or None."""
    return overpass.load_cache(cache_path or config.OSM_CACHE_PATH,
                               fetch_path or config.OSM_FETCH_PATH)


def _osm_base(data):
    """How current the OSM half of the diff is: the reply's own
    osm3s.timestamp_osm_base, trimmed to the minute for display."""
    return overpass.osm_base(data, undated=None)


def _osm_base_time(data):
    """The same timestamp as an aware datetime, or None if absent or garbled."""
    return overpass.osm_base_time(data)


def _cache_date(cache_path=None, fetch_path=None):
    """How current the cached reply is: the sidecar, else the file's mtime."""
    return overpass.cache_date(cache_path or config.OSM_CACHE_PATH,
                               fetch_path or config.OSM_FETCH_PATH)


def _save_fetch(fetched, url, osm_base, data, fetch_path):
    overpass.save_fetch(fetch_path, fetched, url, osm_base, data)


def _osm_rings(data):
    """Flatten OSM ways and relation outer members into matchable rings."""
    rings = []
    for el in data.get("elements", []):
        name = (el.get("tags") or {}).get("name")
        if el.get("type") == "way":
            rings.append(_make_ring(el.get("geometry"), name, "way", el["id"]))
        elif el.get("type") == "relation":
            for loop in _relation_outer_loops(el):
                rings.append(_make_ring(loop, name, "relation", el["id"]))
    return [r for r in rings if r]


def _make_ring(geom, name, otype, oid):
    if not geom:
        return None
    pts = [(p["lon"], p["lat"]) for p in geom if "lon" in p and "lat" in p]
    if len(pts) < 3:
        return None
    return {
        "pts": pts,
        "name": name,
        "otype": otype,
        "oid": oid,
        "bbox": _bbox(pts),
        "centroid": _centroid(pts),
    }


# --- City source ------------------------------------------------------------

def _city_features():
    with open(config.SLIM_PATH, encoding="utf-8") as f:
        for line in f:
            feat = json.loads(line)
            outers = _outer_rings(feat["geometry"])
            if not outers:
                continue
            allpts = [p for ring in outers for p in ring]
            props = feat.get("properties") or {}
            yield {
                "name": props.get("name"),
                "address": props.get("address"),
                "objectid": props.get("objectid"),
                "geom": feat["geometry"],
                "outers": outers,
                "bbox": _bbox(allpts),
                "centroid": _centroid(max(outers, key=_ring_area)),
            }


def _outer_rings(geom):
    """Outer ring(s) as lists of (lon, lat). Polygon -> 1, MultiPolygon -> many."""
    coords = geom.get("coordinates")
    if not coords:
        return []
    if geom["type"] == "Polygon":
        return [[tuple(p) for p in coords[0]]]
    if geom["type"] == "MultiPolygon":
        return [[tuple(p) for p in poly[0]] for poly in coords if poly]
    return []


# --- Matching ---------------------------------------------------------------

def _match(city, rings):
    gaps = []
    counts = {"missing": 0, "mismatch": 0, "unnamed": 0, "placeholder": 0}
    for c in city:
        match = _find_match(c, rings)
        if match is None:
            status = "missing"
        elif not match["name"]:
            status = "unnamed"
        elif _norm(match["name"]) != _norm(c["name"]):
            status = "mismatch"
        else:
            continue  # an OSM area with the same name overlaps -- not a gap
        if is_placeholder(c["name"]):
            status = "placeholder"
        gaps.append(_gap_feature(c, status, match))
        counts[status] += 1
    return gaps, counts


def _find_match(c, rings):
    """An OSM ring overlapping the City polygon, preferring a same-named one."""
    cnorm = _norm(c["name"])
    best = None
    name_fallback = None
    for r in rings:
        if not _bbox_overlap(c["bbox"], r["bbox"]):
            continue
        same_name = bool(cnorm) and _norm(r["name"]) == cnorm
        if _point_in_ring(c["centroid"], r["pts"]) or any(
            _point_in_ring(r["centroid"], outer) for outer in c["outers"]
        ):
            if same_name:
                return r  # exact name match settles it
            if best is None or (r["name"] and not best["name"]):
                best = r  # otherwise prefer a named ring over an unnamed one
        elif same_name and name_fallback is None:
            # Centroid tests missed (concave / multipolygon), but a same-named
            # area overlaps this polygon's bbox -- almost certainly the match.
            name_fallback = r
    return best or name_fallback


def _gap_feature(c, status, match):
    props = {
        "name": c["name"],
        "address": c["address"],
        "status": status,
        "objectid": c["objectid"],
    }
    if match:
        props["osm_name"] = match["name"]
        props["osm_url"] = (
            f"https://www.openstreetmap.org/{match['otype']}/{match['oid']}"
        )
    return {
        "type": "Feature",
        "properties": props,
        "geometry": _round_geom(c["geom"]),
    }


def _write_gaps(gaps):
    with open(config.GAPS_GEOJSON_PATH, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": gaps}, f)


# --- Geometry helpers -------------------------------------------------------

def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _centroid(pts):
    """Area-weighted polygon centroid (shoelace); mean for degenerate rings.

    Translated to the first vertex before summing: at lon/lat a small park's
    cross-products are differences of numbers near 3,500, and summed raw they
    lose the centroid to float cancellation.
    """
    n = len(pts)
    ox, oy = pts[0]
    area = cx = cy = 0.0
    for i in range(n):
        x0, y0 = pts[i][0] - ox, pts[i][1] - oy
        x1, y1 = pts[(i + 1) % n][0] - ox, pts[(i + 1) % n][1] - oy
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if area == 0:
        return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)
    area *= 0.5
    return (cx / (6 * area) + ox, cy / (6 * area) + oy)


def _ring_area(pts):
    n = len(pts)
    area = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return abs(area) / 2


# Generic feature words the City and OSM disagree on appending ("Trafalgar
# Square" vs "Trafalgar Square Park", "Woodlawn Cemetery" vs "... Cemetery and
# Crematorium"). Deliberately short: Guelph's real name variants are things like
# "Bathgate Drive Park" against OSM's "Bathgate Park", and normalising those
# away would hide exactly the work item the gap page exists to show.
_GENERIC_SUFFIX = re.compile(r"\s+(?:and\s+)?(?:park|cemetery|crematorium|club)$")


def _norm(name):
    """Loose match key: drop the artefacts City and OSM names differ on.

    Lowercases and reduces to single-spaced alphanumerics, unifies "&"/"and",
    drops a leading article, and trims generic trailing feature words -- so
    spatially matched parks aren't flagged as mismatches over naming convention
    alone. Affects matching only; the displayed name keeps the raw City data.
    """
    if not name:
        return ""
    # Delete apostrophes so the City's "Oconnor" keys the same as OSM's
    # "O'Connor" (rather than splitting into a stray "s" or "connor" token).
    s = name.lower().replace("&", " and ").replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"^the\s+", "", s)
    while True:
        trimmed = _GENERIC_SUFFIX.sub("", s).strip()
        if trimmed == s:
            return s
        s = trimmed or s  # keep the last word if the name is only generic words


def _round_geom(geom):
    return {"type": geom["type"], "coordinates": _round(geom["coordinates"])}


def _round(c):
    if isinstance(c, (int, float)):
        return round(c, 5)  # ~1 m -- ample for a reference outline, smaller file
    return [_round(x) for x in c]
