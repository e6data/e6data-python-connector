"""Pure scalar contracts checked against Python arithmetic and datetime."""
import datetime as dt
from decimal import Decimal

import grpc
import pytest
import pytz

from e6data_python_connector import common
from e6data_python_connector import date_time_utils as dates
from e6data_python_connector.exceptions import ProgrammingError


@pytest.mark.parametrize('numerator,denominator', [(7,3),(-7,3),(7,-3),(-7,-3),(0,3),(-6,3),(6,-3)])
def test_floor_arithmetic_matches_python(numerator, denominator):
    assert dates.floor_div(numerator, denominator) == numerator // denominator
    assert dates.floor_mod(numerator, denominator) == numerator % denominator


@pytest.mark.parametrize('micros', [0, 1, 999999, -1, -1000001, -86400000000, 946684800123000, 1709164800000000])
def test_epoch_dates_and_datetimes_match_standard_library(micros):
    expected = dt.datetime(1970,1,1,tzinfo=dt.timezone.utc) + dt.timedelta(microseconds=micros)
    assert dates.format_iso_date_from_epoch_micros(micros) == expected.date().isoformat()
    assert dates.format_iso_datetime_from_epoch_micros(micros) == expected.isoformat(timespec='milliseconds')


@pytest.mark.parametrize('year,expected', [(0,'0000'),(1,'0001'),(9999,'9999'),(10000,'+10000'),(-1,'-0001'),(-10000,'-10000')])
def test_expanded_year_format(year, expected):
    assert dates._format_iso_year(year) == expected


@pytest.mark.parametrize('offset,minutes', [('Z',0),('+05:30',330),('-03:30',-210),('+00:00',0)])
def test_timezone_offset_cache_and_numeric_application(offset, minutes):
    zone = dates.timezone_from_offset(offset)
    assert dates._tz_offset_minutes(zone) == minutes
    assert dates.timezone_from_offset(offset) is zone
    expected = (dt.datetime(1970,1,2,tzinfo=dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(minutes=minutes))))
    assert dates.format_iso_datetime_from_epoch_micros(86400000000, tz=zone) == expected.isoformat(timespec='milliseconds')
    assert dates.format_iso_datetime_from_epoch_micros(86400000000, tz=zone, separator=' ', include_millis=False, include_offset=False) == expected.strftime('%Y-%m-%d %H:%M:%S')


def test_named_timezone_and_invalid_probe():
    assert dates.timezone_from_offset('America/New_York') is pytz.timezone('America/New_York')
    assert dates._tz_offset_minutes(pytz.timezone('America/New_York'), 0) == -300
    assert dates._tz_offset_minutes(None) == 0
    assert dates._tz_offset_minutes(object()) == 0
    with pytest.raises(pytz.UnknownTimeZoneError):
        dates.timezone_from_offset('Invalid/Zone')
    with pytest.raises(ValueError):
        dates.timezone_from_offset('+25:00')


@pytest.mark.parametrize('value,expected', [(None,'%Y-%m-%d %H:%M:%S'),('','%Y-%m-%d %H:%M:%S'),('yyyy','%Y'),('MM','%m'),('dd','%d'),('HH','%H'),('mm','%M'),('ss','%S')])
def test_named_date_formats(value, expected):
    assert dates.get_format(value) == expected


def test_zone_lookup_defaults_and_unsupported_keys():
    assert dates.get_zone(None) == 'UTC'
    assert dates.get_zone('') == 'UTC'
    assert dates.get_zone('+05:30') == 'Asia/Kolkata'
    with pytest.raises(KeyError):
        dates.get_zone('unsupported')
    with pytest.raises(KeyError):
        dates.get_format('unsupported')


@pytest.mark.parametrize('value,expected', [(None,'NULL'),(5,5),(-1.5,-1.5),("O'Reilly","'O''Reilly'"),([1,None,'x'],"(1,NULL,'x')"),(dt.date(2024,2,29),"'2024-02-29'"),(dt.datetime(2024,2,29,12,30,1,120000),"'2024-02-29 12:30:01.120000'")])
def test_sql_parameter_escaping(value, expected):
    assert common.ParamEscaper().escape_item(value) == expected


