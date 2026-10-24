# Guelph Parks Layer

Turns the City of Guelph [Park Boundary](https://gismaps.guelph.ca/hosting/rest/services/OpenData/OpenData1/FeatureServer/5)
layer (126 park polygons) into map-tile layers that OpenStreetMap mappers can
add to the **JOSM** and **iD** editors as a reference overlay.

**Live layer and how to add it: https://guelph-maps.github.io/guelph-parks-layer/**

Part of the [guelph-maps](https://github.com/guelph-maps) organisation, which
indexes every Guelph project. Its sibling layer is
[guelph-address-layer](https://github.com/guelph-maps/guelph-address-layer)
([live](https://guelph-maps.github.io/guelph-address-layer/)): the City's
address points, rendered as house-number labels, from the same organisation.

It is a sibling of
[toronto-parks-layer](https://github.com/skfd/toronto-parks-layer), which is the
template this was cloned from: the same `download -> slim -> compare -> vector
-> raster -> site -> publish` pipeline, pointed at Guelph's park boundaries.
A person who knows one project knows the other; the only step that differs in
substance is `download`, because Guelph publishes an ArcGIS FeatureServer where
Toronto publishes a static file on CKAN.

The audit behind it is
[`guelph-osm-import-audit`](https://github.com/guelph-maps/guelph-osm-import-audit)
(private), `findings/parks-recreation.md`,
which tiered this layer **4 / conflate**: OSM already has the parks, what the
City has that OSM lacks is the **official current names** — including the
Anishinaabemowin renaming *Mkinaak Donjibaa Park* — plus a handful of genuinely
absent polygons. That is a gap page, not an import.
[guelph-pitches-beholder](https://github.com/guelph-maps/guelph-pitches-beholder)
tracks the courts and sports fields inside these same parks against OSM —
the same audit finding, tiered 4 / conflate.

## What it produces

- **Vector tiles** (MVT) &mdash; interactive in iD; click a polygon to read its
  `name`, `address` and `objectid` tags.
- **Raster tiles** (PNG) &mdash; translucent green fills with park-name labels;
  each park's outline and label share a stable hashed colour so a name
  overhanging a small polygon is still visually tied to it. A readable backdrop
  for JOSM. A name only renders once the polygon is a visible shape on screen,
  so big parks are labelled from city zoom and small parkettes only when zoomed
  in; at the top raster zoom every named park is labelled.
- A **landing page** with copy-paste "add this layer" instructions for both
  editors.
- A **gap-review page** ([`/gaps/`](https://guelph-maps.github.io/guelph-parks-layer/gaps/))
  that compares the City polygons against park areas already in OpenStreetMap
  and lists the gaps &mdash; City parks with no overlapping OSM area
  ("missing"), matched parks whose OSM name differs ("mismatch"), and matched
  parks whose OSM area carries no name at all ("unnamed") &mdash; on an
  interactive map and a filterable table. OSM areas are pulled from Overpass;
  matching is by spatial overlap (see [`src/compare.py`](src/compare.py)).
  The same page lists the **park amenities** the City records and OSM lacks
  &mdash; see [Park amenities](#park-amenities). Its
  [history page](https://guelph-maps.github.io/guelph-parks-layer/gaps/history.html)
  charts those counts over time, one point per weekly run.

All of it is published to GitHub Pages and rebuilt weekly.

## What is kept

**Every park the City publishes as in use.** Toronto's slim step filters on
`AREA_CLASS`, because its Green Spaces dataset mixes traffic islands, road
slivers, boulevards and hydro corridors in with the parks. Guelph's layer has
no class field, and does not need one: it is parks and nothing else. The
analogous categorical filter here is **`ParkStatus`** (`INCLUDE_PARK_STATUS` in
[`src/config.py`](src/config.py)), which keeps `IN-USE` and drops anything
retired, proposed or planned.

Be clear about what that rule does today: **nothing**. All 126 rows are
`IN-USE`; the City removes a closed park from the extract rather than flagging
it, so the field currently carries no information at all. The rule is written
down anyway, because the day a `RETIRED` or `PROPOSED` value does appear, the
alternative is an overlay telling mappers to add a park that has been
decommissioned or not yet built.

**Names come from `Name`, not `ParkName`.** This is the one trap in the
dataset, and the obvious field is the wrong one. `ParkName` is ALL CAPS
(`LEWIS FARM PARK`); `Name` (service alias "Name of Facility") is the same name
already cased for OSM (`Lewis Farm Park`). So, unlike the Toronto sibling,
there is **no title-casing step here** — see `NAME_KEY` in
[`src/config.py`](src/config.py).

The City's own casing is not perfect, and a mapper should not copy it blindly:
`O'connor Lane Park`, `I.o.d.e. Fountain`, `W.e. Hamilton Park`,
`John Mccrae Memorial Gardens`, `Macalister Park`,
`Priory Park (blacksmith Fntn)`. These are shown as the City publishes them —
the layer is a reference, and inventing a correction would be a worse lie than
showing the wart.

The single polygon named `Unnamed Neighbourhood Park` is kept out of the
rendered tile layer (that is a placeholder, not a name, and an overlay that
draws it invites someone to type it into OSM). The slim step writes it to
`parks-slim.geojsonl` but not to `parks-layer.geojsonl`, so the gap-review page
still tracks it under its own `placeholder` category while the tiles do not.
This is the exact role Toronto's numbered `TRCA LANDS (  n)` parcels play there.

One caution the audit raised and this layer cannot settle: the City's polygon
is the **parcel it owns**, which routinely includes a road allowance, a
stormwater block or a walkway easement nobody would call part of the park.
OSM's existing polygons were traced from imagery and follow the visible edge.
Where the two disagree, OSM's is often the better `leisure=park`. Use this
layer for names and for finding absent parks; do not replace geometry from it
without overlaying a sample first.

## Park amenities

The City publishes the same 126 parks a second time, as
[Park Location](https://gismaps.guelph.ca/hosting/rest/services/OpenData/OpenData1/FeatureServer/19)
(OpenData1/19, same licence): one centroid point per park, names identical to
Park Boundary's 126 of 126, plus `NumParking` and seventeen YES/NO amenity flags.
Its geometry adds nothing, so it is not a layer of its own; its flags are read
for four extra statuses on the gap page, each row joined to its park polygon by
name and OSM looked for inside the polygon plus 20 m
([`src/amenities.py`](src/amenities.py)):

| status | the City says | gap when | first run, 2026-10-24 | on by default |
|---|---|---|--:|---|
| `notoilet` | a **permanent** restroom in the [Restrooms](https://gismaps.guelph.ca/hosting/rest/services/OpenData/OpenData1/FeatureServer/20) layer (OpenData1/20) | no `amenity=toilets` within 100 m of it or anywhere in its park, one OSM toilet per City restroom | 3 | yes |
| `nosplashpad` | `SplashPad=YES` | no splash pad in the park, under any tag Guelph uses for one | 2 | yes |
| `nodiscgolf` | `DiscGolf=YES` | no `leisure=disc_golf_course` or `sport=disc_golf` | 2 | yes |
| `nocapacity` | `NumParking` > 0 | no lot of the park's carries `capacity` | 23 | no |

The three restrooms are Riverside's bandshell, the third of Exhibition Park's
three (OSM has two toilets there), and restroom 54, which the City files under
Eramosa River Park but which stands inside Lyon Park's polygon. Splash pads:
Northview Estates Subdivision and Margaret Greene. Disc golf: Eastview and
Riverside.

Choices worth knowing before changing them:

- **Restrooms come from the Restrooms layer, not Park Location's `Restroom`
  flag.** The two contradict each other: the flag says YES for 17 parks with no
  restroom of either kind in that layer and NO for 3 that have one (counted
  live, and stated on the page). Portables are left out; they are seasonal. The
  City's restroom points sit 60&ndash;80 m off the building OSM maps at Margaret
  Greene, Silvercreek and Hanlon Creek, hence the 100 m radius
  (`TOILET_RADIUS_M`) and the same-park allowance.
- **Lots inside the polygon first.** The 20 m fringe finds the lot at every
  park the City gives parking, but it also reaches the neighbours': Riverside,
  with nine bare lots of its own, would be credited by a private 5-stall lot
  14 m outside it. So a park's lots are those whose
  centre is inside its polygon, and the fringe counts only when there are none.
  `access` is not filtered on: Orin Reid's, South End's and Westminster Woods'
  lots are tagged `private` and are the park's. Goldie Mill and Silvercreek
  already carry `capacity` (35 and 7 + 10 against the City's 39 and 18), so
  they are done, not mismatches; the recalibration's 25 counted a park done only
  when a lot's `capacity` equalled the City number. Lot capacity is **off by default**: the
  City's figure is for the whole park, to be counted from aerial imagery across
  its lots, not copied onto the one the row links to.
- **Splash pads are never `leisure=splash_pad` in Guelph.** Four are
  `playground=splash_pad`, Market Square's is `fountain=splash_pad` (the City
  flags Market Square `SplashPad=NO`; the check only runs City-to-OSM, so that
  disagreement is noted here, not listed), and Hanlon Creek's is a
  `leisure=swimming_pool` named "Hanlon Park Creek Splash Pad"
  ([way 208504883](https://www.openstreetmap.org/way/208504883)), which wants
  retagging by hand. The check accepts all of those, and a name with "splash"
  or "spray" in it.
- **Left out:** the picnic flag (that gap is OSM not mapping picnic tables),
  playgrounds (93 of 94 already in OSM), the pitch flags
  ([guelph-pitches-beholder](https://github.com/guelph-maps/guelph-pitches-beholder)
  covers them) and community gardens
  ([guelph-gardens-layer](https://guelph-maps.github.io/guelph-gardens-layer/gaps/)
  covers them from the City's garden roster; the page links there).

Both City layers are fetched by `download` every run (about 120 KB together)
and simply overwritten. The OSM side is a second Overpass query with its own
cache (`data/osm-amenities.json`) and element floor, so a fallback can never
hand parking lots to the park match; falling back to it marks the run stale
like the park query does. If either City layer has never been fetched, or no
mirror answers and there is no cache, the amenity statuses are skipped &mdash;
their counts show as dashes and are left out of the history row, never
recorded as zero.

## Setup

1. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Set up WSL2 + tippecanoe once &mdash; see [wsl-setup.md](wsl-setup.md).
3. Confirm the GitHub repo in `src/config.py` (`GITHUB_REPO`, `PAGES_URL`).

## Usage

```
python run.py download   # fetch the latest Park Boundary GeoJSON (smart-cached)
python run.py slim       # filter to in-use parks -> slim GeoJSONL
python run.py compare    # diff City polygons against OSM -> data/gaps.geojson
python run.py backfill   # one-off: reconstruct past weeks' gap counts from OSM history
python run.py vector     # build vector (MVT) tiles via WSL tippecanoe
python run.py raster     # build labelled raster (PNG) tiles
python run.py site       # render the landing page (+ the gap-review page)
python run.py publish    # force-push the site to the gh-pages branch

python run.py build      # download + slim + compare + vector + raster + site
python run.py update     # build + publish  (the scheduled entry point)
```

Build output lands in `build/site/`; that directory is what gets published.

## The source, and why `download` is the only rewritten step

Toronto downloads one static GeoJSON from a CKAN package and smart-caches it on
a HEAD request: `Last-Modified` plus `Content-Length` against a small JSON
sidecar. Guelph publishes an **ArcGIS FeatureServer**, and a `/query` response
has neither of those to offer — it is generated the moment you ask, so its
`Last-Modified` is the time of your own request.

So the cache key changes and nothing else does. The query is

```
.../FeatureServer/5/query?where=1%3D1&outFields=*&outSR=4326&f=geojson
```

`outSR=4326` is not optional: the service stores geometry in EPSG:26917 (UTM
17N, metres), and without it every downstream coordinate is nonsense. The body
is ~330 KB, cheap enough to fetch every time, and what is compared is a
**sha256 of the response**. An identical hash means the City has not touched the
layer and the existing dated file is kept — which also keeps the site's "City
data" date meaning *when the data last changed*, exactly as Toronto's
`Last-Modified` filename does.

The output contract is unchanged: one dated GeoJSON FeatureCollection in
`data/`, which is all `slim` and everything after it knows about.

Two ArcGIS-specific checks sit on the response, because this service answers
with HTTP 200 whatever it thinks of your request: a body carrying an `error`
object is refused, and so is one with `exceededTransferLimit` set. The layer's
`maxRecordCount` is 100,000 against 126 rows, so a truncated page cannot happen
today — but a partial extract would report the parks that fell off the end as
missing from OSM, and that is worth stopping the run for rather than quietly
paginating around.

## Tile endpoints

```
https://guelph-maps.github.io/guelph-parks-layer/tiles/vector/{z}/{x}/{y}.pbf   (z10-19)
https://guelph-maps.github.io/guelph-parks-layer/tiles/raster/{z}/{x}/{y}.png   (z13-17)
```

The vector layer name is `parks`.

## Hosting

The tile pyramid is published to an orphan `gh-pages` branch, recreated and
force-pushed on every build so repository history never grows. One-time step:
in the GitHub repo, set **Settings &rarr; Pages &rarr; Source** to the
`gh-pages` branch (root).

## Scheduling (Windows)

Run as Administrator:

```powershell
.\schedule-add.ps1      # registers a weekly task "kk-GuelphParksLayer", Tuesdays 16:30
.\schedule-remove.ps1   # unregisters it
```

Weekly is enough &mdash; 126 park polygons change rarely, and the City's service
carries no edit date to poll anyway; it is the gap page, which diffs against
live OSM, that moves week to week. Tuesday keeps this clear of
`toronto-parks-layer`'s Monday slot, so the two never drive tippecanoe in the
same WSL instance at once.

### The link gate

Both network steps &mdash; the dataset query and the `gh-pages` push &mdash;
run behind `addressvault.net`, the same offline/metered gate the address vault
pulls behind. A dead link is not a build failure: `run.py` exits **75**
(`EX_TEMPFAIL`), nothing is written, and the task's restart-on-failure retries
three times half an hour apart rather than leaving a seven-day gap. It does not
wait the link out, since the task carries a hard `ExecutionTimeLimit` that would
kill a long wait anyway.

### Gap history

Every live comparison appends one line to `data/history.jsonl` -- the date, the
OSM data date, and the missing / mismatch / unnamed / placeholder counts -- and
the site step charts it at [`/gaps/history.html`](https://guelph-maps.github.io/guelph-parks-layer/gaps/history.html),
with the rows published beside it as `gaps/history.jsonl`. That is the whole
record the observer keeps: the tiles and the gap list are rebuilt from scratch
and force-pushed each week, but this file only grows, so the scheduled
`update` extends the chart by one point every Tuesday. A run that fell back to
cached OSM is not recorded; it observed nothing new, and a point it drew would
be a false plateau. A live row's OSM date is the mirror's declared
`timestamp_osm_base`, so a mirror answering with old data shows as such.

Nothing heavier is kept on purpose. OSM keeps its own history, so the record is
reconstructible: `python run.py backfill` asks `overpass-api.de` what OSM looked
like on each past Monday (an attic query, `[date:...]`, which only that
instance is relied on for) and re-runs the comparison against it, adding rows
marked `attic`. It is paced -- one attempt per date, 30 s between dates, and
it stops at the first unanswered query -- because attic queries cost the
instance more than live ones and this is a one-off, not the weekly build. Dates
already on record are skipped, so an interrupted run resumes when re-run.
The default range starts 2026-06-01, the same Monday the Toronto sibling's
chart starts on; `--since`, `--until`, `--every` and `--pause` adjust it.

Two caveats the page states: a reconstructed week is compared against
*today's* City polygons (the City side is not archived; the Park Boundary layer
changes rarely), and the counts follow the City layer, so they move when the
City adds or renames parks, not only when someone maps one.

A checkout without `data/history.jsonl` (a fresh clone, a wiped `data/`) seeds
itself from the published `gaps/history.jsonl` before recording, so the record
survives the machine it was made on.

The amenity counts (`nocapacity`, `nosplashpad`, `nodiscgolf`, `notoilet`) are
recorded from 2026-10-24 on. Earlier rows do not have them, and `backfill` does
not reconstruct them; the chart starts those lines at the first run that took
them, and the legend toggles each line (lot capacity starts hidden).

### Keeping the OSM half fresh

The gap page is only worth acting on if both sides of the diff are current, and
the OSM side is the one that moves daily. Every mirror in `OVERPASS_URLS` is
tried, and the whole list is retried `OVERPASS_ROUNDS` times a minute apart,
because what is being worked around is a loaded instance shedding one request.
A reply with fewer than `OSM_MIN_ELEMENTS` elements is refused however healthy
its status code: a regional instance answers an out-of-region bbox with a
valid, empty result, which taken at face value would report all 126 City parks
as missing from OSM.

`overpass.kumi.systems` is deliberately **not** in the list. It returned 504s
through August 2026 and has since been caught serving months-stale data, which
is the worse of the two failures because it looks exactly like success.
`overpass.private.coffee` was dropped on 2026-09-29 for the same failure: the
Toronto sibling caught it serving OSM from May and July on consecutive days.
That leaves `overpass-api.de` alone, and a reply from any mirror whose data is
more than `OSM_MAX_AGE_DAYS` (3) old is refused like a 504.

The page prints the **OSM database timestamp the mirror declares about its own
reply** (`osm3s.timestamp_osm_base`), not the date of the build — a mirror can
answer in two seconds with data from last week, and printing "today" beside it
would hide precisely that.

If no mirror can be reached, the cache is used &mdash; a stale gap page beats
none &mdash; but the run stops being quiet about it. The page carries a warning
banner beside the OSM date, and `update` exits **70** *after* publishing, so the
tiles still ship and the task's restart-on-failure tries the fetch again in half
an hour instead of in a week. Being offline is told apart from an Overpass
outage and stays a 75.

## Tests

```
python tests\test_tilemath.py
python tests\test_slim.py
pytest                       # the above, plus the download / compare / publish tests
```

## Licence / attribution

Park data is &copy; City of Guelph, published under the
[Open Government Licence &ndash; City of Guelph](https://gismaps.guelph.ca/Images/OpenDataLicenceVersion2.pdf).
The OSMF Licence Working Group approved that licence as `compatible` on
2024-09-09.

**This project redistributes City data** — as published tiles on a public URL —
which the sibling *beholder* products never do, and the licence attaches a
required attribution to that. Both the landing page and the gap page carry,
visibly:

> Contains information licensed under the Open Government Licence – City of Guelph.

linked to the licence text. The same attribution is embedded in the vector tile
metadata. This is a condition of use, not a courtesy: if you fork this, the
notice travels with it.
