#!/usr/bin/env python
# coding=utf-8

import cgi
import os
import sys
import math
import pycurl
import StringIO
import simplejson as json
import time

API_URL = 'https://www.car2go.com/api/v2.1/vehicles?loc={loc}&oauth_consumer_key={key}&format=json'
MAPS_URL = 'https://maps.google.ca/maps?q={q}&ll={ll}&z=16&t=h'.replace('&', '&amp;')
MAPS_IFRAME_CODE = '<iframe width="300" height="250" frameborder="0" scrolling="no" marginheight="0" marginwidth="0" src="https://maps.google.ca/maps?q={q}&amp;ll={ll}&amp;t=m&amp;z=15&amp;output=embed"></iframe>'.replace('&', '&amp;')
MAPS_IMAGE_CODE = '<img src="http://maps.googleapis.com/maps/api/staticmap?size=300x250&zoom=15&markers=size:small|{ll}&markers=size:tiny|{other_ll}&center={ll}&visual_refresh=true&sensor=false" alt="map of {q}" width="300" height="250" />'.replace('&', '&amp;')
MAPS_MULTI_CODE = '<img src="http://maps.googleapis.com/maps/api/staticmap?size=300x250&markers=size:small|{ll}&visual_refresh=true&sensor=false" alt="{alt}" width="300" height="250" id="multimap" />'.replace('&', '&amp;')

# For zoom=15 and size 300x250, the map is less than 0.02 degrees across
# in both directions. In practice the observed value varies from 
# roughly 0.007385 degrees latitude to roughly 0.013326 degrees longitude
# (both in Vancouver), with numbers in other cities both north and south
# of Vancouver's latitude (Austin, Berlin) being fairly close.
# If we change displayed map size, we might also need to update this value,
# or come up with a formula to estimate it based on map size and zoom level.
MAP_SIZE_IN_DEGREES = 0.02

CACHE_PERIOD = 60 # cache data for this many seconds at most
DATA_COLLECTION_INTERVAL_MINUTES = 1 # used in download.py, process.py

CITIES = {
    'amsterdam': {'electric': 'all'},
    'austin': {'electric': 'some', 'number_first_address': True},
    'berlin': {'electric': 'some'},
    'calgary': {'number_first_address': True},
    'duesseldorf': {'display': 'Düsseldorf'},
    'hamburg': {},
    'koeln': {'display': 'Köln'},
    'london': {'number_first_address': True},
    'miami': {'number_first_address': True},
    'portland': {'of_interest': True, 'electric': 'some', 
        'number_first_address': True},
    'sandiego': {'display': 'San Diego', 'electric': 'all',
        'number_first_address': True},
    'seattle': {'of_interest': True, 'number_first_address': True},
    'stuttgart': {'electric': 'all'}, 
    'toronto': {'of_interest': True, 'number_first_address': True},
    'ulm': {'electric': 'some'},
    'vancouver': {'of_interest': True, 'electric': 'some',
        'number_first_address': True},
    'washingtondc': {'of_interest': True, 'display': 'Washington, D.C.',
        'number_first_address': True},
    'wien': {}
    }

# fill in city data that can be assumed and autogenerated
for city in CITIES:
    if not 'display' in CITIES[city]:
        CITIES[city]['display'] = city.title()
    if not 'electric' in CITIES[city]:
        CITIES[city]['electric'] = False
    if not 'of_interest' in CITIES[city]:
        CITIES[city]['of_interest'] = False
    if not 'number_first_address' in CITIES[city]:
        CITIES[city]['number_first_address'] = False

root_dir = os.path.dirname(os.path.realpath(__file__))
data_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data/')
filename_format = '%s_%04d-%02d-%02d--%02d-%02d'

timer = []

OAUTH_KEY = 'car2gowebsite' # default key used by car2go.com
if os.path.exists('oauth_key'):
    f = open('oauth_key', 'r')
    OAUTH_KEY = f.read().strip()
    f.close()


def get_URL(url):
    # TODO: consider handling if-none-match, or modified-since, or etag, 
    # or something similar
    # http://www.diveintopython.net/http_web_services/etags.html
    # Maybe before doing so, look into existing data and see 
    # how often the data doesn't change over a minute or over five minutes.
    # At first glance it doesn't look like the the car2go server is sending
    # either last-modified or etag, actually.

    # TODO: also support gzip, if curl doesn't for me. Connection 
    # establishment is likely to be much of the delay, but perhaps not all.

    # TODO: Maybe try to support keep-alive too? Not sure if I can do it 
    # over separate script runs...

    htime1 = time.time()

    c = pycurl.Curl()
    c.setopt(pycurl.URL, url)

    b = StringIO.StringIO()
    c.setopt(pycurl.WRITEFUNCTION, b.write)
    c.perform()

    htime2 = time.time()
    timer.append(['http get, ms', (htime2-htime1)*1000.0])

    html = b.getvalue()
    b.close()
    
    return html

def get_all_cars_text(city, force_download = False):
    json_text = None
    cache = False

    cached_data_filename = data_dir + 'current_%s' % city
    if os.path.exists(cached_data_filename) and not force_download:
        cached_data_timestamp = os.path.getmtime(cached_data_filename)
        cached_data_age = time.time() - cached_data_timestamp
        if cached_data_age < CACHE_PERIOD:
            cache = cached_data_timestamp
            timer.append(['using cached data, age in seconds', cached_data_age])
            f = open(cached_data_filename, 'r')
            json_text = f.read()
            f.close()

    if json_text == None:   
        json_text = get_URL(API_URL.replace('{loc}', city).replace('{key}', OAUTH_KEY))

    return json_text,cache

def get_electric_cars(city):
    json_text,cache = get_all_cars_text(city)

    time1 = time.time()

    cars = json.loads(json_text).get('placemarks')

    time2 = time.time()
    timer.append(['json size, kB', len(json_text)/1000.0])
    timer.append(['json load, ms', (time2-time1)*1000.0])

    electric_cars = []


    time1 = time.time()

    for car in cars:
        if car['engineType'] == 'ED':
            electric_cars.append(car)

    time2 = time.time()
    timer.append(['list search, ms', (time2-time1)*1000.0])

    return electric_cars,cache

def get_city():
    city = 'vancouver' # default to Vancouver

    # look for http param first
    # if http param not present, look for command line param
    
    param = None
    arguments = cgi.FieldStorage()

    if 'city' in arguments:
        param = str(arguments['city'].value).lower()
    elif len(sys.argv) > 1:
        param = sys.argv[1].lower()

    if param in CITIES:
        city = param

    return city

def dist(ll1, ll2):
    # adapted from http://www.movable-type.co.uk/scripts/latlong.html
    # see also http://stackoverflow.com/questions/27928/how-do-i-calculate-distance-between-two-latitude-longitude-points

    # the js equivalent of this code is used in sort.js
    # - any changes should be reflected in both

    def deg2rad(deg):
        return deg * (math.pi/180.0)

    R = 6371 # Radius of the earth in km
    dLat = deg2rad(ll2[0]-ll1[0])
    dLon = deg2rad(ll2[1]-ll1[1])

    a = math.sin(dLat/2) * math.sin(dLat/2) + \
        math.cos(deg2rad(ll1[0])) * math.cos(deg2rad(ll2[0])) * \
        math.sin(dLon/2) * math.sin(dLon/2)

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    d = R * c # distance in km
    return d

