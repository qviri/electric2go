#!/usr/bin/env python2
# coding=utf-8

from __future__ import print_function
import os
import sys
import copy
import simplejson as json
from collections import defaultdict
from datetime import timedelta
import time

import cars


DEBUG = False


def get_filepath(city, t, file_dir):
    city_obj = {'name': city}
    filename = cars.get_file_name(city_obj, t)

    return os.path.join(file_dir, filename)


def process_data(system, data_time, prev_data_time, new_availability_json, unfinished_trips, unfinished_parkings):
    # get functions for the correct system
    parse_module = cars.get_carshare_system_module(system_name=system, module_name='parse')
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
        result = copy.deepcopy(unfinished_parking)

        # save duration
        result['ending_time'] = prev_time
        result['duration'] = (result['ending_time'] - result['starting_time']).total_seconds()

        return result

    def start_trip(curr_time, starting_car_info):
        result = copy.deepcopy(starting_car_info)

        result['from'] = starting_car_info['coords']
        del result['coords']
        result['starting_time'] = curr_time
        result['starting_fuel'] = result['fuel']
        del result['fuel']

        return result

    def end_trip(prev_time, ending_car_info, unfinished_trip):
        new_car_data = process_car(ending_car_info)

        current_trip_distance = cars.dist(new_car_data['coords'], unfinished_trip['from'])
        current_trip_duration = (prev_time - unfinished_trip['starting_time']).total_seconds()

        trip_data = unfinished_trip
        trip_data['to'] = new_car_data['coords']
        trip_data['ending_time'] = prev_time
        trip_data['distance'] = current_trip_distance
        trip_data['duration'] = current_trip_duration
        if current_trip_duration > 0:
            trip_data['speed'] = current_trip_distance / (current_trip_duration / 3600.0)
        trip_data['ending_fuel'] = new_car_data['fuel']
        trip_data['fuel_use'] = unfinished_trip['starting_fuel'] - new_car_data['fuel']

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

            # TODO: try to filter lapsed reservations - 30 minutes exactly is now the most common trip duration when binned to closest 5 minutes
            # - check directly - and try to guess if it's a lapsed reservation (fuel use? but check 29, 31 minute trips to
            # see if their fuel use isn't usually 0 either)

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


def batch_load_data(system, city, file_dir, starting_time, time_step, max_files, max_skip):
    global DEBUG

    timer = []

    def load_file(filepath_to_load):
        try:
            with open(filepath_to_load, 'r') as f:
                result = json.load(f)
            return result
        except:
            # return False if file does not exist or is malformed
            return False

    i = 1
    t = starting_time
    prev_t = t
    filepath = get_filepath(city, starting_time, file_dir)

    unfinished_trips = {}
    unfinished_parkings = {}
    unstarted_trips = {}

    finished_trips = defaultdict(list)
    finished_parkings = defaultdict(list)

    missing_files = []

    json_data = load_file(filepath)
    # loop as long as new files exist
    # if we have a limit specified, loop only until limit is reached
    while json_data != False and (max_files is False or i <= max_files):
        time_process_start = time.time()

        new_finished_trips, new_finished_parkings, unfinished_trips, unfinished_parkings, unstarted_trips_this_round =\
            process_data(system, t, prev_t, json_data, unfinished_trips, unfinished_parkings)

        # update data dictionaries

        unstarted_trips.update(unstarted_trips_this_round)

        for vin in new_finished_parkings:
            finished_parkings[vin].append(new_finished_parkings[vin])

        for vin in new_finished_trips:
            finished_trips[vin].append(new_finished_trips[vin])

        timer.append((filepath + ': batch_load_data process_data, ms',
             (time.time()-time_process_start)*1000.0))

        # find next file according to provided time_step (or default,
        # which is the cars.DATA_COLLECTION_INTERVAL_MINUTES const)

        prev_t = t  # prev_t is now last file that was successfully loaded

        # detect and attempt to counteract missing or malformed
        # data files, unless instructed otherwise by max_skip = 0
        # TODO: while loop in a while loop... can probably be done cleaner
        skipped = -1
        potentially_missing = []
        while skipped < max_skip and (skipped == -1 or not json_data):
            # loop for a minimum of one time, then until either json_data is valid
            # or we've reached the max_skip limit

            i += 1
            t += timedelta(minutes=time_step)
            filepath = get_filepath(city, t, file_dir)
            json_data = load_file(filepath)

            if not json_data:
                # file found was not valid, try to skip past it
                print('file %s is missing or malformed' % filepath, file=sys.stderr)
                potentially_missing.append(filepath)

                skipped = skipped + 1 if skipped > 0 else 1  # handle the initial -1
            else:
                # we've found a valid file, indicate we can end loop
                skipped = max_skip

        # if we got out of the loop after finding a file that works,
        # save files that we skipped
        if json_data:
            missing_files.extend(potentially_missing)

        timer.append((filepath + ': batch_load_data total load loop, ms',
             (time.time()-time_process_start)*1000.0))

        if DEBUG:
            print('\n'.join(l[0] + ': ' + str(l[1]) for l in timer), file=sys.stderr)

        # reset timer to only keep information about one file at a time
        timer = []

    ending_time = prev_t  # complements starting_time from function params

    result = {
        'finished_trips': finished_trips,
        'finished_parkings': finished_parkings,
        'unfinished_trips': unfinished_trips,
        'unfinished_parkings': unfinished_parkings,
        'unstarted_trips': unstarted_trips,
        'metadata': {
            'starting_time': starting_time,
            'ending_time': ending_time,
            'time_step': time_step*60,
            'missing': missing_files
        }
    }

    return result
