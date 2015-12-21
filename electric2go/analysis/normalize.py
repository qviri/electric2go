# coding=utf-8

import os
import sys
import codecs
from collections import defaultdict
from datetime import timedelta
import glob
import tarfile

from .cmdline import json  # will be either simplejson or json
from .. import cars, systems


def calculate_parking(data):
    data['duration'] = (data['ending_time'] - data['starting_time']).total_seconds()

    return data


def calculate_trip(trip_data):
    """
    Calculates a trip's distance, duration, speed, and fuel use.
    """

    current_trip_distance = cars.dist(trip_data['to'], trip_data['from'])
    current_trip_duration = (trip_data['ending_time'] - trip_data['starting_time']).total_seconds()

    trip_data['distance'] = current_trip_distance
    trip_data['duration'] = current_trip_duration
    if current_trip_duration > 0:
        trip_data['speed'] = current_trip_distance / (current_trip_duration / 3600.0)
    trip_data['fuel_use'] = trip_data['starting_fuel'] - trip_data['ending_fuel']

    return trip_data


def process_data(parse_module, data_time, prev_data_time, new_availability_json, unfinished_trips, unfinished_parkings):
    # get parser functions for the system
    get_cars_from_json = getattr(parse_module, 'get_cars_from_json')
    extract_car_basics = getattr(parse_module, 'extract_car_basics')
    extract_car_data = getattr(parse_module, 'extract_car_data')

    # handle outer JSON structure and get a list we can loop through
    available_cars = get_cars_from_json(new_availability_json)

    # keys that are handled explicitly within the loop
    RECOGNIZED_KEYS = ['vin', 'lat', 'lng', 'fuel']

    # ignored keys that should not be tracked for trips - stuff that won't change during a trip
    IGNORED_KEYS = ['name', 'license_plate', 'address', 'model', 'color', 'fuel_type', 'transmission']

    if len(available_cars):
        # assume all cars will have same key structure (otherwise we'd have merged systems), and look at first one
        OTHER_KEYS = [key for key in extract_car_data(available_cars[0]).keys()
                      if key not in RECOGNIZED_KEYS and key not in IGNORED_KEYS]

    # unfinished_trips and unfinished_parkings come from params, are updated, then returned
    unstarted_potential_trips = {}  # to be returned
    finished_trips = {}  # to be returned
    finished_parkings = {}  # to be returned

    # called by start_parking, end_trip, and end_unstarted_trip
    def process_car(car_info):
        new_car_data = extract_car_data(car_info)  # get full car info
        result = {'vin': new_car_data['vin'],
                  'coords': (new_car_data['lat'], new_car_data['lng']),
                  'fuel': new_car_data['fuel']}

        for key in OTHER_KEYS:
            result[key] = new_car_data[key]

        return result

    def start_parking(curr_time, new_car_data):
        result = process_car(new_car_data)

        # car properties will not change during a parking period, so we don't need to save any
        # starting/ending pairs except for starting_time and ending_time
        result['starting_time'] = curr_time

        return result

    def end_parking(prev_time, unfinished_parking):
        result = dict.copy(unfinished_parking)

        result['ending_time'] = prev_time
        result = calculate_parking(result)

        return result

    def start_trip(curr_time, starting_car_info):
        result = dict.copy(starting_car_info)

        result['from'] = starting_car_info['coords']
        del result['coords']
        result['starting_time'] = curr_time
        del result['ending_time']
        result['starting_fuel'] = result['fuel']
        del result['fuel']

        return result

    def end_trip(prev_time, ending_car_info, unfinished_trip):
        new_car_data = process_car(ending_car_info)

        trip_data = unfinished_trip
        trip_data['to'] = new_car_data['coords']
        trip_data['ending_time'] = prev_time
        trip_data['ending_fuel'] = new_car_data['fuel']

        trip_data = calculate_trip(trip_data)

        trip_data['start'] = {}
        trip_data['end'] = {}
        for key in OTHER_KEYS:
            trip_data['start'][key] = unfinished_trip[key]
            trip_data['end'][key] = new_car_data[key]
            del trip_data[key]

        return trip_data

    def end_unstarted_trip(prev_time, ending_car_info):
        # essentially the same as end_trip except all bits that depend on
        # unfinished_trip have been removed
        trip_data = process_car(ending_car_info)

        trip_data['ending_time'] = prev_time
        trip_data['to'] = trip_data['coords']
        del trip_data['coords']
        trip_data['ending_fuel'] = trip_data['fuel']
        del trip_data['fuel']

        trip_data['end'] = {}
        for key in OTHER_KEYS:
            trip_data['end'][key] = trip_data[key]
            del trip_data[key]

        return trip_data

    """
    Set this up as a defacto state machine with two states.
    A car is either in parking or in motion. These are stored in unfinished_parkings and unfinished_trips respectively.

    Based on a cycle's data:
    - a car might finish a trip: it then is removed from unfinished_trips, is added to unfinished_parkings, and
      added to finished_trips.
    - a car might start a trip: it is then removed from unfinished_parkings, is added to unfinished_trips, and
      added to finished_parkings

    There are some special cases: a 1-cycle-long trip which causes a car to flip out of and back into
    unfinished_parkings, and initialization of a "new" car (treated as finishing an "unstarted" trip, since if it
    wasn't on a trip it would have been in unfinished_parkings before).

    data_time is when we know about a car's position; prev_data_time is the previous cycle.
    A parking period starts on data_time and ends on prev_data_time.
    A trip starts on prev_data_time and ends on data_time.
    """

    available_vins = set()
    for car in available_cars:

        vin, lat, lng = extract_car_basics(car)
        available_vins.add(vin)

        # most of the time, none of these conditionals will be processed - most cars park for much more than one cycle

        if vin not in unfinished_parkings and vin not in unfinished_trips:
            # returning from an unknown trip, the first time we're seeing the car

            unstarted_potential_trips[vin] = end_unstarted_trip(data_time, car)

            unfinished_parkings[vin] = start_parking(data_time, car)

        if vin in unfinished_trips:
            # trip has just finished

            finished_trips[vin] = end_trip(data_time, car, unfinished_trips[vin])
            del unfinished_trips[vin]

            unfinished_parkings[vin] = start_parking(data_time, car)

        elif vin in unfinished_parkings and (lat != unfinished_parkings[vin]['coords'][0] or lng != unfinished_parkings[vin]['coords'][1]):
            # car has moved but the "trip" took exactly 1 cycle. consequently unfinished_trips and finished_parkings
            # were never created in vins_that_just_became_unavailable loop. need to handle this manually

            # end previous parking and start trip
            finished_parkings[vin] = end_parking(prev_data_time, unfinished_parkings[vin])
            trip_data = start_trip(prev_data_time, finished_parkings[vin])

            # end trip right away and start 'new' parking period in new position
            finished_trips[vin] = end_trip(data_time, car, trip_data)
            unfinished_parkings[vin] = start_parking(data_time, car)

    vins_that_just_became_unavailable = set(unfinished_parkings.keys()) - available_vins
    for vin in vins_that_just_became_unavailable:
        # trip has just started

        finished_parkings[vin] = end_parking(prev_data_time, unfinished_parkings[vin])
        del unfinished_parkings[vin]

        unfinished_trips[vin] = start_trip(prev_data_time, finished_parkings[vin])

    return finished_trips, finished_parkings, unfinished_trips, unfinished_parkings, unstarted_potential_trips


