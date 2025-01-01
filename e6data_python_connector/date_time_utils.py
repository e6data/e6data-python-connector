from typing import Final
import pytz


FORMATS = {
    "yyyy": "%Y",
    "dd": "%d",
    "MM": "%m",
    "HH": "%H",
    "mm": "%M",
    "ss": "%S"
}

zone_map: Final = dict()


def floor_div(x, y):
    q = x // y
    if x ^ y < 0 and q * y != x:
        return q - 1
    return q


def floor_mod(x, y):
    r = x % y
    if (x ^ y) < 0 and r != 0:
        return r + y
    return r


def timezone_from_offset(offset_string) -> pytz:
    # Parse the offset string into hours and minutes
    sign = -1 if offset_string[0] == "-" else 1
    if ":" in offset_string:
        if offset_string in zone_map:
            return zone_map[offset_string]
        with_out_sign = offset_string[1:]
        hours_minutes = with_out_sign.split(":")
        hours = int(hours_minutes[0])
        minutes = int(hours_minutes[1])
        total_minutes = (hours * 60 + minutes) * sign
        fixed_offset = pytz.FixedOffset(total_minutes)
        zone_map[offset_string] = fixed_offset
        return pytz.FixedOffset(total_minutes)
    else:
        return pytz.UTC if offset_string == 'Z' else pytz.timezone(offset_string)


def get_format(str_format):
    if str_format is None or len(str_format) == 0:
        return "%Y-%m-%d %H:%M:%S"
    return FORMATS[str_format]
