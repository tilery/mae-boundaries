import csv
from pathlib import Path

import sys
import asyncpg
import overpy
import requests
import ujson as json
import yaml
from minicli import cli, run, wrap
from postgis import LineString, MultiLineString
from postgis.asyncpg import register

OVERPASS = "https://overpass-api.de/api/interpreter"
CONN = None


async def get_relation(**tags):
    if "iso" in tags:
        tags["ISO3166-1:alpha2"] = tags.pop("iso")
    tags = "".join(f'["{k}"="{v}"]' for k, v in tags.items())
    path = Path("tmp/boundary")
    path.mkdir(parents=True, exist_ok=True)
    file_ = (
        tags.replace("/", "_")
        .replace("][", "_")
        .replace('"', "")
        .replace(":", "_")
        .replace("[", "")
        .replace("]", "")
        + ".json"
    )
    path = path / file_
    if not path.exists():
        print(f"Downloading {path}")
        params = {"data": f"[out:json];relation{tags};(._;>;);out body;"}
        try:
            resp = requests.get(OVERPASS, params=params)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            print(f"\nError: Network problem retrieving data")
            sys.exit(1)
        except requests.exceptions.HTTPError as err:
            print(f"\nHTTPError: {err}")
            sys.exit(1)
        data = resp.content
        with path.open("wb") as f:
            f.write(data)
        data = data.decode()
    else:
        with path.open() as f:
            data = f.read()
    try:
        relation = overpy.Result.from_json(json.loads(data)).relations[0]
    except IndexError:
        raise ValueError(f"Cannot find relation for {tags}")
    collection = []
    for member in relation.members:
        coords = []
        # Nepal disputed way without outer role:
        # http://www.openstreetmap.org/way/202061325
        if member.role != "outer" and member.ref != 202_061_325:
            continue
        way = member.resolve()
        for node in way.nodes:
            coords.append((float(node.lon), float(node.lat)))
        collection.append(LineString(coords))
    shape = await make_polygon(MultiLineString(collection))
    return shape


async def make_polygon(geom):
    return await CONN.fetchval(
        "SELECT ST_Multi(ST_Collect(ST_MakePolygon((sub.dump).geom))) FROM "
        "(SELECT ST_Dump(ST_LineMerge($1::geometry)) as dump) AS sub",
        geom,
    )


async def remove_area(shape, other):
    return await CONN.fetchval(
        "SELECT ST_Difference($1::geometry, $2::geometry)", shape, other
    )


async def add_area(shape, other):
    return await CONN.fetchval(
        "SELECT ST_Union($1::geometry, $2::geometry)", shape, other
    )


async def load_country(admin_level=2, **tags):
    return await get_relation(
        boundary="administrative", admin_level=admin_level, **tags
    )


async def snap_to_coastline(country):
    return await CONN.fetchval(
        """
        SELECT ST_Intersection(
            ST_SetSRID(ST_Boundary(ST_ForcePolygonCCW($1::geometry)), 4326),
            (SELECT ST_Collect(geom)
             FROM land
             WHERE ST_Intersects(ST_SetSRID($1::geometry, 4326), geom)))
        """,
        country,
    )


async def exterior_ring(shape):
    return await CONN.fetchval(
        "SELECT ST_MakePolygon(ST_ExteriorRing($1::geometry))", shape
    )


def load_rules():
    return yaml.safe_load((Path(__file__).parent / "rules.yml").read_text())


async def load_areas():
    areas = {}
    rules = load_rules()
    print("# Computing areas")
    for name, properties in rules["areas"].items():
        print(name)
        if not properties.get("includes"):
            shape = await get_relation(**properties)
        else:
            shape = None
            while properties["includes"]:
                subarea = areas[properties["includes"].pop(0)]
                if not shape:
                    shape = subarea
                else:
                    shape = await add_area(shape, subarea)
            if properties.get("exterior-ring"):
                shape = await exterior_ring(shape)
        areas[name] = shape
    return areas


@cli(name="all")
async def process(
    itl_path: Path = Path("exports/boundary.json"),
    disputed_path: Path = Path("exports/disputed.json"),
    country=None,
):
    itl_path.parent.mkdir(parents=True, exist_ok=True)
    disputed_path.parent.mkdir(parents=True, exist_ok=True)
    boundaries = []
    if country is not None:
        boundaries = json.loads(itl_path.read_text())["features"]
        boundaries = [b for b in boundaries if b["properties"].get("iso") != country]
    else:
        sba = await load_country(name="British Sovereign Base Areas")
        boundaries.append(
            {
                "type": "Feature",
                "geometry": sba.geojson,
                "properties": {"name": "British Sovereign Base Areas"},
            }
        )
    areas = await load_areas()
    rules = load_rules()

    with (Path(__file__).parent / "country.csv").open() as f:
        countries = list(csv.DictReader(f))

    print("\n# Process countries\n")

    for properties in countries:
        iso = properties["iso"]
        if country is not None and iso != country:
            continue
        admin_level = int(properties["admin_level"] or 0)
        if not (0 < admin_level < 4):
            continue
        polygon = await load_country(admin_level=admin_level, iso=iso)
        print(f"{iso} : `{properties['name']}` ({properties['name:en']})")
        if iso in rules["countries"]:
            print(f"| Patching country {iso}")
            for name in rules["countries"][iso].get("excludes", []):
                print(f" - Removing {name}")
                polygon = await remove_area(polygon, areas[name])
            for name in rules["countries"][iso].get("includes", []):
                print(f" + Adding {name}")
                polygon = await add_area(polygon, areas[name])
        print(f"| Snapping {iso} to coastline")
        border = await snap_to_coastline(polygon)
        boundaries.append(
            {"type": "Feature", "geometry": border.geojson, "properties": properties}
        )
    with itl_path.open("w") as f:
        print(f"""\nExport of {itl_path}\n""")
        json.dump({"type": "FeatureCollection", "features": boundaries}, f, indent=1)
    with disputed_path.open("w") as f:
        print(f"""Export of {disputed_path}\n""")
        json.dump(
            {
                "type": "GeometryCollection",
                "geometries": [areas[n].geojson for n in rules["disputed"]],
            },
            f,
            indent=1,
        )


@cli
async def show_area(name):
    areas = await load_areas()
    print(areas[name].geojson)


@cli
async def show_country(iso, path: Path = Path("exports/boundary.json")):
    for boundary in json.loads(path.read_text())["features"]:
        if boundary["properties"].get("iso") == iso:
            print(json.dumps(boundary))
            break
    else:
        print(f"Cannot find {iso} in countries list")


@wrap
async def wrapper(database):
    global CONN
    CONN = await asyncpg.connect(database=database)
    await register(CONN)
    yield
    await CONN.close()


if __name__ == "__main__":
    run(database="mae")
