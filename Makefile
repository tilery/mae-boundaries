COASTLINE = land-polygons-complete-4326
DATABASE = mae

all: process

$(COASTLINE).zip:
	wget https://osmdata.openstreetmap.de/download/$@

# unzip restores the archive's own mtimes, older than the zip itself
$(COASTLINE)/land_polygons.shp: $(COASTLINE).zip
	unzip -o $<
	touch $@

download_coastline: $(COASTLINE)/land_polygons.shp

import_coastline: $(COASTLINE)/land_polygons.shp
	ogr2ogr -f "PostgreSQL" PG:"dbname=$(DATABASE)" $< -nln land -lco GEOMETRY_NAME=geom

process:
	python make.py all

.PHONY: all download_coastline import_coastline process
