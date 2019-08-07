# MAE boundaries

Apply MAE (French Foreign Office) rules to OSM boundaries.

It will generate two geojson:

- `boundary.json`, with the international boundaries
- `disputed.json`, with the disputed areas

It also provides a list of country and city names.

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

        python -m venv mae
        source mae/bin/activate
        pip install -r requirements.txt

- run the script:

        python make.py all


## Rules

- `areas`: define areas to be included/excluded from country boundaries, based on
  OSM keys on based on other areas name (using `includes`)
- `disputed`: list areas that are considered "disputed" by MAE
- `countries`: for each country (based on ISO code), list areas to include/exclude
