#!/usr/bin/env python2
# coding=utf-8

from . import API_AVAILABLE_VEHICLES_URL, API_AVAILABLE_VEHICLES_HEADERS


CITIES = {
    'london': {
        'loc_key': 40758,
        'of_interest': True
    },
    'muenchen': {
        'loc_key': 4604,
        'of_interest': True
    },
    'sanfrancisco': {
        'loc_key': 4259,
        'of_interest': True
    },
    'wien': {
        'loc_key': 40468,
        'of_interest': True
    }
}

# fill in city data that can be assumed and autogenerated
for city, city_data in CITIES.items():
    if 'API_AVAILABLE_VEHICLES_URL' not in city_data and 'loc_key' in city_data:
        city_data['API_AVAILABLE_VEHICLES_URL'] = API_AVAILABLE_VEHICLES_URL(loc=city_data['loc_key'])

    if 'API_AVAILABLE_VEHICLES_HEADERS' not in city_data:
        city_data['API_AVAILABLE_VEHICLES_HEADERS'] = API_AVAILABLE_VEHICLES_HEADERS

KNOWN_CITIES = [
    city for city in CITIES
    if ('BOUNDS' in CITIES[city]
        and 'MAP_LIMITS' in CITIES[city]
        and 'DEGREE_LENGTHS' in CITIES[city]
        and 'MAP_SIZES' in CITIES[city]
        and 'LABELS' in CITIES[city])
    ]
