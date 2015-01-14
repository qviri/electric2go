#!/usr/bin/env python2
# coding=utf-8

import os
import stat
import argparse
import copy
import shutil
import simplejson as json
from datetime import datetime, timedelta
import time

import cars
from city import KNOWN_CITIES
from car2goprocess import stats as process_stats, graph as process_graph, dump as process_dump


timer = []
DEBUG = False


def process_data(json_data, data_time = None, previous_data = {}, **extra_args):
    data = previous_data
    trips = []
    positions = []

    for vin in data.keys():
        # need to reset out status for cases where cars are picked up 
        # (and therefore disappear from json_data) before two cycles 
        # of process_data. otherwise their just_moved is never updated.
        # if necessary, just_moved will be set to true later
        data[vin]['just_moved'] = False

    for car in json_data:
        if 'vin' in car:
            vin = car['vin']
            name = car['name']
            lat = car['coordinates'][1]
            lng = car['coordinates'][0]
        else:
            # no recognized data in this file
            continue

        position_data = {'coords': [lat, lng], 'metadata': {}}

        if vin in previous_data:
            if not (data[vin]['coords'][0] == lat and data[vin]['coords'][1] == lng):
                # car has moved since last known position
                prev_coords = data[vin]['coords']
                prev_seen = data[vin]['seen']
                data[vin]['coords'] = [lat, lng]
                data[vin]['seen'] = data_time
                data[vin]['just_moved'] = True

                if 'fuel' in data[vin]:
                    prev_fuel = data[vin]['fuel']
                    data[vin]['fuel'] = car['fuel']
                    fuel_use = prev_fuel - car['fuel']

                current_trip_distance = cars.dist(data[vin]['coords'], prev_coords)
                current_trip_duration = (data_time - prev_seen).total_seconds()

                trip_data = {
                    'vin': vin,
                    'from': prev_coords,
                    'to': data[vin]['coords'],
                    'starting_time': prev_seen,
                    'ending_time': data[vin]['seen'],
                    'distance': current_trip_distance,
                    'duration': current_trip_duration,
                    'fuel_use': 0
                    }
                if 'fuel' in data[vin]:
                    trip_data['starting_fuel'] = prev_fuel
                    trip_data['ending_fuel'] = data[vin]['fuel']
                    trip_data['fuel_use'] = fuel_use

                data[vin]['most_recent_trip'] = trip_data

                if current_trip_duration > 0:
                    data[vin]['speed'] = current_trip_distance / (current_trip_duration / 3600.0)
                    position_data['metadata']['speed'] = data[vin]['speed']

                trips.append(trip_data)
                
            else:
                # car has not moved from last known position. just update time last seen
                data[vin]['seen'] = data_time
                data[vin]['just_moved'] = False
        else:
            # 'new' car showing up, initialize it
            data[vin] = {'name': name, 'coords': [lat, lng], 'seen': data_time,
                'just_moved': False}
            if 'fuel' in car:
                data[vin]['fuel'] = car['fuel']

        positions.append(position_data)

    return data, positions, trips

