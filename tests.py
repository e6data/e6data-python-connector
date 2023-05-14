import csv
import os
import time
from unittest import TestCase
import e6xdb.e6x as edb
import json
import logging

logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


class TestE6X(TestCase):
    def setUp(self) -> None:
        self._host = os.environ.get('ENGINE_IP')
        self._database = os.environ.get('DB_NAME')
        self.e6x_connection = None
        logging.debug('Trying to connect to engine host {}, database {}.'.format(self._host, self._database))
        self.e6x_connection = edb.connect(
            host=self._host,
            port=9000,
            username='vishal@e6x.io',
            database=self._database,
            password='75cei^%$TREdgfhU&T^RTYDrchfgvjy65dhcgf',
        )
        logging.debug('Successfully to connect to engine.')

    def test_connection(self):
        self.assertIsNotNone(self.e6x_connection, 'Unable to connect.')

    def disconnect(self):
        self.e6x_connection.close()
        self.assertFalse(self.e6x_connection.check_connection())

    def test_query_1(self):
        sql = 'select 1'
        logging.debug('Executing query: {}'.format(sql))
        cursor = self.e6x_connection.cursor()
        query_id = cursor.execute(sql)
        logging.debug('Query Id {}'.format(query_id))
        self.assertIsNotNone(query_id)
        records = cursor.fetchall()
        self.assertIn(1, records[0])
        cursor.clear()
        self.e6x_connection.close()

    def test_query_2(self):
        sql = "select timestamp_add('year',2,current_date())"
        logging.debug('Executing query: {}'.format(sql))
        cursor = self.e6x_connection.cursor()
        query_id = cursor.execute(sql)
        logging.debug('Query Id {}'.format(query_id))
        self.assertIsNotNone(query_id)
        records = cursor.fetchall()
        cursor.clear()
        self.assertEqual(1, len(records))
        self.e6x_connection.close()

    def test_query_3_fetch_one(self):
        sql = "select * from date_dim limit 3"
        logging.debug('Executing query: {}'.format(sql))
        cursor = self.e6x_connection.cursor()
        query_id = cursor.execute(sql)
        logging.debug('Query Id {}'.format(query_id))
        self.assertIsNotNone(query_id)
        records = cursor.fetchone()
        cursor.clear()
        self.assertEqual(1, len(records))
        self.e6x_connection.close()

    def test_query_4_fetch_many(self):
        sql = "select * from date_dim limit 3"
        logging.debug('Executing query: {}'.format(sql))
        cursor = self.e6x_connection.cursor()
        query_id = cursor.execute(sql)
        logging.debug('Query Id {}'.format(query_id))
        self.assertIsNotNone(query_id)
        records = cursor.fetchmany(1)
        cursor.clear()
        self.assertEqual(1, len(records))
        self.e6x_connection.close()

    def test_query_5_dry_run(self):
        sql = "select * from date_dim limit 3"
        logging.debug('Executing query: {}'.format(sql))
        response = self.e6x_connection.dry_run(sql)
        self.assertIsNotNone(response)
        self.e6x_connection.close()

    def test_query_5_caches(self):
        sql = "select * from date_dim limit 3"
        logging.debug('Executing query: {}'.format(sql))
        self.e6x_connection.set_prop_map(json.dumps(dict(USE_QUERY_RESULT_CACHE=True)))
        cursor = self.e6x_connection.cursor()
        query_id = cursor.execute(sql)
        logging.debug('Query Id {}'.format(query_id))
        self.assertIsNotNone(query_id)
        records = cursor.fetchall()
        self.e6x_connection.set_prop_map(json.dumps(dict(USE_QUERY_RESULT_CACHE=False)))
        now = time.time()
        query_id = cursor.execute(sql)
        logging.debug('Query Id {}'.format(query_id))
        records = cursor.fetchall()
        print('After cache, execution time', time.time() - now)
        cursor.clear()
        self.e6x_connection.close()

    def test_query_6_explain_analyse(self):
        sql = "select * from date_dim limit 3"
        logging.debug('Executing query: {}'.format(sql))
        cursor = self.e6x_connection.cursor()
        query_id = cursor.execute(sql)
        cursor.explain_analyse()
        self.e6x_connection.close()

    def test_query_7_explain(self):
        sql = "select * from date_dim limit 3"
        logging.debug('Executing query: {}'.format(sql))
        cursor = self.e6x_connection.cursor()
        query_id = cursor.execute(sql)
        cursor.explain()
        self.e6x_connection.close()

    def tearDown(self) -> None:
        self.disconnect()

    def test_get_query_list_from_csv_file(self):
        query_path = os.getenv("QUERY_PATH") or './query_file.csv'
        query_column_name = os.getenv("QUERY_CSV_COLUMN_NAME") or 'QUERY'
        logging.debug('Query path found: {}'.format(query_path))
        if query_path:
            if not query_path.endswith('.csv'):
                raise Exception('Invalid QUERY_PATH: Only CSV file is supported.')
            local_file_path = query_path
            data = list()
            with open(local_file_path, 'r') as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    data.append({
                        'query': row.get(query_column_name),
                        'query_id': row.get('QUERY_ID') or None,
                    })
            for row in data:
                sql = row.get("query")
                logging.debug('Executing query: {}'.format(sql))
                cursor = self.e6x_connection.cursor()
                query_id = cursor.execute(sql)
                logging.debug('Query Id {}'.format(query_id))
                self.assertIsNotNone(query_id)
                records = cursor.fetchall()
                self.assertGreater(len(records[0]), 0)
