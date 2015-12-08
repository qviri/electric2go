# coding=utf-8

from __future__ import unicode_literals

from os import path


try:
    with open(path.join(path.dirname(__file__), 'api_key'), 'r') as f:
        API_KEY = f.read().strip()
except IOError:
    API_KEY = 'adf51226795afbc4e7575ccc124face7'  # default key used by drivenow.com


CITIES = {
    'berlin': {
        'loc_key': 6099,
        'electric': 'some'
    },
    'kobenhavn': {
        'loc_key': 41369,
        'electric': 'all',
        'display': 'Copenhagen'
    },
    'duesseldorf': {
        'loc_key': 1293,
        'display': 'Düsseldorf',
    },
    'hamburg': {
        'loc_key': 40065,
        'electric': 'some'
    },
    'koeln': {
        'loc_key': 1774,
        'display': 'Cologne',
        'localized': {
            'de': 'Köln'
        }
    },
    'london': {
        'loc_key': 40758,
        'electric': 'some',
        'BOUNDS': {
            'NORTH': 51.612,  # exact value is 51.611141
            'SOUTH': 51.518,  # exact value is 51.518598
            'EAST': 0.022,  # exact value is 0.021994
            'WEST': -0.165  # exact value is -0.164666
        },
        'MAP_LIMITS': {
            # http://render.openstreetmap.org/cgi-bin/export?bbox=-0.20593,51.518,0.06293,51.612&scale=55659&format=png
            'NORTH': 51.612,
            'SOUTH': 51.518,
            'EAST': 0.06293,
            'WEST': -0.20593
        },
        'DEGREE_LENGTHS': {
            # for latitude 51.56
            'LENGTH_OF_LATITUDE': 111258.94,
            'LENGTH_OF_LONGITUDE': 69349.27
        },
        'MAP_SIZES': {
            'MAP_X': 1920,
            'MAP_Y': 1080
        },
        'LABELS': {
            'fontsizes': [35, 22, 30, 18],
            'lines': [
                (250, 210),
                (250, 170),
                (250, 130),
                (250, 95)
            ]
        }
    },
    'muenchen': {
        'loc_key': 4604,
        'electric': 'some',
        'display': 'Munich',
        'localized': {
            'de': 'München'
        }
    },
    'stockholm': {
        'loc_key': 42128
    },
    'wien': {
        'loc_key': 40468,
        'display': 'Vienna',
        'localized': {
            'de': 'Wien'
        }
    }
}

API_AVAILABLE_VEHICLES_URL = 'https://api2.drive-now.com/cities/{loc}?expand=full'

# fill in city data that can be assumed and autogenerated
for city, city_data in CITIES.items():
    city_data['of_interest'] = True  # we want everything for now

    if 'API_AVAILABLE_VEHICLES_URL' not in city_data:
        city_data['API_AVAILABLE_VEHICLES_URL'] = API_AVAILABLE_VEHICLES_URL.format(loc=city_data['loc_key'])

    if 'API_AVAILABLE_VEHICLES_HEADERS' not in city_data:
        city_data['API_AVAILABLE_VEHICLES_HEADERS'] = {'X-Api-Key': API_KEY}