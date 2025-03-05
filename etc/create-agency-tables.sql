/*
This script defines/creates the necessary database schema. It uses psql 
variables and should be run with psql on a PostgreSQL database with 
PostGIS installed. You'll need to set the projection for your region 
and optionally provide a table name prefix or otherwise change the table 
names to distinguish among agencies within a database.
*/
/*
equivalent to GTFS stops table
*/
CREATE EXTENSION POSTGIS;

-- DROP TABLE IF EXISTS 'pt_test_stops';
CREATE TABLE STOPS (
	STOP_ID VARCHAR,
	STOP_NAME NAME, -- required
	STOP_CODE SERIAL PRIMARY KEY, -- public_id
	LON NUMERIC,
	LAT NUMERIC,
	THE_GEOM GEOMETRY (POINT, 26917),
	REPORT_TIME DOUBLE PRECISION -- epoch time
);

CREATE INDEX ON STOPS (STOP_ID);

/*
Similar to GTFS trips table, in that it stores sequences of 
stops to be served by a trip and these can be matched to a 
direction_id on a particular vehicle
*/
-- DROP TABLE IF EXISTS 'pt_test_directions';
CREATE TABLE DIRECTIONS (
	UID SERIAL PRIMARY KEY,
	ROUTE_ID VARCHAR,
	DIRECTION_ID VARCHAR,
	TITLE VARCHAR,
	NAME VARCHAR,
	BRANCH VARCHAR,
	USEFORUI BOOLEAN,
	STOPS TEXT[],
	REPORT_TIME DOUBLE PRECISION, -- epoch time
	ROUTE_GEOM GEOMETRY (LINESTRING, 26917) -- optional default route geometry
);

CREATE INDEX ON DIRECTIONS (DIRECTION_ID);

/*
Data on vehilce locations fetched from the API gets stored here along 
with map-matched geometries. When extracted into GTFS, most feilds here 
are ignored. "Trips" are the primary object of the data processing sequence.  
*/
-- DROP TABLE IF EXISTS 'pt_test_trips';
CREATE TABLE TRIPS (
	TRIP_ID INTEGER PRIMARY KEY,
	-- linestring geometry with a point corresponding to each reported location
	-- correspends to "times", below
	ORIG_GEOM GEOMETRY (LINESTRING, 26917),
	-- sequential vehicle report times, corresponding to points on orig_geom
	-- times are in UNIX epoch
	TIMES DOUBLE PRECISION[],
	ROUTE_ID VARCHAR,
	DIRECTION_ID VARCHAR,
	-- service_id is a local variant on the number of days since the UNIX epoch
	SERVICE_ID SMALLINT,
	VEHICLE_ID VARCHAR,
	BLOCK_ID INTEGER,
	MATCH_CONFIDENCE REAL,
	-- this trip has not been processed or has been processed unsucessfully
	IGNORE BOOLEAN DEFAULT TRUE,
	-- debugging fields
	MATCH_GEOM GEOMETRY (MULTILINESTRING, 26917), -- map-matched route geometry
	CLEAN_GEOM GEOMETRY (LINESTRING, 26917), -- geometry of points used in map matching
	PROBLEM VARCHAR DEFAULT '' -- description of any problems that arise
);

CREATE INDEX ON TRIPS (TRIP_ID);

/*
Where interpolated stop times are stored for each trip. 
*/
-- DROP TABLE IF EXISTS 'pt_test_stop_times';
CREATE TABLE STOP_TIMES (
	TRIP_ID INTEGER,
	STOP_UID INTEGER,
	STOP_SEQUENCE INTEGER,
	ETIME DOUBLE PRECISION, -- non-localized epoch time in seconds
	FAKE_STOP_ID VARCHAR -- allows for repeated visits of the same stop
);

CREATE INDEX ON STOP_TIMES (TRIP_ID);