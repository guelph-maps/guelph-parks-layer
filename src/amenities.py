"""Check what the City says is in each park against what OSM maps there.

The City's Park Location layer (OpenData1/19) is Park Boundary again as
centroid points -- same 126 parks, same names -- plus a stall count and YES/NO
amenity flags. Each row is joined to its park polygon by name, and OSM is
looked for inside the polygon (plus AMENITY_FRINGE_M). Four statuses come out,
one gap feature per (park, status), beside the name statuses compare.py makes:

  * "nocapacity"  -- the City gives the park NumParking stalls and no OSM lot in
                     it carries ``capacity``. Lots inside the polygon are
                     preferred over the fringe, which can reach a neighbour's;
  * "nosplashpad" -- SplashPad=YES and OSM has no splash pad in the park, under
                     any of the tags Guelph's mappers have used for one;
  * "nodiscgolf"  -- DiscGolf=YES and no disc golf course;
  * "notoilet"    -- a PERMANENT restroom from the Restrooms layer (OpenData1/20)
                     with no amenity=toilets matched to it.

Toilets come from the Restrooms layer, not Park Location's Restroom flag: the
two disagree in about twenty parks, mostly YES with no restroom in the other
layer (portables, seasonal or gone). The disagreement is counted and shown on
the page rather than resolved. Portables are left out: they come and go with
the season, and a weekly worklist of them would be noise.

Left out on purpose: the picnic flag (the gap is OSM not mapping picnic tables,
not missing parks), playgrounds (93 of 94 already mapped), the pitch flags
(guelph-pitches-beholder covers them) and community gardens
(guelph-gardens-layer covers them, with the City's own garden roster).
"""

import json
import math
import os
import re

from src import compare, config

STATUSES = ("nocapacity", "nosplashpad", "nodiscgolf", "notoilet")

_SPLASH_NAME = re.compile(r"splash|spray", re.I)


def load_city():
    """(Park Location rows, Restrooms rows), or None when either is absent."""
    layers = []
    for path in (config.PARK_LOCATION_PATH, config.RESTROOMS_PATH):
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as f:
            layers.append(json.load(f).get("features") or [])
    return tuple(layers)


def check(city, parkloc, restrooms, elements):
    """Amenity gap features and counts for the City parks ``city``.

    ``city`` is compare._city_features() output, ``parkloc`` and ``restrooms``
    the two City layers' GeoJSON features, ``elements`` the amenity Overpass
    reply's elements. Returns (gaps, counts).
    """
    osm = [(_osm_point(e), e.get("tags") or {}) for e in elements]
    osm = [(pt, tags, e) for (pt, tags), e in zip(osm, elements) if pt]
    lots = [o for o in osm if o[1].get("amenity") == "parking"]
    toilets = [o for o in osm if o[1].get("amenity") == "toilets"]
    splash = [o for o in osm if _is_splash_pad(o[1])]
    discgolf = [o for o in osm if _is_disc_golf(o[1])]

    gaps = []
    counts = {s: 0 for s in STATUSES}
    for row, park in _join(parkloc, city):
        p = row["properties"]
        at = _point(row["geometry"]) or park["centroid"]
        if (p.get("NumParking") or 0) > 0:
            gap = _parking_gap(park, at, p["NumParking"], lots)
            if gap:
                gaps.append(gap)
        if p.get("SplashPad") == "YES" and not _any_in(park, splash):
            gaps.append(_feature(park, "nosplashpad", at, "City lists a splash pad"))
        if p.get("DiscGolf") == "YES" and not _any_in(park, discgolf):
            gaps.append(_feature(park, "nodiscgolf", at,
                                 "City lists a disc golf course"))

    gaps += _toilet_gaps(city, restrooms, toilets)
    for g in gaps:
        counts[g["properties"]["status"]] += 1
    counts.update(_restroom_flag_conflicts(parkloc, restrooms, city))
    return gaps, counts


# --- Joining the City layers ------------------------------------------------

def _join(parkloc, city):
    """Pair each Park Location row with its Park Boundary polygon, by name."""
    by_name = {}
    for c in city:
        by_name.setdefault(c["name"], c)
        by_name.setdefault(compare._norm(c["name"]), c)
    for row in parkloc:
        name = (row.get("properties") or {}).get("Name")
        park = by_name.get(name) or by_name.get(compare._norm(name))
        if park is None:
            print(f"  Park Location {name!r} has no Park Boundary polygon; skipped.")
            continue
        yield row, park