def test_parameter_containers_and_errors():
    escaper=common.ParamEscaper()
    assert escaper.escape_args({'x': "'"}) == {'x': "''''"}
    assert escaper.escape_args([1,'a',None]) == (1,"'a'",'NULL')
    assert escaper.escape_string(b'caf\xc3\xa9') == "'café'"
    assert escaper.escape_sequence([]) == '()'
    assert escaper.escape_datetime(dt.datetime(2024,1,1,0,0,0,123456), escaper._DATETIME_FORMAT, cutoff=3) == "'2024-01-01 00:00:00.123'"
    with pytest.raises(ProgrammingError):
        escaper.escape_args('unsupported')
    with pytest.raises(ProgrammingError):
        escaper.escape_item(object())


def test_universal_set_and_dbapi_type_membership():
    universal=common.UniversalSet()
    assert None in universal and object() in universal
    type_object=common.DBAPITypeObject('string','varchar')
    assert type_object.__cmp__('string') == 0
    assert common.DBAPITypeObject(2).__cmp__((1,)) == 1
    assert common.DBAPITypeObject(2).__cmp__((3,)) == -1


def test_real_grpc_credentials_and_file_errors(tmp_path):
    assert isinstance(common.get_ssl_credentials(None), grpc.ChannelCredentials)
    assert isinstance(common.get_ssl_credentials(123), grpc.ChannelCredentials)
    with pytest.raises(FileNotFoundError):
        common.get_ssl_credentials(str(tmp_path/'missing.pem'))
    with pytest.raises(IsADirectoryError):
        common.get_ssl_credentials(str(tmp_path))


def test_shared_dbapi_helpers_on_real_locally_buffered_cursor():
    from collections import deque
    from e6data_python_connector.e6data_grpc import Connection, Cursor
    connection=Connection('localhost',1,access_token='unit-local-token',secure=True,auto_resume=False)
    try:
        cursor=Cursor(connection)
        common.DBAPICursor._reset_state(cursor)
        cursor._data=deque([[1,'a'],[2,'b']])
        assert common.DBAPICursor.fetchone(cursor)==[1,'a']
        assert common.DBAPICursor.fetchone(cursor)==[2,'b']
        assert common.DBAPICursor.fetchone(cursor) is None
        assert cursor.rownumber==2
        cursor.arraysize=3
        assert cursor.arraysize==3
        assert cursor.setinputsizes([int]) is None
        assert cursor.setoutputsize(128) is None
        assert common.DBAPICursor.executemany(cursor,'unused',[]) is None
        assert common.DBAPICursor.close(cursor) is None
        assert connection.check_connection()
        # Native cursor has already-consumed wire rows, so no RPC is needed.
        cursor._result_exhausted=True
        cursor._data=[[3,'c'],[4,'d']]
        assert common.DBAPICursor.fetchmany(cursor)==[[3,'c']]
        assert common.DBAPICursor.fetchall(cursor)==[[[4,'d']]]
        assert common.DBAPICursor.fetchmany(cursor)==[]
        cursor._data=[[5,'e']]
        assert iter(cursor) is cursor
        assert next(cursor)==[[5,'e']]
        with pytest.raises(StopIteration):
            next(cursor)
    finally:
        connection.close()


def test_certificate_bytes_and_path_use_real_public_ca(tmp_path):
    import ssl
    import certifi
    roots=ssl.create_default_context(cafile=certifi.where()).get_ca_certs(binary_form=True)
    assert roots, 'Installed public trust bundle must contain a CA'
    pem=ssl.DER_cert_to_PEM_cert(roots[0]).encode('ascii')
    path=tmp_path/'public-ca.pem'
    path.write_bytes(pem)
    assert isinstance(common.get_ssl_credentials(pem),grpc.ChannelCredentials)
    assert isinstance(common.get_ssl_credentials(str(path)),grpc.ChannelCredentials)
