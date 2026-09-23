from pathlib import Path
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))
from sql_server_reader import scan, connection_string, quote, MAX_ROWS
import singer_runtime
original_runtime = (singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review)
sys.modules["snapshot_runtime"] = singer_runtime
import sql_server_runtime as runtime
singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review = original_runtime


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
    def test_multi_table_binding_and_reviewed_streams(self):
        project = {"tables": {
            "products": {"source": {"schema": "dbo", "table": "Products", "stream": "products"},
                         "columns": [{"name": "ProductID"}]},
            "orders": {"source": {"schema": "sales", "table": "Orders", "stream": "orders"},
                       "columns": [{"name": "OrderID"}]},
        }}
        config = {"sourceSettings": {"connection": {"server": "example.database.windows.net"}},
                  "projectLock": project}
        source = runtime.source_config(config)
        self.assertEqual(source["objects"]["products"],
                         {"schema": "dbo", "table": "Products", "columns": ["ProductID"]})
        self.assertEqual(source["objects"]["orders"]["columns"], ["OrderID"])
        schema = {"type": "object", "properties": {"id": {"type": ["integer"]}}}
        def fake_scan(settings, emit=None):
            if emit: emit({"id": 1 if settings["object"]["table"] == "Products" else 2})
            return schema, 1 if emit else 0
        with patch.object(runtime, "scan", side_effect=fake_scan) as scanned:
            catalog = json.loads(b"".join(runtime.sql_output(None, source, None, 10, True)))
            self.assertEqual([s["tap_stream_id"] for s in catalog["streams"]],
                             ["products", "orders"])
            for stream in catalog["streams"]:
                stream["metadata"] = [{"breadcrumb": [], "metadata": {"selected": True}}]
            output = b"".join(runtime.sql_output(None, source, catalog, 10)).decode().splitlines()
            self.assertEqual([json.loads(line)["stream"] for line in output],
                             ["products", "orders", "products", "orders"])
            self.assertEqual(scanned.call_count, 4)
        with self.assertRaisesRegex(ValueError, "Review every table"):
            runtime.sql_review({"catalog": catalog}, {"products": {}})
        project["tables"]["orders"]["source"]["table"] = "Other"
        with self.assertRaisesRegex(ValueError, "stream identity"):
            runtime.source_config({**config, "projectLock": {"tables": {"orders": {
                **project["tables"]["orders"],
                "source": {**project["tables"]["orders"]["source"], "stream": "wrong"}}}}})

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