def _park_of(pt, city):
    """The City park a point falls in (or within the fringe of), else None."""
    best = None
    for c in city:
        if not _in_bbox(pt, c["bbox"], config.AMENITY_FRINGE_M):
            continue
        d = _dist_to_park(pt, c)
        if d <= config.AMENITY_FRINGE_M and (best is None or d < best[0]):
            best = (d, c)
    return best[1] if best else None


# --- Parking ----------------------------------------------------------------

def _parking_gap(park, at, stalls, lots):
    """A nocapacity feature for ``park``, or None when a lot carries capacity.

    Lots whose centre is inside the polygon are the park's; only when there
    are none does the fringe count. Without that order Riverside, with nine
    bare lots of its own, would be credited by a neighbour's private 5-stall
    lot 14 m outside it.
    """
    near = [(pt, tags, e) for pt, tags, e in lots
            if _in_bbox(pt, park["bbox"], config.AMENITY_FRINGE_M)]
    inside = [o for o in near if _dist_to_park(o[0], park) == 0]
    mine = inside or [o for o in near
                      if _dist_to_park(o[0], park) <= config.AMENITY_FRINGE_M]
    if any(tags.get("capacity") for _pt, tags, _e in mine):
        return None
    if not mine:
        return _feature(park, "nocapacity", at,
                        f"City: {stalls:,} stalls; no OSM lot in or beside the park")
    pt, tags, e = min(mine, key=lambda o: _metres(o[0], at))
    n = len(mine)
    lots_text = "1 OSM lot" if n == 1 else f"{n} OSM lots"
    return _feature(park, "nocapacity", pt,
                    f"City: {stalls:,} stalls; {lots_text}, none with capacity",
                    osm=e)


# --- Splash pads and disc golf ----------------------------------------------

def _is_splash_pad(tags):
    return (tags.get("leisure") in ("splash_pad", "water_park")
            or tags.get("playground") == "splash_pad"
            or tags.get("fountain") == "splash_pad"
            or bool(_SPLASH_NAME.search(tags.get("name") or "")))


def _is_disc_golf(tags):
    return (tags.get("leisure") == "disc_golf_course"
            or "disc_golf" in (tags.get("sport") or ""))


def _any_in(park, features):
    return any(_in_bbox(pt, park["bbox"], config.AMENITY_FRINGE_M)
               and _dist_to_park(pt, park) <= config.AMENITY_FRINGE_M
               for pt, _tags, _e in features)


# --- Toilets ----------------------------------------------------------------

def _toilet_gaps(city, restrooms, toilets):
    """notoilet features for permanent City restrooms OSM has no toilet for.

    One OSM toilet answers for at most one City restroom, nearest pairs first,
    and it may be anywhere within TOILET_RADIUS_M of the City point or anywhere
    in the same park: Exhibition Park has three permanent restrooms, OSM two
    toilets, and that is one gap, whichever building it turns out to be.
    """
    rooms = []
    for r in restrooms:
        p = r.get("properties") or {}
        pt = _point(r.get("geometry"))
        if not pt or "PERMANENT" not in (p.get("RestroomType") or "").upper():
            continue
        if p.get("Status") not in (None, "IN-USE"):
            continue
        rooms.append((pt, p, _park_of(pt, city)))

    pairs = []
    for i, (pt, _p, park) in enumerate(rooms):
        for j, (tpt, _tags, _e) in enumerate(toilets):
            d = _metres(pt, tpt)
            same_park = (park is not None
                         and _in_bbox(tpt, park["bbox"], config.AMENITY_FRINGE_M)
                         and _dist_to_park(tpt, park) <= config.AMENITY_FRINGE_M)
            if d <= config.TOILET_RADIUS_M or same_park:
                pairs.append((d, i, j))
    used_room, used_toilet = set(), set()
    for _d, i, j in sorted(pairs):
        if i in used_room or j in used_toilet:
            continue
        used_room.add(i)
        used_toilet.add(j)

    gaps = []
    for i, (pt, p, park) in enumerate(rooms):
        if i in used_room:
            continue
        listed = p.get("ParkName") or "no park"
        where = p.get("LocationDescription")
        detail = f"Permanent restroom {p.get('RestroomID')}, City lists it under {listed}"
        if where and where.strip():
            detail += f" ({where.strip()})"
        if toilets:
            nearest = min(_metres(pt, t[0]) for t in toilets)
            detail += f"; nearest OSM toilets {nearest:,.0f} m"
        if park is None:
            park = {"name": listed.title(), "address": None, "objectid": None,
                    "geom": {"type": "Point", "coordinates": list(pt)}}
        gaps.append(_feature(park, "notoilet", pt, detail))
    return gaps