def batch_process(city, starting_time, dry = False, make_iterations = True, \
    show_move_lines = True, max_files = False, max_skip = 0, file_dir = '', \
    time_step = cars.DATA_COLLECTION_INTERVAL_MINUTES, \
    show_speeds = False, symbol = '.', \
    distance = False, time_offset = 0, web = False, stats = False, \
    trace = False, dump_trips = False, dump_vehicle = False, \
    all_positions_image = False, \
    **extra_args):

    args = locals()

    global timer, DEBUG

    def get_filepath(city, t, file_dir):
        filename = cars.filename_format % (city, t.year, t.month, t.day, t.hour, t.minute)

        return os.path.join(file_dir, filename)

    def load_file(filepath):
        if not os.path.exists(filepath):
            return False

        f = open(filepath, 'r')
        json_text = f.read()
        f.close()

        try:
            return json.loads(json_text)
        except:
            return False

    i = 1
    t = starting_time
    filepath = get_filepath(city, starting_time, file_dir)

    data_frames = []
    all_trips = []
    all_positions = []
    trips_by_vin = {}

    # TODO: the loop below should now be pretty easy to extract as a function

    saved_data = {}

    json_data = load_file(filepath)

    # loop as long as new files exist
    # if we have a limit specified, loop only until limit is reached
    while json_data != False and (max_files is False or i <= max_files):
        time_process_start = time.time()

        print t,

        if 'placemarks' in json_data:
            json_data = json_data['placemarks']

        saved_data, current_positions, current_trips = process_data(json_data, t, saved_data,
            **args)
        print 'total known: %d' % len(saved_data),
        print 'moved: %02d' % len(current_trips)

        timer.append((filepath + ': process_data, ms',
             (time.time()-time_process_start)*1000.0))

        time_organize_start = time.time()

        for vin in saved_data:
            if vin not in trips_by_vin:
                trips_by_vin[vin] = []

            if saved_data[vin]['just_moved']:
                trips_by_vin[vin].append(copy.deepcopy(saved_data[vin]['most_recent_trip']))

        data_frames.append((t, filepath, current_positions, current_trips))

        all_trips.extend(current_trips)
        all_positions.extend(current_positions)

        timer.append((filepath + ': organize data, ms',
             (time.time()-time_organize_start)*1000.0))

        # find next file according to provided time_step (or default,
        # which is the cars.DATA_COLLECTION_INTERVAL_MINUTES const)
        i = i + 1
        t = t + timedelta(0, time_step*60)
        filepath = get_filepath(city, t, file_dir)

        json_data = load_file(filepath)

        if json_data == False:
            print 'would stop at %s' % filepath

        skipped = 0
        next_t = t
        while json_data == False and skipped < max_skip:
            # this will detect and attempt to counteract missing or malformed 
            # data files, unless instructed otherwise by max_skip = 0
            skipped += 1

            next_t = next_t + timedelta(0, time_step*60)
            next_filepath = get_filepath(city, next_t, file_dir)
            next_json_data = load_file(next_filepath)

            print 'trying %s...' % next_filepath ,

            if next_json_data != False:
                print 'exists, using it instead' ,
                shutil.copy2(next_filepath, filepath)
                json_data = load_file(filepath)

            print

        timer.append((filepath + ': batch_process total load loop, ms',
             (time.time()-time_process_start)*1000.0))

        if DEBUG:
            print '\n'.join(l[0] + ': ' + str(l[1]) for l in timer)

        # reset timer to only keep information about one file at a time
        timer = []

    ending_time = data_frames[-1][0]  # complements starting_time from function params

    # set up params for iteratively-named images
    animation_files_filename = datetime.now().strftime('%Y%m%d-%H%M') + \
        '-' + os.path.basename(filepath)
    animation_files_prefix = os.path.join(os.path.dirname(filepath), 
        animation_files_filename)
    iter_filenames = []

    # generate images
    if not dry:
        for index, data in enumerate(data_frames):
            turn, filepath, current_positions, current_trips = data
            
            # reset timer to only keep information about one file at a time
            timer = []
            process_graph.timer = []

            second_filename = False
            if make_iterations:
                second_filename = animation_files_prefix + '_' + \
                    str(index).rjust(3, '0') + '.png'
                iter_filenames.append(second_filename)

            time_graph_start = time.time()

            process_graph.make_graph(positions = current_positions, trips = current_trips,
                first_filename = filepath, turn = turn,
                second_filename = second_filename, **args)

            time_graph = (time.time() - time_graph_start) * 1000.0
            timer.append((filepath + ': make_graph, ms', time_graph))

            print turn, 'generated graph in %d ms' % time_graph

            if DEBUG:
                print '\n'.join(l[0] + ': ' + str(l[1]) for l in process_graph.timer)
                print '\n'.join(l[0] + ': ' + str(l[1]) for l in timer)

    # print animation information if applicable
    if make_iterations and not dry:
        if web:
            crush_commands = []

            crushed_dir = animation_files_prefix + '-crushed'
            if not os.path.exists(crushed_dir):
                os.makedirs(crushed_dir)

            for filename in iter_filenames:
                crush_commands.append('pngcrush %s %s' % (filename, 
                    os.path.join(crushed_dir, os.path.basename(filename))))

            crush_filebasename = animation_files_prefix
            f = open(crush_filebasename + '-pngcrush', 'w')
            print >> f, '\n'.join(crush_commands)
            os.chmod(crush_filebasename + '-pngcrush', 
                stat.S_IRUSR|stat.S_IWUSR|stat.S_IXUSR)
            f.close()

            f = open(crush_filebasename + '-filenames', 'w')
            print >> f, json.dumps(iter_filenames)
            f.close()

            print '\nto pngcrush:'
            print './%s-pngcrush' % crush_filebasename

        background_path = os.path.relpath(os.path.join(cars.root_dir,
            'backgrounds/', '%s-background.png' % city))
        png_filepaths = animation_files_prefix + '_%03d.png'
        mp4_path = animation_files_prefix + '.mp4'

        framerate = 8
        frames = i - 1
        if time_step < 5:
            framerate = 30
            # for framerates over 25, avconv assumes conversion from 25 fps
            frames = (frames/25)*30

        print '\nto animate:'
        print '''avconv -loop 1 -r %d -i %s -vf 'movie=%s [over], [in][over] overlay' -b 15360000 -frames %d %s''' % (framerate, background_path, png_filepaths, frames, mp4_path)
        # if i wanted to invoke this, just do os.system('avconv...')

    if all_positions_image:
        process_graph.make_positions_graph(city, all_positions, all_positions_image)

    if trace:
        print
        print process_stats.trace_vehicle(trips_by_vin, trace)

    if stats:
        print
        process_stats.print_stats(all_trips, trips_by_vin.keys(), starting_time, ending_time)

    if dump_trips:
        filename = dump_trips
        process_dump.dump_trips(all_trips, filename)

    if dump_vehicle:
        process_dump.dump_vehicle(trips_by_vin, dump_vehicle)

    if DEBUG:
        print '\n'.join(l[0] + ': ' + str(l[1]) for l in process_graph.timer)
        print '\n'.join(l[0] + ': ' + str(l[1]) for l in timer)

    print

