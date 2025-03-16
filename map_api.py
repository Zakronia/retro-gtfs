import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry
import json, db
from conf import conf
from numpy import mean
from shapely.geometry import MultiLineString
from shapely.geometry.geo import shape # note: changed asShape to shape
from shapely.ops import transform as reproject
from shapely.wkb import loads as loadWKB, dumps as dumpWKB
from copy import copy
from geom import cut
from minor_objects import TimePoint


class match(object):
	"""This object is responsible for coming up with a more spatially accurate 
	version of the trip. We do this by first trying to map match the GPS 
	track to the street/rail network using OSRM. If that doesn't work well 
	for any reason, we try altering some parameters to improve the match. 
	If it's still not great, we can see if there is a default route_geometry 
	provided. Ultimately, we judge whether the match is sufficent to proceed.

	If we do use this match, this object also provides methods for associating 
	points (vehicles, stops) with points along the route gemetry; these will 
	be used for time interpolation inside the trip object."""
	
	def __init__(self, trip_object):
		self.geometry = MultiLineString()
  		# initialize some variables
		self.OSRM_response = {}					# python-parsed OSRM response object
		self.trip = trip_object
		# error radius to use for map matching, same for all points
		self.error_radius = conf['error_radius']
		self.default_route_used = False

		# fire off a query to OSRM with the default parameters
		print ('map_api_debug: running self.query_OSRM()')
		self.query_OSRM()

		if not self.OSRM_match_is_sufficient:
			# try again with a larger error radius
			print ('map_api_debug: match not sufficient, trying larger error radius')
			self.error_radius *= 2
			print ('map_api_debug: running self.query_OSRM()')
			self.query_OSRM()

		# still no good? 
		if not self.OSRM_match_is_sufficient:
			# Try a default geometry
			if self.get_default_route():
				self.locate_vehicles_on_default_route()
			else: 
				return # bad match, no default
		else: # have a workable OSRM match geometry
			print ('map_api_debug: parsing OSRM geometry')
			self.parse_OSRM_geometry()
			self.locate_vehicles_on_OSRM_route()

		if len(self.trip.vehicles) > 2:
			print ('map_api_debug: locating stops on route')
			self.locate_stops_on_route()
		db.add_trip_match(self.trip.trip_id, self.confidence, dumpWKB( self.geometry, hex=True ))
		# report on what happened
		self.print_outcome()

	@property
	def OSRM_match_is_sufficient(self):
		"""Is this match good enough actually to be used?"""
		return self.confidence >= conf['min_OSRM_match_quality']

	@property
	def is_useable(self):
		"""Do we have everything we need to proceed with the match?"""
		if not (self.OSRM_match_is_sufficient or self.default_route_used):
			return False
		if not len(self.trip.vehicles) > 3:
			return False
		if self.trip.vehicles[0].measure == self.trip.vehicles[-1].measure:
			return False
		if not len(self.trip.timepoints) > 1:
			return False
		# and only if we make it past all those conditions:
		return True
	
	@property
	def confidence(self):
		if self.OSRM_response['code'] != 'Ok':
			return self.OSRM_response['matchings']['confidence']
		else:
			# Get an average confidence value from the match result.
			confidence_values = [ m['confidence'] for m in self.OSRM_response['matchings'] ]
			return mean( confidence_values )

	def query_OSRM(self):
		"""Construct the request and send it to OSRM, retrying if necessary."""
		# structure it as API requires, rounding coords to 6 decimals
		coords = ';'.join( [ 
			format(v.lon,'.7g')+','+format(v.lat,'.7g') for v in self.trip.vehicles 
		] )
		radii = ';'.join( [ str(self.error_radius) ] * len(self.trip.vehicles) )
		# construct and send the request
		options = {
			'radiuses':radii,
			'steps':'false',
			'geometries':'geojson',
			'annotations':'false',
			'overview':'full',
			'gaps':'ignore', # don't split based on time gaps - shouldn't be any
			'tidy':'true',
			'generate_hints':'false'
		}
		# open a connection, configured to retry in case of errors
		with requests.Session() as session:
			retries = Retry( total=5, backoff_factor=1 )
			session.mount( 'http://', HTTPAdapter(max_retries=retries) )
			# make the request
			try:
				raw_response = session.get(
					conf['OSRMserver']['url']+'/match/v1/transit/'+coords,
					params=options,
					timeout=conf['OSRMserver']['timeout']
					)
			except:
				return db.ignore_trip(self.trip.trip_id,'connection issue')
		# parse the result to a python object
		self.OSRM_response = json.loads(raw_response.text)
		# how confident should we be in this response?


	def parse_OSRM_geometry(self):
		"""Parse the OSRM match geometry into a more useable format.
			Specifically a simplified and projected MultiLineString."""
		# get a list of lists of lat-lon coords which need to be reprojected
		lines = [shape(matching['geometry']) for matching in self.OSRM_response['matchings']] # note: changed asShape to shape
		multilines = MultiLineString(lines)
		# reproject to local 
		local_multilines = reproject( conf['projection'], multilines )
		# simplify slightly for speed (2 meter simplification)
		simple_local_multilines = local_multilines.simplify(2)
		# if the multi actually just had one line, this simplifies to a 
		# linestring, which can cause problems down the road
		if simple_local_multilines.geom_type == 'LineString':
			simple_local_multilines = MultiLineString([simple_local_multilines])
		self.geometry = simple_local_multilines


	def get_default_route(self):
		"""Check if a default route geometry is available; if so, we'll need to 
			parse things into the same format, just as though this had come from 
			OSRM."""
		# get the default if there is one
		route_geom = db.get_route_geom( self.trip.direction_id, self.trip.last_seen )
		if route_geom: # default available
			self.default_route_used = True
			self.confidence = 1
			self.geometry = MultiLineString([route_geom])
			return True
		else: # no default
			return False


	def print_outcome(self):
		"""Print the outcome of this match to stdout."""
		if self.default_route_used and self.confidence == 1:
			print( '\tdefault route used for direction',self.trip.direction_id )
		elif self.default_route_used and self.confidence == 0:
			print( '\tdefault route not found for',self.trip.direction_id )
		elif not self.default_route_used and self.confidence > conf['min_OSRM_match_quality']:
			print( '\tOSRM match found with',round(self.confidence,3),'confidence' )
		else:
			print( '\tmatching failed for trip',self.trip.trip_id )


	# Below are functions associated with finding the measure of points along
	# the route geometry, either as given by OSRM or provided as the default.
	# These are called from inside the trip if the match is useable.


	def locate_vehicles_on_OSRM_route(self):
		"""Find the measure of vehicles along the OSRM-supplied route. This is 
		easy because OSRM provides the distance of an input coordinate along the 
		match geometry."""
		assert not self.default_route_used
		# these are the matched points of the input cordinates
		# null (None) entries indicate an omitted (outlier) point
		# true where not none
		drop_list = [ point is None for point in self.OSRM_response['tracepoints'] ]
		# drop vehicles that did not contribute to the match,
		# backwards to maintain order
		for i in reversed( range( 0, len(drop_list) ) ):
			if drop_list[i]: self.trip.ignore_vehicle( i )
		# get cumulative distances of each vehicle along the match geom
		# This is based on the leg distances provided by OSRM. Each leg is just 
		# the trip between matched points. Each match has one more vehicle record 
		# associated with it than legs
		cummulative_distance = 0
		v_i = 0
		for matching in self.OSRM_response['matchings']:
			# the first point is at 0 per match
			self.trip.vehicles[v_i].set_measure( cummulative_distance )
			v_i += 1
			for leg in matching['legs']:
				cummulative_distance += leg['distance']
				self.trip.vehicles[v_i].set_measure( cummulative_distance )
				v_i += 1
		# Because the line has been simplified, the distances will be 
		# slightly off and need correcting 
		adjust_factor = self.geometry.length / self.trip.vehicles[-1].measure
		for v in self.trip.vehicles:
			v.measure = v.measure * adjust_factor


	def locate_vehicles_on_default_route(self):
		"""Find the measure of vehicles along the default route. First discard 
		observations too far from the route geometry. Next, find the measure of 
		the remaining vehicles in the order they were observed. If the vehicles 
		progress monotonically down the line then all is good. Otherwise, we 
		start dropping observations that are most severely out of order until we 
		are left with an ordered list moving along the route in the correct 
		direction. Wrong direction travel will generally result in a minimal
		ordered set: 1 remaining observation."""
		assert self.default_route_used
		# match stops within a distance of the route geometry
		vehicles_to_ignore = []
		for vehicle in self.trip.vehicles:
			# if the vehicle is close enough
			distance_from_route = self.geometry.distance( vehicle.geom )
			if distance_from_route <= conf['stop_dist']:
				m = self.geometry.project(vehicle.geom)
				vehicle.set_measure(m)
			else:
				vehicles_to_ignore.append(vehicle)
		for vehicle in vehicles_to_ignore:
			self.trip.ignore_vehicle( vehicle )
		# while the list is not fully sorted
		while self.trip.vehicles != sorted(self.trip.vehicles,key=lambda v: v.measure):
			correct_order = sorted(self.trip.vehicles,key=lambda v: v.measure)
			current_order = self.trip.vehicles
			transpositions = {}
			# compare all vehicles in both lists
			for i,v1 in enumerate(correct_order):
				for j,v2 in enumerate(current_order):
					if v1 == v2:
						if abs(i-j) > 0: # not in the same position
							# add these vehicles to the list with their distances as keys
							if abs(i-j) not in transpositions: transpositions[abs(i-j)] = [v1]
							else: transpositions[abs(i-j)].append(v1)
						else: # are in the same position
							continue
			max_dist = max(transpositions.keys())
			# ignore vehicles associated with the max of the transposition distances
			for vehicle in transpositions[max_dist]:
				self.trip.ignore_vehicle(vehicle)
		# now we either have a sorted list or an essentially empty list if the 
		# match happened to be bad


	def locate_stops_on_route(self):
		"""Find the measure of stops along the route geometry for any arbitrary 
			route. Stops must be within a given distance of the path, but can 
			repeat if the route passes a stop two or more times. To check for this,
			the geometry is sliced up into segments and we check just a portion 
			of the route at a time."""
		assert len(self.trip.stops) > 0
		assert self.geometry.length > 0
		# list of timepoints
		potential_timepoints = []
		# copy the geometry so we can slice it up it
		path = copy(self.geometry)
		traversed = 0
		# while there is more than 750m of path remaining
		while path.length > 0:
			subpath, path = cut(path,750)
			# check for nearby stops
			for stop in self.trip.stops:
				# if the stop is close enough
				stop_dist = subpath.distance(stop.geom)
				if stop_dist <= conf['stop_dist']:
					# measure how far it is along the trip
					m = traversed + subpath.project(stop.geom)
					# add it to the list of measures
					potential_timepoints.append( TimePoint(stop,m,stop_dist) )
			# note what we have already traversed
			traversed += 750
		# Now some of these will be duplicates that are close to the cutpoint
		# and thus are added twice with similar measures
		# such points need to be removed
		final_timepoints = []
		for pt in potential_timepoints:
			skip_this_timepoint = False
			for ft in final_timepoints:
				# if same stop and very close
				if pt.stop_id == ft.stop_id and abs(pt.measure-ft.measure) < 2*conf['stop_dist']:
					#choose the closer of the two to use
					if ft.dist <= pt.dist:
						skip_this_timepoint = True
						break 
					else:
						ft = pt
						skip_this_timepoint = True
						break
			if not skip_this_timepoint:
				# we didn't have anything like that in the final set yet
				final_timepoints.append( pt )
		# add terminal stops if they are anywhere near the GPS data
		# but not used yet
		if not self.default_route_used:
			# for first and last stops
			for terminal_stop in [self.trip.stops[0],self.trip.stops[-1]]:
				if not terminal_stop.id in [ t.stop.id for t in potential_timepoints ]:
					# if the terminal stop is less than 500m away from the route
					dist = self.geometry.distance(terminal_stop.geom)
					if dist < 500:
						m = self.geometry.project(terminal_stop.geom)
						final_timepoints.append( TimePoint(
							terminal_stop,
							m-dist if m < self.geometry.length/2 else m+dist,
							dist
						) )
		# for default geometries on the other hand, remove stops that are nowhere
		# near the actual GPS data
		else:
			final_timepoints = [
				t for t in final_timepoints if 
				t.measure > self.trip.vehicles[0].measure - 500 and 
				t.measure < self.trip.vehicles[-1].measure + 500
			]
		# sort by measure ascending
		final_timepoints = sorted(final_timepoints,key=lambda timepoint: timepoint.measure)
		self.trip.timepoints = final_timepoints