def get_city_and_time_from_filename(filename):
    city, leftover = filename.rsplit('_', 1)

    # don't use splitext so we correctly handle filenames with multiple dots
    # like wien_2015-06-19.tar.gz
    parts = leftover.split('.', 1)

    if len(parts) == 2 and not parts[0].endswith('--00-00'):
        # replace file extension with 00:00 if needed
        leftover = leftover.replace('.' + parts[1], '--00-00')

    file_time = cars.parse_date(leftover)

    return city, file_time


def batch_load_data(system, city, location, starting_time, ending_time, time_step):
    def load_data_from_file(city, t, file_dir):
        filename = cars.get_file_name(city, t)
        filepath_to_load = os.path.join(file_dir, filename)

        try:
            with open(filepath_to_load, 'r') as f:
                result = json.load(f)
            return result
        except (IOError, ValueError):
            # return False if file does not exist or is malformed
            return False

    def load_data_from_tar(city, t, archive):
        # TODO: whole structure for loading files can be much improved.
        # Study implementation for tarfile and see how to best use it.
        # Also add zipfile support.

        filename = cars.get_file_name(city, t)

        try:
            # extractfile doesn't support "with" syntax :(
            f = archive.extractfile(location_prefix + filename)

            # TODO: about half of run time is spent in reading in this file and doing json.load
            # I can't do much about json.load, but I could see if I can somehow preload the files
            # so that it doesn't have to do stupid things like checking for each file or seeking to it manually

            try:
                reader = codecs.getreader('utf-8')
                result = json.load(reader(f))
            except ValueError:
                # return False if file is not valid JSON
                result = False

            f.close()

            return result
        except KeyError:
            # return False if file is not in the archive
            return False

    # get parser functions for the correct system
    try:
        parse_module = systems.get_parser(system)
    except ImportError:
        sys.exit('unsupported system {system_name}'.format(system_name=system))

    # vary function based on file_dir / location. if location is an archive file,
    # preload the archive and have the function read files from there
    location_prefix = ''
    if os.path.isfile(location) and tarfile.is_tarfile(location):
        load_data_point = load_data_from_tar

        location = tarfile.open(location)

        # Get time of last data point.
        # This implementation assumes that files in the tarfile
        # are in alphabetical/chronological order. This assumption
        # holds for my data scripts
        last_file_name = location.getnames()[-1]
        _, last_file_time = get_city_and_time_from_filename(last_file_name)

        # handle file name prefixes like "./vancouver_2015-06-19--00-00"
        location_prefix = last_file_name.split(city)[0]
    else:
        load_data_point = load_data_from_file

        # Get time of last data point.
        # First search for all files matching naming scheme
        # for the current city, then find its max date - Python's
        # directory lists all return in arbitrary order.
        mask = cars.FILENAME_MASK.format(city=city)
        matching_files = glob.glob(os.path.join(location, mask))

        last_file_time = max(get_city_and_time_from_filename(filename)[1]
                             for filename in matching_files)

    if not ending_time or ending_time > last_file_time:
        # If ending_time not provided, scan until we get to the last file.
        # If provided, check if it is earlier than data actually available;
        # if not, only use what is available
        ending_time = last_file_time

    # t will be the time of the current iteration
    t = starting_time

    # prev_t will be the time of the previous *good* dataset.
    # In the very first iteration of main loop, value of prev_t is not used.
    # This initial value will be only used when there is no data at all,
    # in which case it'll become the ending_time. We want ending_time
    # to be at least somewhat useful, so assign t.
    prev_t = starting_time

    # These two dicts contain ongoing record of things that are happening.
    # The dicts are modified in each iteration as cars' trips and parkings
    # end or start.
    unfinished_trips = {}
    unfinished_parkings = {}

    # These are built up as we iterate, and only appended to.
    unstarted_trips = {}
    finished_trips = defaultdict(list)
    finished_parkings = defaultdict(list)
    missing_data_points = []

    # Loop until we get to end of dataset or until the limit requested.
    while t <= ending_time:
        # get current time's data
        data = load_data_point(city, t, location)

        if data:
            new_finished_trips, new_finished_parkings, unfinished_trips, unfinished_parkings, unstarted_trips_this_round =\
                process_data(parse_module, t, prev_t, data, unfinished_trips, unfinished_parkings)

            # update data dictionaries
            unstarted_trips.update(unstarted_trips_this_round)
            for vin in new_finished_parkings:
                finished_parkings[vin].append(new_finished_parkings[vin])
            for vin in new_finished_trips:
                finished_trips[vin].append(new_finished_trips[vin])

            prev_t = t
            """ prev_t is now last data point that was successfully loaded.
            This means that the first good frame after some bad frames
            (that were skipped) will have process_data with t and prev_t
            separated by more than 1 time_step.
            For example, consider the following dataset:
                data
                data <- trip starts
                data
                data
                data
                missing
                missing
                data <- trip seen to end
                data
            We could assume trip took 6 time_steps, or 4 time_steps - either
            is defensible.
            I've decided on interpretation resulting in 6 in the past, so I'll
            stick with that. """

        else:
            # Data file not found or was malformed, report it as missing.
            missing_data_points.append(t)

        # get next data time according to provided time_step
        t += timedelta(seconds=time_step)

    # actual_ending_time is the actual ending time of the resulting dataset,
    # that is, the last valid data point found.
    # Not necessarily the same as input ending_time - files could have ran out
    # before we got to input ending_time, or the last file could have been
    # malformed.
    actual_ending_time = prev_t

    result = {
        'finished_trips': finished_trips,
        'finished_parkings': finished_parkings,
        'unfinished_trips': unfinished_trips,
        'unfinished_parkings': unfinished_parkings,
        'unstarted_trips': unstarted_trips,
        'metadata': {
            'system': system,
            'city': city,
            'starting_time': starting_time,
            'ending_time': actual_ending_time,
            'time_step': time_step,
            'missing': missing_data_points
        }
    }

    return result
