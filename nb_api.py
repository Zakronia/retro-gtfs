# functions involving requests to the nextbus APIs

import requests, time, db, sys
from requests.adapters import HTTPAdapter
from urllib3 import Retry
import threading, multiprocessing
import json
from datetime import datetime
from trip import Trip
from os import remove, path
from conf import API_KEY, conf # configuration
from minor_objects import Stop, TimePoint
import logging

now = datetime.now()
cdt = now.strftime("%Y%m%d_%H%M%S")
logFormat = "%(levelname)s:%(name)s %(asctime)s %(message)s"
logging.basicConfig(filename="C:\\Users\\Zach\\research\\python\\logs\\" + cdt + ".log", level=logging.DEBUG, format=logFormat)
logger = logging.getLogger()

# should we process trips (or simply store the vehicles)? default False
doMatching = True

# GLOBALS
fleet = {} 			# operating vehicles in the ( fleet vid -> trip_obj )
next_bid = db.new_block_id()		# next block_id to be assigned
last_update = 0	# last update from server, removed results already reported

fleet_lock = threading.Lock()
print_lock = threading.Lock()
record_check_lock = threading.Lock()

def get_new_vehicles():
	"""hit the vehicleLocations API and get all vehicles that have updated 
		since the last check. Associate each vehicle with a trip_id (tid)
		and send the trips for processing when it is determined that they 
		have ended"""
	global fleet
	global next_bid
	global last_update
	# UNIX time the request was sent
	request_time = time.time()

	try: 
		response = requests.get(
			'https://api.pugetsound.onebusaway.org/api/where/vehicles-for-agency/3.json',
			params={'key':API_KEY},
			headers={'Accept-Encoding':'gzip, deflate'},
			timeout=3
		)
	except:
		logger.warning( msg = 'connection problem at ' )
		return

	# UNIX time the response was received
	response_time = time.time()
	# estimated UNIX time the server generated it's report
	# (halfway between send and reply times)
	server_time = (request_time + response_time) / 2
	# list of trips to send for processing
	ending_trips = []
 
	# parsing and storing the results
	JSON = json.loads(response.text)
	vehicles = JSON['data']['list']
 
	# get values from the XML
	## last_update = int(XML.find('./lastTime').attrib['time'])
	last_update = JSON['currentTime']
 
	# prevent simulataneous editing
	with fleet_lock:
		# check to see if there's anything we just haven't heard from at all lately
		for vehicleID in list(fleet.keys()):
			# if it's been more than 30 minutes
			if server_time - fleet[vehicleID].last_seen > 1800:
				# it has ended
				ending_trips.append(fleet[vehicleID])
				del fleet[vehicleID]
    
		# Now, for each reported vehicle
		for vehicle in vehicles:
			if vehicle['tripId'] == "":
				continue

			# get values from parsed JSON
			vehicleID, tripID = vehicle['vehicleId'][2:], vehicle['tripId'][2:]
			lon = float( vehicle[ 'location' ][ 'lon' ] )
			lat = float( vehicle[ 'location' ][ 'lat' ] )

			# iterate through each of the reference trips to find the one we need.
			# not very efficient, but means we don't have to send a metric shit ton of API requests
			trips = JSON['data']['references']['trips']
			for trip in trips:
				if trip['id'] == ('3_' + tripID):
					routeID = trip['routeId'][2:]
					blockID = trip['blockId'][2:]
					directionID = trip['directionId']
			report_time = vehicle['lastUpdateTime']

			try: # have we seen this vehicle recently?
				fleet[vehicleID]
			except: # haven't seen it! create a new trip
				fleet[vehicleID] = Trip.new(tripID,blockID,directionID,routeID,vehicleID,report_time)
				logger.info( msg = 'Created new trip ' + tripID + ' for vehicle ' + vehicleID )
				# add this vehicle to the trip
				fleet[vehicleID].add_point(lon,lat,report_time)
				# done with this vehicle
				continue
			# we have a record for this vehicle, and it's been heard from recently
			# see if anything else has changed that makes this a new trip
			if ( fleet[vehicleID].route_id != routeID or fleet[vehicleID].direction_id != directionID ):
				# this trip is ending
				ending_trips.append( fleet[vehicleID] )
				# create the new trip in it's place
				fleet[vehicleID] = Trip.new(tripID,blockID,directionID,routeID,vehicleID,report_time)
				logger.info( msg = 'Created new trip ' + tripID + ' for vehicle ' + vehicleID )
				# add this vehicle to it
				fleet[vehicleID].add_point(lon,lat,report_time)
    
				closestStopID = vehicle['tripStatus']['closestStop'][2:]
				tripDistance = vehicle['tripStatus']['distanceAlongTrip']
				stopOffset = vehicle['tripStatus']['closestStopTimeOffset']

				closestStopLat, closestStopLon = 0, 0
				for stop in JSON['data']['references']['stops']:
					if stop['id'] == closestStopID:
						closestStopLat = stop['lat']
						closestStopLon = stop['lon']

				closestStop = Stop.new(int(closestStopID), closestStopLat, closestStopLon, report_time)

				if fleet[vehicleID].add_timepoint( closestStop, tripDistance, 5, stopOffset):
					logging.info( msg = 'Refining time estimate for stop ' + str(closestStopID) + ' in Trip ' + str(fleet[vehicleID].trip_id) )
				else: logger.info( msg = 'Adding Stop ' + str(closestStopID) + ' to Trip ' + str(fleet[vehicleID].trip_id) )
			else: # not a new trip, just add the vehicle
				if len(fleet[vehicleID].waypoints) != 0 and report_time == fleet[vehicleID].waypoints[len(fleet[vehicleID].waypoints)-1]:
					continue

				fleet[vehicleID].add_point(lon,lat,report_time)
				# then update the time and sequence
				fleet[vehicleID].last_seen = report_time

				closestStopID = vehicle['tripStatus']['closestStop'][2:]
				tripDistance = vehicle['tripStatus']['distanceAlongTrip']
				stopOffset = vehicle['tripStatus']['closestStopTimeOffset']

				closestStopLat, closestStopLon = 0, 0
				for stop in JSON['data']['references']['stops']:
					if stop['id'] == closestStopID:
						closestStopLat = stop['lat']
						closestStopLon = stop['lon']

				closestStop = Stop.new(int(closestStopID), closestStopLat, closestStopLon, report_time)

				if fleet[vehicleID].add_timepoint( closestStop, tripDistance, 5, stopOffset):
					logging.info( msg = 'Refining time estimate for stop ' + str(closestStopID) + ' in Trip ' + str(fleet[vehicleID].trip_id) )
				else: logger.info( msg = 'Adding Stop ' + str(closestStopID) + ' to Trip ' + str(fleet[vehicleID].trip_id) )	
 	# release the fleet lock
	logger.info( str(len(fleet)) + ' in fleet and ' + str(len(ending_trips)) + ' ending trips')
 
 	# store the trips which are ending
	for trip in ending_trips:
		# to fix the running issue where the agency_id prefix doesn't get cut out correctly for some reason
		if trip.trip_id[:2] == '3_':
			trip.trip_id == trip.trip_id[2:]

		logger.info(msg = 'Trip ' + trip.trip_id + ' has ended')

		if len(trip.vehicles) > 1:
			with requests.Session() as session:
				retries = Retry( total=3, backoff_factor=1 )
				session.mount( 'http://', HTTPAdapter(max_retries=retries) )
				try: 
					response_stops = session.get(
						'http://api.pugetsound.onebusaway.org/api/where/trip-details/3_' + trip.trip_id + '.json', 
						params={'key':API_KEY},
						headers={'Accept-Encoding':'gzip, deflate'}, 
						timeout=conf['OSRMserver']['timeout']
					)
				except:
					logger.error(msg = 'Connection error fetching stops for trip ' + trip.trip_id)
					return

				JSON_TripDetails = json.loads(response_stops.text)
				stops = JSON_TripDetails['data']['references']['stops']
				logger.info( msg = 'Fetching ' + str(len(stops)) + ' stops for Trip ' + trip.trip_id)

				for stop in stops:
					try:	# some stops don't have a stop_Id / stop_code
						stop_code = int(stop['code'])
					except:
						stop_code = -1
						logger.warning(msg = str(stop['id']) + ' does not have a stop code, storing as -1')
					# store the stop, (or ignore it if there is nothing new)
					with record_check_lock:
						logger.info(msg = 'Trying to save stop ' + stop['id'][2:] + ' to database')
						db.try_storing_stop(
							stop['id'],		# stop_id
							stop['name'],	# stop_name
							stop_code,					# stop_code # sometimes is missing!
							stop['lon'], 
							stop['lat']
						)

			trip.save()
			logger.info(msg = 'Saving Trip ' + trip.trip_id + ' to the database')
		else:
			logger.warning(msg = 'Trip ' + trip['id'] + ' did not have enough vehicles to save to database')
	
 	# process the trips that are ending?
	if doMatching:
		for trip in ending_trips:
			# start each in it's own process
			logger.info( msg = 'Processing trip ' + str( trip.trip_id ) )
			thread = threading.Thread(target=trip.process)
			thread.start()