#!/usr/bin/env python2
# coding=utf-8

import datetime
import json


def trips_offset_tz(trips, tz_offset):
    for trip in trips:
        offset = datetime.timedelta(hours=tz_offset)
        trip['starting_time'] = trip['starting_time'] + offset
        trip['ending_time'] = trip['ending_time'] + offset

    return trips


def json_serializer(obj):
    # default doesn't serialize dates... tell it to use isoformat()
    # syntax from http://blog.codevariety.com/2012/01/06/python-serializing-dates-datetime-datetime-into-json/
    return obj.isoformat() if hasattr(obj, 'isoformat') else obj


def dump_trips(all_trips, filename, tz_offset):
    if tz_offset != 0:
        # adjust timezone if needed
        all_trips = trips_offset_tz(all_trips, tz_offset)

    with open(filename, 'w') as f:
        json.dump(all_trips, f, default=json_serializer, indent=2)
