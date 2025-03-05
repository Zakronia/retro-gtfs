from shapely.wkb import loads as loadWKB
from conf import conf
from shapely.geometry import Point
from shapely.ops import transform as reproject


class Vehicle(object):
	"""A transit vehicle GPS/space-time point record
		geometries provided straight from PostGIS"""

	def __init__( self, epoch_time, longitude, latitude ):
		# set now
		self.time = epoch_time
		self.longitude = longitude
		self.latitude = latitude
		self.local_geom = reproject( conf['projection'], Point(longitude,latitude) )
		# set later
		self.measure = None	# measure in meters along the matched route geometry

	@property
	def lat(self):
		return self.latitude

	@property
	def lon(self):
		return self.longitude
	
	@property
	def geom(self):
		return self.local_geom

	def set_measure(self,measure_in_meters):
		assert measure_in_meters >= 0
		self.measure = measure_in_meters

	def __repr__(self):
		return str(self.__dict__)



class Stop(object):
	"""A physical transit stop."""

	@classmethod
	def __init__(self):
		self.id = -1
		self.lat = -1
		self.lon = -1
		self.report_time = -1
	
	@classmethod
	def new(self, stop_id, projected_geom_hex ):
		# stop_id is the int UID of the stop, which can be associated with the 
		# given stop_id through the stops table
		Stop = self()
		Stop.id = stop_id
		Stop.geom = loadWKB( projected_geom_hex, hex=True )
		return Stop
  
	@classmethod
	def new(self, stop_id, lat, lon, time ):
		Stop = self()
		Stop.id = stop_id
		Stop.lat = lat
		Stop.lon = lon
		Stop.report_time = time
		return Stop

	def set_measure(self,measure_in_meters):
		assert measure_in_meters >= 0
		self.measure = measure_in_meters

	def __repr__(self):
		return str(self.__dict__)

	@property
	def getID(self):
		return self.id


class TimePoint(object):
	"""A stop in sequence."""
 
	@classmethod 
	def __init__(self):
		self.stop:Stop = None
		self.measure:int = None
		self.dist = None
		self.smallestOffset:int = None
		self.arrival_time = None
 
	@classmethod
	def new( self, stop_object_reference, measure, distance_from_route, offset ):
		TimePoint = self()
		TimePoint.stop = stop_object_reference	# Stop object
		TimePoint.measure = measure					# meters along route
		TimePoint.dist = distance_from_route		# meters distant from route
		TimePoint.smallestOffset = offset
		TimePoint.arrival_time = 0
		return TimePoint
	
	@property
	def stop_id(self):
		return int(self.stop.id)
	@property
	def geom(self):
		return self.stop.geom

	def set_time(self,epoch_time):
		self.arrival_time = epoch_time
	
	def __repr__(self):
		return str(self.__dict__)