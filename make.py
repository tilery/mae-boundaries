import csv
from pathlib import Path

import sys
import asyncpg
import overpy
import requests
import ujson as json
from minicli import cli, run
from postgis import LineString, MultiLineString
from postgis.asyncpg import register

OVERPASS = 'https://overpass-api.de/api/interpreter'


async def get_relation(conn, **tags):
    if 'iso' in tags:
        tags['ISO3166-1:alpha2'] = tags.pop('iso')
    tags = "".join(f'["{k}"="{v}"]' for k, v in tags.items())
    path = Path('tmp/boundary')
    path.mkdir(parents=True, exist_ok=True)
    file_ = (tags.replace('/', '_').replace('][', '_')
                 .replace('"', '').replace(':', '_').replace('[', '')
                 .replace(']', '') + '.json')
    path = path / file_
    if not path.exists():
        params = {'data': f'[out:json];relation{tags};(._;>;);out body;'}
        try:
            resp = requests.get(OVERPASS, params=params)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            print(f'\nError: Network problem retrieving data')
            sys.exit(1)
        except requests.exceptions.HTTPError as err:
            print(f'\nHTTPError: {err}')
            sys.exit(1)
        data = resp.content
        with path.open('wb') as f:
            f.write(data)
        data = data.decode()
    else:
        with path.open() as f:
            data = f.read()
    try:
        relation = overpy.Result.from_json(json.loads(data)).relations[0]
    except IndexError:
        raise ValueError(f'Cannot find relation for {tags}')
    collection = []
    for member in relation.members:
        coords = []
        # Nepal disputed way without outer role:
        # http://www.openstreetmap.org/way/202061325
        if member.role != 'outer' and member.ref != 202061325:
            continue
        way = member.resolve()
        for node in way.nodes:
            coords.append((float(node.lon), float(node.lat)))
        collection.append(LineString(coords))
    shape = await make_polygon(conn, MultiLineString(collection))
    return shape


async def make_polygon(conn, geom):
    return await conn.fetchval(
        'SELECT ST_Multi(ST_Collect(ST_MakePolygon((sub.dump).geom))) FROM '
        '(SELECT ST_Dump(ST_LineMerge($1::geometry)) as dump) AS sub', geom)


async def compute_golan(conn):
    golan = await get_relation(conn, boundary="administrative",
                               admin_level="8", name="מועצה אזורית גולן")
    majdal = await get_relation(conn, boundary="administrative",
                                admin_level="8", name="مجدل شمس")
    return await conn.fetchval(
        'SELECT ST_MakePolygon(ST_ExteriorRing(ST_Union($1::geometry, '
        '$2::geometry)))', golan, majdal)


async def compute_doklam(conn):
    # https://en.wikipedia.org/wiki/en:Doklam?uselang=fr
    shape = await get_relation(conn, boundary="administrative",
                               admin_level="3", name="Doklam 洞郎地区")
    other = await get_relation(conn, boundary="administrative",
                               admin_level="3", name="鲁林地区")
    shape = await add_area(conn, shape, other)
    other = await get_relation(conn, boundary="administrative",
                               admin_level="3", name="查马普地区")
    shape = await add_area(conn, shape, other)
    other = await get_relation(conn, boundary="administrative",
                               admin_level="3", name="基伍地区")
    shape = await add_area(conn, shape, other)
    return shape


async def compute_kashmir(conn):
    shape = await get_relation(conn, boundary="administrative",
                               admin_level="4", name="Jammu and Kashmir")
    kashmir_pak = await get_relation(conn, boundary="disputed_area",
                                     admin_level="", name="Kashmir")
    shape = await add_area(conn, shape, kashmir_pak)
    aksai_chin = await get_relation(
        conn, boundary="disputed_area",
        admin_level="", name="阿克赛钦 / Aksai Chin / अक्साई चिन")
    shape = await add_area(conn, shape, aksai_chin)
    demchok = await get_relation(conn, boundary="disputed_area",
                                 name="Demchok Eastern Sector")
    shape = await add_area(conn, shape, demchok)
    trans_karakoram = await get_relation(
        conn, boundary="disputed_area", name="Trans-Karakoram Tract")
    shape = await add_area(conn, shape, trans_karakoram)

    return shape


async def remove_area(conn, shape, other):
    return await conn.fetchval(
        'SELECT ST_Difference($1::geometry, $2::geometry)', shape, other)


async def add_area(conn, shape, other):
    return await conn.fetchval(
        'SELECT ST_Union($1::geometry, $2::geometry)', shape, other)


async def load_country(conn, admin_level=2, **tags):
    return await get_relation(conn, boundary='administrative',
                              admin_level=admin_level, **tags)


