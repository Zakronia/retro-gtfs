# call this file to begin processing a set of trips from 
# stored vehicle locations. It will ask which trips from 
# the db to process. You can either process individual 
# trips or a range of trips given sequential trip_ids 

import multiprocessing as mp
from time import sleep
from trip import Trip
import db
from random import shuffle

# let mode be one of ('single','range?')
mode = input('Processing mode (single, all, route, or unfinished) --> ')

def process_trip(valid_trip_id):
	"""worker process called when using multiprocessing"""
	print( 'starting trip:',valid_trip_id )
	db.reconnect()
	t = Trip.fromDB(valid_trip_id)
	t.process()

def process_trips(trip_ids):
	shuffle(trip_ids)
	print( len(trip_ids),'trips in that range' )
	# how many parallel processes to use?
	max_procs = int(input('max processes --> '))
	# create a pool of workers and pass them the data
	p = mp.Pool(max_procs)
	p.map(process_trip,trip_ids,chunksize=3)
	print( 'COMPLETED!' )

# single mode enters one trip at a time and stops when 
# a non-integer is entered
if mode in ['single','s']:
	trip_id = input('trip_id to process--> ')
	while trip_id.isdigit():
		if db.trip_exists(trip_id):
			# create a trip object
			this_trip = Trip.fromDB(trip_id)
			# process
			this_trip.process()
		else:
			print( 'no such trip' )
		# ask for another trip and continue
		trip_id = input('trip_id to process --> ')
# 'range' mode does all valid ids in the given range
elif mode in ['all','a']:
	# get a list of all trip id's in the range
	trip_ids = db.get_trip_ids_by_range(-float('inf'),float('inf'))
	process_trips(trip_ids)
# process only a certain route
elif mode in ['route','r']:
	route_id = input('route_id --> ')
	trip_ids = db.get_trip_ids_by_route(route_id)
	process_trips(trip_ids)
# process only trips that haven't been processed sucessfully yet
elif mode in ['unfinished','u']:
	trip_ids = db.get_trip_ids_unfinished()
	process_trips(trip_ids)
else:
	print( 'Invalid mode given.' )