def process_commandline():
    global DEBUG

    parser = argparse.ArgumentParser()
    parser.add_argument('starting_filename', type=str,
        help='name of first file to process')
    parser.add_argument('-dry', action='store_true',
        help='dry run: do not generate any images')
    parser.add_argument('-s', '--stats', action='store_true',
        help='generate and print some basic statistics about car2go use')
    parser.add_argument('-t', '--trace', type=str, default=False,
        help='print out all trips of a vehicle found in the dataset; \
            accepts license plates, VINs, \
            "random", "most_trips", "most_distance", and "most_duration"')
    parser.add_argument('-dt', '--dump-trips', type=str, default=False,
        help='dump JSON of all trips to filename passed as param')
    parser.add_argument('-dv', '--dump-vehicle', type=str, default=False,
        help='specify vehicle''s VIN to get a JSON of its trips written \
            to file named {vin}_trips.json')
    parser.add_argument('-tz', '--time-offset', type=int, default=0,
        help='offset times shown on graphs by TIME_OFFSET hours')
    parser.add_argument('-d', '--distance', type=float, default=False,
        help='mark distance of DISTANCE meters from nearest car on map')
    parser.add_argument('-noiter', '--no-iter', action='store_true', 
        help='do not create consecutively-named files for animating')
    parser.add_argument('-ap', '--all-positions-image', type=str, default=False,
        help='create image of all vehicle positions in the dataset \
            and save to ALL_POSITIONS_IMAGE')
    parser.add_argument('-web', action='store_true',
        help='create pngcrush script and JS filelist for HTML animation \
            page use; forces NO_ITER to false')
    parser.add_argument('-nolines', '--no-lines', action='store_true',
        help='do not show lines indicating vehicles\' moves')
    parser.add_argument('-max', '--max-files', type=int, default=False,
        help='limit maximum amount of files to process')
    parser.add_argument('-skip', '--max-skip', type=int, default=3,
        help='amount of missing or malformed sequential data files to try to \
            work around (default 3; specify 0 to work only on data provided)')
    parser.add_argument('-step', '--time-step', type=int,
        default=cars.DATA_COLLECTION_INTERVAL_MINUTES,
        help='analyze data for every TIME_STEP minutes (default %i)' %
            cars.DATA_COLLECTION_INTERVAL_MINUTES)
    parser.add_argument('-speeds', '--show_speeds', action='store_true', 
        help='indicate vehicles\' speeds in addition to locations') 
    parser.add_argument('-symbol', type=str, default='.',
        help='matplotlib symbol to indicate vehicles on the graph \
            (default \'.\', larger \'o\')')
    parser.add_argument('-debug', action='store_true',
        help='print extra debug and timing messages')

    args = parser.parse_args()
    params = vars(args)

    DEBUG = args.debug
    filename = args.starting_filename

    city,starting_time = filename.rsplit('_', 1)

    # strip off directory, if any.
    file_dir,city = os.path.split(city.lower())

    if not os.path.exists(filename):
        print 'file not found: ' + filename
        return

    if not city in KNOWN_CITIES:
        print 'unsupported city: ' + city
        return

    try:
        # parse out starting time
        starting_time = datetime.strptime(starting_time, '%Y-%m-%d--%H-%M')
    except:
        print 'time format not recognized: ' + filename
        return

    params['starting_time'] = starting_time
    params['make_iterations'] = not args.no_iter
    params['show_move_lines'] = not args.no_lines

    params['city'] = city
    params['file_dir'] = file_dir

    if args.web is True:
        params['make_iterations'] = True

    batch_process(**params)


if __name__ == '__main__':
    process_commandline()

