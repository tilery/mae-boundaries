# MAE boundaries

Apply MAE (French Foreign Office) rules to OSM boundaries.

It will generate two geojson:

- `boundary.json`, with the international boundaries
- `disputed.json`, with the disputed areas


## System requirements

- postgresql
- postgis
- python >= 3.6

## Usage

- Create a `mae` psql database with postgis enabled

    createdb mae
    psql mae -c 'CREATE EXTENSION postgis'

- Create python [virtualenv](http://docs.python-guide.org/en/latest/dev/virtualenvs/),
  activate it and install python dependencies

    python3 -m venv mae
    source mae/bin/activate
    pip install -r requirements.txt

- run the script:

    python make.py process
