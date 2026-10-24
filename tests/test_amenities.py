"""The park amenity statuses: what counts as mapped, and what is a gap.

Each test is one of the traps the 2026-10-09 recalibration and the first run
turned up: a neighbour's lot crediting a park, a splash pad mapped under some
other tag, a City restroom point tens of metres off the building OSM maps, a
restroom the City files under the wrong park, and a check that did not run
being read as zero gaps.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import amenities, compare, config, history, site  # noqa: E402

# A park roughly 800 m by 1.1 km; one degree of longitude here is ~80,700 m.
SQUARE = [(-80.25, 43.54), (-80.24, 43.54), (-80.24, 43.55), (-80.25, 43.55)]
INSIDE = (-80.245, 43.545)
EAST_EDGE = -80.24
M_LON = 1 / 80700.0     # one metre east, in degrees


def _east(metres, lat=43.545):
    """A point ``metres`` east of the park's east edge."""
    return (EAST_EDGE + metres * M_LON, lat)


def _park(name="Test Park"):
    return {"name": name, "address": "1 Test Street", "objectid": 7,
            "geom": {"type": "Polygon", "coordinates": [list(map(list, SQUARE))]},
            "outers": [SQUARE], "bbox": compare._bbox(SQUARE),
            "centroid": compare._centroid(SQUARE)}


def _row(name="Test Park", **flags):
    props = {"Name": name, "NumParking": 0, "SplashPad": "NO", "DiscGolf": "NO",
             "Restroom": "NO", **flags}
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Point", "coordinates": list(INSIDE)}}


def _restroom(pt, kind="PERMANENT RESTROOM", park="TEST PARK", rid=1):
    return {"type": "Feature",
            "properties": {"RestroomType": kind, "ParkName": park, "Status": "IN-USE",
                           "RestroomID": rid, "LocationDescription": None},
            "geometry": {"type": "Point", "coordinates": list(pt)}}


_ids = iter(range(1, 10_000))


def _osm(pt, **tags):
    """An Overpass element as ``out center`` returns a way."""
    return {"type": "way", "id": next(_ids), "tags": tags,
            "center": {"lon": pt[0], "lat": pt[1]}}


def _check(rows, elements, restrooms=(), city=None):
    return amenities.check(city or [_park()], list(rows), list(restrooms), elements)


def _statuses(gaps):
    return [g["properties"]["status"] for g in gaps]


# --- parking ----------------------------------------------------------------

def test_a_bare_lot_in_the_park_is_a_capacity_gap_pointing_at_the_lot():
    lot = _osm(INSIDE, amenity="parking")
    gaps, counts = _check([_row(NumParking=40)], [lot])
    assert counts["nocapacity"] == 1
    p = gaps[0]["properties"]
    assert p["osm_url"].endswith(f"/way/{lot['id']}")
    assert p["point"] == [round(INSIDE[0], 5), round(INSIDE[1], 5)]
    assert "40 stalls" in p["detail"]


def test_a_lot_with_capacity_settles_it():
    gaps, _ = _check([_row(NumParking=40)], [_osm(INSIDE, amenity="parking", capacity="38")])
    assert gaps == []


def test_a_neighbours_lot_on_the_fringe_does_not_credit_the_parks_own():
    # Riverside: nine bare lots of its own, and a private 5-stall lot 14 m out.
    elements = [_osm(INSIDE, amenity="parking"),
                _osm(_east(15), amenity="parking", capacity="5", access="private")]
    gaps, _ = _check([_row(NumParking=145)], elements)
    assert _statuses(gaps) == ["nocapacity"]


def test_the_fringe_counts_when_the_park_has_no_lot_of_its_own():
    gaps, _ = _check([_row(NumParking=51)], [_osm(_east(15), amenity="parking", capacity="51")])
    assert gaps == []
    gaps, _ = _check([_row(NumParking=51)], [_osm(_east(15), amenity="parking")])
    assert _statuses(gaps) == ["nocapacity"]


def test_a_lot_beyond_the_fringe_is_not_the_parks():
    gaps, _ = _check([_row(NumParking=20)], [_osm(_east(40), amenity="parking", capacity="20")])
    assert _statuses(gaps) == ["nocapacity"]
    assert "no OSM lot" in gaps[0]["properties"]["detail"]
    assert "osm_url" not in gaps[0]["properties"]


def test_a_park_without_parking_asks_nothing():
    gaps, counts = _check([_row()], [])
    assert gaps == [] and counts["nocapacity"] == 0


# --- splash pads and disc golf ----------------------------------------------

def test_a_splash_pad_counts_under_any_tag_guelph_uses_for_one():
    for tags in ({"leisure": "splash_pad"}, {"playground": "splash_pad"},
                 {"fountain": "splash_pad"},
                 {"leisure": "swimming_pool", "name": "Hanlon Park Creek Splash Pad"}):
        gaps, _ = _check([_row(SplashPad="YES")], [_osm(INSIDE, **tags)])
        assert gaps == [], tags


def test_a_listed_splash_pad_with_none_in_the_park_is_a_gap():
    gaps, counts = _check([_row(SplashPad="YES")],
                          [_osm(_east(40), playground="splash_pad"),
                           _osm(INSIDE, leisure="playground")])
    assert _statuses(gaps) == ["nosplashpad"] and counts["nosplashpad"] == 1


def test_disc_golf_by_course_or_by_sport():
    assert _check([_row(DiscGolf="YES")], [_osm(INSIDE, leisure="disc_golf_course")])[0] == []
    assert _check([_row(DiscGolf="YES")], [_osm(INSIDE, sport="disc_golf")])[0] == []
    gaps, _ = _check([_row(DiscGolf="YES")], [])
    assert _statuses(gaps) == ["nodiscgolf"]


