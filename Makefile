all: download_coastline import_coastline process
download_coastline:
	wget http://data.openstreetmapdata.com/land-polygons-complete-4326.zip
	unzip land-polygons-complete-4326.zip
import_coastline:
	ogr2ogr -f "PostgreSQL" PG:"dbname=mae" land-polygons-complete-4326/land_polygons.shp -nln land -lco GEOMETRY_NAME=geom
process:
	python make.py process
