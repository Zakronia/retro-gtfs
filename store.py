# main file, called to start the process of pulling vehicle locations

import threading
from nb_api import get_new_vehicles, logger
import db
from time import sleep
import random
import sys

# takes arguments from the command line
# should we get route information from the API? default False
getRoutes = True if 'getRoutes' in sys.argv else True
# should existing data be truncated? default False;
truncateData = True if 'truncateData' in sys.argv else False

def time_loop():
	"""timer function whose purpose is to call itself every N seconds 
		without stopping. Calls some other function after setting 
		itself to go off again"""
	threading.Timer( 10, time_loop ).start() # int is delay in seconds
	# request new vehicles and store them
	get_new_vehicles()

if truncateData:
	db.empty_tables()
	logger.info( msg='Truncating data')

# call the big function. This takes longer to run the first time, 
get_new_vehicles()

# so wait a bit longer than usual to call the timer function 10secs later
threading.Timer( 10, time_loop ).start()
# then it calls itself every N secs