async def snap_to_coastline(conn, country):
    return await conn.fetchval("""
        SELECT ST_Intersection(
            ST_SetSRID(ST_Boundary(ST_ForcePolygonCCW($1::geometry)), 4326),
            (SELECT ST_Collect(geom)
             FROM land
             WHERE ST_Intersects(ST_SetSRID($1::geometry, 4326), geom)))
        """, country)


@cli
async def process(itl_path: Path=Path('exports/boundary.json'),
                  disputed_path: Path=Path('exports/disputed.json'),
                  database='mae'):
    itl_path.parent.mkdir(parents=True, exist_ok=True)
    disputed_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await asyncpg.connect(database=database)
    await register(conn)
    boundaries = []
    disputed = []

    def add_disputed(polygon):
        disputed.append({
            'type': 'Feature',
            'geometry': polygon.geojson
        })

    # Used more than once.
    kashmir = await compute_kashmir(conn)
    add_disputed(kashmir)
    shipki_la = await get_relation(conn, type='boundary',
                                   name='什布奇山口地区')
    add_disputed(shipki_la)
    kaurik = await get_relation(conn, type='boundary',
                                name='巨哇、曲惹地区')
    add_disputed(kaurik)
    jadh = await get_relation(conn, type='boundary',
                              name='桑、葱莎、波林三多地区')
    add_disputed(jadh)
    lapthal = await get_relation(conn, type='boundary',
                                 name='乌热、然冲、拉不底地区')
    add_disputed(lapthal)
    golan = await compute_golan(conn)
    add_disputed(golan)
    doklam = await compute_doklam(conn)
    add_disputed(doklam)
    bir_tawil = await get_relation(conn, type='boundary',
                                   name='بيرطويل (Bir Tawil)')
    add_disputed(bir_tawil)
    halaib_triangle = await get_relation(conn, type='boundary',
                                         name='مثلث حلايب‎')
    add_disputed(halaib_triangle)

    with (Path(__file__).parent / 'country.csv').open() as f:
        countries = list(csv.DictReader(f))

    print('\nDownload and import countries to database\n')

    for country in countries:
        iso = country['iso']
        admin_level = int(country['admin_level'] or 0)
        if 0 < admin_level < 4:
            polygon = await load_country(conn, admin_level=admin_level,
                                         iso=iso)
            properties = country
            if properties['name:en'] == 'Sahrawi Arab Democratic Republic':
                continue
            print(f"{iso} : `{properties['name']}` ({properties['name:en']})")
            if iso == 'IL':
                polygon = await remove_area(conn, polygon, golan)
                west_bank = await get_relation(conn, place="region",
                                               name="الضفة الغربية")
                polygon = await remove_area(conn, polygon, west_bank)
            if iso == 'SY':
                polygon = await add_area(conn, polygon, golan)
            if iso == 'SS':
                sudan = await load_country(conn, 2, iso='SD')  # Sudan
                polygon = await remove_area(conn, polygon, sudan)
            if properties['name:en'] == 'Sudan':
                polygon = await remove_area(conn, polygon, bir_tawil)
            if iso == 'EG':
                polygon = await add_area(conn, polygon, bir_tawil)
            if iso == 'NP':
                claim = await get_relation(conn, type="boundary",
                                           name="Extent of Nepal Claim")
                add_disputed(claim)
                polygon = await add_area(conn, polygon, claim)
            if iso == 'IN':
                claim = await get_relation(conn, type="boundary",
                                           name="Extent of Nepal Claim")
                polygon = await remove_area(conn, polygon, claim)
            if iso == 'CN':
                polygon = await remove_area(conn, polygon, doklam)
            if iso == 'BH':
                polygon = await add_area(conn, polygon, doklam)
            if iso == 'MA':
                # Western Sahara
                esh = await get_relation(conn, boundary="disputed",
                                         name="الصحراء الغربية")
                add_disputed(esh)
                polygon = await add_area(conn, polygon, esh)
            border = await snap_to_coastline(conn, polygon)
            boundaries.append({
                'type': 'Feature',
                'geometry': border.geojson,
                'properties': properties
            })
    sba, properties = await load_country(conn,
                                         name='British Sovereign Base Areas')
    boundaries.append({
        'type': 'Feature',
        'geometry': sba.geojson,
        'properties': properties
    })
    await conn.close()
    with itl_path.open('w') as f:
        print(f'''\nExport of {itl_path}\n''')
        json.dump({'type': 'FeatureCollection', 'features': boundaries}, f,
                  indent=1)
    with disputed_path.open('w') as f:
        print(f'''Export of {disputed_path}\n''')
        json.dump({'type': 'FeatureCollection', 'features': disputed}, f,
                  indent=1)


if __name__ == '__main__':
    run()
