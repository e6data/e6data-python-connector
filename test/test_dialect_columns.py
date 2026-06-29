import unittest
from unittest.mock import patch

from sqlalchemy import types

from e6data_python_connector import dialect as dialect_module
from e6data_python_connector.dialect import (
    E6dataDate,
    E6dataDecimal,
    E6dataDialect,
    E6dataTimestamp,
)


class FakeClient(object):
    def __init__(self, columns):
        self.columns = columns
        self.calls = []

    def get_columns(self, catalog, schema, table_name):
        self.calls.append((catalog, schema, table_name))
        return self.columns


class FakeCursorOwner(object):
    def __init__(self, client):
        self.client = client

    def cursor(self, catalog_name=None):
        return FakeCursor(self.client)


class FakeCursor(object):
    def __init__(self, client):
        self.connection = client


class FakeSQLAlchemyConnection(object):
    def __init__(self, client):
        self.connection = FakeCursorOwner(client)


class TestDialectGetColumns(unittest.TestCase):
    def test_get_columns_maps_each_reflected_column_to_its_own_sqlalchemy_type(self):
        client = FakeClient([
            {"fieldName": "id", "fieldType": "integer"},
            {"fieldName": "customer_name", "fieldType": "varchar"},
            {"fieldName": "amount", "fieldType": "decimal"},
            {"fieldName": "created_on", "fieldType": "date"},
            {"fieldName": "created_at", "fieldType": "timestamp"},
        ])
        connection = FakeSQLAlchemyConnection(client)
        dialect = E6dataDialect()
        dialect.catalog_name = "lakehouse"

        with patch.object(dialect_module, "Connection", FakeSQLAlchemyConnection):
            columns = dialect.get_columns(connection, "orders", "sales")

        self.assertEqual(
            ["id", "customer_name", "amount", "created_on", "created_at"],
            [column["name"] for column in columns],
        )
        self.assertEqual([("lakehouse", "sales", "orders")], client.calls)
        self.assertIs(columns[0]["type"], types.Integer)
        self.assertIs(columns[1]["type"], types.String)
        self.assertIs(columns[2]["type"], E6dataDecimal)
        self.assertIs(columns[3]["type"], E6dataDate)
        self.assertIs(columns[4]["type"], E6dataTimestamp)

    def test_get_columns_defaults_unknown_e6data_type_to_string(self):
        client = FakeClient([
            {"fieldName": "payload", "fieldType": "variant"},
        ])
        connection = FakeSQLAlchemyConnection(client)
        dialect = E6dataDialect()
        dialect.catalog_name = "lakehouse"

        with patch.object(dialect_module, "Connection", FakeSQLAlchemyConnection):
            columns = dialect.get_columns(connection, "events", "sales")

        self.assertEqual("payload", columns[0]["name"])
        self.assertIs(columns[0]["type"], types.String)


if __name__ == "__main__":
    unittest.main()