def test_a_flag_set_to_no_is_never_a_gap():
    assert _check([_row(SplashPad="NO", DiscGolf="NO")], [])[0] == []


# --- restrooms --------------------------------------------------------------

def test_a_permanent_restroom_with_no_toilet_anywhere_near_is_a_gap():
    gaps, counts = _check([_row()], [], restrooms=[_restroom(INSIDE)])
    assert _statuses(gaps) == ["notoilet"] and counts["notoilet"] == 1


def test_portables_are_left_out():
    gaps, _ = _check([_row()], [], restrooms=[_restroom(INSIDE, kind="PORTABLE RESTROOM")])
    assert gaps == []


def test_a_toilet_anywhere_in_the_same_park_answers_for_it():
    far_inside = (-80.249, 43.549)   # ~500 m from INSIDE, still in the park
    gaps, _ = _check([_row()], [_osm(far_inside, amenity="toilets")],
                     restrooms=[_restroom(INSIDE)])
    assert gaps == []


def test_a_toilet_just_outside_the_park_answers_within_the_radius():
    # Margaret Greene: the City point sits 62 m from the building OSM maps.
    room = _east(-10)
    gaps, _ = _check([_row()], [_osm(_east(60), amenity="toilets")],
                     restrooms=[_restroom(room)])
    assert gaps == []
    gaps, _ = _check([_row()], [_osm(_east(150), amenity="toilets")],
                     restrooms=[_restroom(room)])
    assert _statuses(gaps) == ["notoilet"]
    assert "nearest OSM toilets 1" in gaps[0]["properties"]["detail"]


def test_one_osm_toilet_answers_for_one_restroom():
    # Exhibition Park: three City restrooms, two OSM toilets -> one gap.
    rooms = [_restroom(INSIDE, rid=1), _restroom((-80.246, 43.546), rid=2),
             _restroom((-80.244, 43.544), rid=3)]
    toilets = [_osm(INSIDE, amenity="toilets"), _osm((-80.246, 43.546), amenity="toilets")]
    gaps, _ = _check([_row()], toilets, restrooms=rooms)
    assert _statuses(gaps) == ["notoilet"]
    assert "restroom 3" in gaps[0]["properties"]["detail"]


def test_a_restroom_is_filed_under_the_park_it_stands_in():
    # Restroom 54 is listed under Eramosa River Park but stands in Lyon Park.
    gaps, _ = _check([_row("Lyon Park")], [],
                     restrooms=[_restroom(INSIDE, park="ERAMOSA RIVER PARK")],
                     city=[_park("Lyon Park")])
    p = gaps[0]["properties"]
    assert p["name"] == "Lyon Park"
    assert "ERAMOSA RIVER PARK" in p["detail"]


def test_the_restroom_flag_and_layer_disagreements_are_counted():
    city = [_park("Flagged"), _park("Unflagged")]
    city[1]["outers"] = [[(x + 0.02, y) for x, y in SQUARE]]
    city[1]["bbox"] = compare._bbox(city[1]["outers"][0])
    rows = [_row("Flagged", Restroom="YES"), _row("Unflagged", Restroom="NO")]
    rooms = [_restroom((-80.225, 43.545), kind="PORTABLE RESTROOM")]  # in Unflagged
    _gaps, counts = _check(rows, [], restrooms=rooms, city=city)
    assert counts["restroom_flag_unbacked"] == 1
    assert counts["restroom_flag_unlisted"] == 1


# --- joining and plumbing ---------------------------------------------------

def test_a_park_location_row_with_no_polygon_is_skipped_not_fatal():
    gaps, _ = _check([_row("Nowhere Park", SplashPad="YES"), _row(DiscGolf="YES")], [])
    assert _statuses(gaps) == ["nodiscgolf"]


def test_names_join_through_the_loose_key():
    gaps, _ = _check([_row("O'connor Lane Park", DiscGolf="YES")], [],
                     city=[_park("Oconnor Lane Park")])
    assert gaps[0]["properties"]["name"] == "Oconnor Lane Park"


def test_the_amenity_query_asks_for_centres_inside_guelph():
    q = compare._amenity_query()
    assert q.rstrip().endswith("out center;")
    assert q.count("(43.46,-80.34,43.6,-80.14)") == len(config.OSM_AMENITY_SELECTORS)


def test_without_the_city_layers_the_amenity_check_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PARK_LOCATION_PATH", str(tmp_path / "none.geojson"))
    assert compare._amenities([_park()]) == ([], {}, False)


# --- what the record and the reader see -------------------------------------

def test_a_skipped_check_is_absent_from_history_not_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "HISTORY_PATH", str(tmp_path / "history.jsonl"))
    monkeypatch.setattr(history, "seed", lambda: False)
    base = {"missing": 13, "city": 126, "osm_stale": False}
    history.record(base, day="2026-10-20")
    history.record({**base, "nocapacity": 23, "notoilet": 3}, day="2026-10-24")
    old, new = history.load()
    assert "nocapacity" not in old
    assert new["nocapacity"] == 23 and new["notoilet"] == 3
    assert "<td>&ndash;</td>" in site._history_row(old)
    assert "<td>23</td>" in site._history_row(new)


def test_the_page_states_the_citys_restroom_contradiction():
    note = site._amenity_note({"notoilet": 3, "restroom_flag_unbacked": 17,
                               "restroom_flag_unlisted": 3})
    assert "<strong>17</strong>" in note and "<strong>3</strong>" in note
    assert "guelph-gardens-layer" in note
    assert "skipped" in site._amenity_note({})
