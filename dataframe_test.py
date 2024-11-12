from unittest import TestCase
from e6data_python_connector import Connection

import logging

logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

class TestDataFrame(TestCase):
    def setUp(self) -> None:
        self._host = "localhost"
        self._catalog = "demogluecatalog"
        self._database = "tpcds_1000_delta"
        logging.debug('Trying to connect to engine')
        self.e6x_connection = Connection(
            host=self._host,
            port=9001,
            username='limbad@e6x.io',
            password='Dummy@123',
            database=self._database,
            catalog=self._catalog
        )
        logging.debug('Successfully connect to engine.')

    def disconnect(self):
        self.e6x_connection.close()
        self.assertFalse(self.e6x_connection.check_connection())

    def tearDown(self) -> None:
        self.disconnect()

    def test_table_creation(self):
        self._dataframe = self.e6x_connection.load_parquet('<parquet_file_path>')
        self._dataframe.select('col1','col1','colN')

        rows = self._dataframe.show()

        for row in rows:
            print(row)

