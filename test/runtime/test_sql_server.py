from pathlib import Path
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))
from sql_server_reader import scan, connection_string, quote, MAX_ROWS


class Cursor:
    def __init__(self, metadata_rows, data_rows):
        self.metadata_rows = metadata_rows
        self.data_rows = data_rows
        self.sql = []
        self.position = 0

    def execute(self, query, parameters=None):
        self.sql.append((query, parameters))

    def fetchall(self):
        return self.metadata_rows

    def fetchmany(self, size):
        batch = self.data_rows[self.position:self.position + size]
        self.position += len(batch)
        return batch


class Database:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


def settings(method="sql-password"):
    auth = {"method": method}
    if method == "sql-password": auth.update(username="reader", password="a};pwd}")
    if method == "entra-service-principal": auth.update(client_id="12345678-1234-1234-1234-123456789012", client_secret="secret")
    return {"object": {"schema": "dbo", "table": "Order Details", "columns": ["OrderID", "UnitPrice"]},
            "connection": {"server": "example.database.windows.net", "database": "northwind", "authentication": auth}}


class SqlServer(unittest.TestCase):
    def test_auth_modes_and_secret_escaping(self):
        sql = connection_string(settings()["connection"])
        self.assertIn("PWD={a}};pwd}}}", sql)
        self.assertIn("Encrypt=yes;TrustServerCertificate=no", sql)
        for method, expected in [("entra-default", "ActiveDirectoryDefault"),
                                 ("entra-managed-identity", "ActiveDirectoryMSI"),
                                 ("entra-service-principal", "ActiveDirectoryServicePrincipal")]:
            with self.subTest(method=method):
                self.assertIn(expected, connection_string(settings(method)["connection"]))
        with self.assertRaises(ValueError):
            connection_string({**settings()["connection"], "trustServerCertificate": True})
        with self.assertRaises(ValueError):
            connection_string({**settings()["connection"], "server": "server;Encrypt=no"})
        with self.assertRaises(ValueError):
            connection_string({**settings()["connection"], "authentication": {"method": "entra-password"}})

    def test_projection_sql_is_quoted_and_metadata_is_parameterised(self):
        cursor = Cursor([("OrderID", "int", 10, 0, False),
                         ("UnitPrice", "money", 19, 4, True)],
                        [(1, Decimal("12.50")), (2, None)])
        database = Database(cursor)
        rows = []
        schema, count = scan(settings(), rows.append, lambda *_args, **_kwargs: database)
        self.assertEqual(rows, [{"OrderID": 1, "UnitPrice": Decimal("12.50")},
                                {"OrderID": 2, "UnitPrice": None}])
        self.assertEqual(count, 2)
        self.assertEqual(schema["required"], ["OrderID"])
        self.assertEqual(cursor.sql[0][1], ("dbo", "Order Details"))
        self.assertIn("FROM [dbo].[Order Details]", cursor.sql[1][0])
        self.assertIn(f"TOP ({MAX_ROWS + 1})", cursor.sql[1][0])
        self.assertTrue(database.closed)
        self.assertEqual(quote("x]y"), "[x]]y]")

    def test_unsupported_column_and_source_bounds_fail_closed(self):
        cursor = Cursor([("Photo", "image", 0, 0, True)], [])
        database = Database(cursor)
        cfg = settings(); cfg["object"].pop("columns")
        with self.assertRaisesRegex(ValueError, "Unsupported SQL column type"):
            scan(cfg, connect=lambda *_args, **_kwargs: database)
        self.assertTrue(database.closed)
        cfg = settings(); cfg["object"]["columns"] = ["OrderID", "OrderID"]
        with self.assertRaises(ValueError): scan(cfg, connect=lambda *_args, **_kwargs: database)
        cfg = settings(); cfg["object"]["columns"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "column missing"):
            scan(cfg, connect=lambda *_args, **_kwargs: database)


if __name__ == "__main__": unittest.main()