def _restroom_flag_conflicts(parkloc, restrooms, city):
    """How often Park Location's Restroom flag disagrees with the Restrooms layer.

    ``restroom_flag_unbacked``: flag YES, no restroom of either kind in the park.
    ``restroom_flag_unlisted``: flag NO, yet the Restrooms layer has one there.
    """
    points = [pt for pt in (_point(r.get("geometry")) for r in restrooms) if pt]
    unbacked = unlisted = 0
    for row, park in _join(parkloc, city):
        flag = (row.get("properties") or {}).get("Restroom")
        has = any(_in_bbox(pt, park["bbox"], config.AMENITY_FRINGE_M)
                  and _dist_to_park(pt, park) <= config.AMENITY_FRINGE_M
                  for pt in points)
        unbacked += flag == "YES" and not has
        unlisted += flag == "NO" and has
    return {"restroom_flag_unbacked": unbacked, "restroom_flag_unlisted": unlisted}


# --- Features and geometry --------------------------------------------------

def _feature(park, status, point, detail, osm=None):
    """A gap feature: the park polygon to outline, ``point`` for the marker."""
    props = {
        "name": park["name"],
        "address": park["address"],
        "status": status,
        "objectid": park["objectid"],
        "detail": detail,
        "point": [round(point[0], 5), round(point[1], 5)],
    }
    if osm is not None:
        props["osm_name"] = (osm.get("tags") or {}).get("name")
        props["osm_url"] = f"https://www.openstreetmap.org/{osm['type']}/{osm['id']}"
    return {"type": "Feature", "properties": props,
            "geometry": compare._round_geom(park["geom"])}


def _osm_point(e):
    """(lon, lat) of an Overpass element: a node's position, else its centre."""
    if "lat" in e and "lon" in e:
        return (e["lon"], e["lat"])
    c = e.get("center")
    if c and "lat" in c and "lon" in c:
        return (c["lon"], c["lat"])
    return None


def _point(geom):
    if geom and geom.get("type") == "Point" and geom.get("coordinates"):
        return tuple(geom["coordinates"][:2])
    return None


def _metres(a, b):
    """Distance between two (lon, lat) points; equirectangular, ample at park scale."""
    kx = 111320.0 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * 110540.0)


def _in_bbox(pt, bbox, metres):
    """Cheap prefilter: is ``pt`` within ``metres`` of the bbox (lon, lat)?"""
    dy = metres / 110540.0
    dx = metres / (111320.0 * math.cos(math.radians(pt[1])))
    return (bbox[0] - dx <= pt[0] <= bbox[2] + dx
            and bbox[1] - dy <= pt[1] <= bbox[3] + dy)


def _dist_to_park(pt, park):
    """0 inside the park's polygon, else metres to its nearest outer edge."""
    if any(compare._point_in_ring(pt, outer) for outer in park["outers"]):
        return 0.0
    kx = 111320.0 * math.cos(math.radians(pt[1]))
    ky = 110540.0

    def xy(p):
        return ((p[0] - pt[0]) * kx, (p[1] - pt[1]) * ky)

    best = math.inf
    for outer in park["outers"]:
        for a, b in zip(outer, outer[1:] + outer[:1]):
            best = min(best, _seg_dist(xy(a), xy(b)))
    return best


def _seg_dist(a, b):
    """Distance from the origin to segment ab."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = dx * dx + dy * dy
    t = 0.0 if span == 0 else max(0.0, min(1.0, -(a[0] * dx + a[1] * dy) / span))
    return math.hypot(a[0] + t * dx, a[1] + t * dy)
