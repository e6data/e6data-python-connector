from unittest import TestCase
from e6data_python_connector import Connection
import numpy as np

import logging

from e6data_python_connector.e6data_grpc import Matrix

logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

class MatrixTest(TestCase):
    def setUp(self) -> None:
        self._host = "localhost"
        self._catalog = "demogluecatalog"
        self._database = "ml_expts"
        logging.debug('Trying to connect to engine')
        self.e6x_connection = Connection(
            host=self._host,
            port=9020,
            username='sweta@e6x.io',
            password='Dummy@123',
            database=self._database,
            catalog=self._catalog
        )
        self.matrix_ops = Matrix(self.e6x_connection)
        logging.debug('Successfully connect to engine.')

    def disconnect(self):
        self.e6x_connection.close()
        self.assertFalse(self.e6x_connection.check_connection())

    def tearDown(self) -> None:
        self.disconnect()

    def test_matrixCompute(self):
        matrix1 = [[1, 2], [3, 4]]
        matrix2 = [[5, 6], [7, 8]]

        print("Matrix1: ", matrix1)
        print("Matrix2: ", matrix2)

        # Matrix Multiplication
        print("Matrix Multiplication:")
        self.matrix_ops.matmul(matrix1, matrix2)

        # Matrix Addition
        print("Matrix Addition:")
        self.matrix_ops.add(matrix1, matrix2)

        # Matrix Transpose
        print("Matrix Transpose:")
        self.matrix_ops.transpose(matrix1)

        # Matrix Inverse
        print("Matrix Inverse:")
        self.matrix_ops.inverse(matrix1)
