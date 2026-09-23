"""Bounded, read-only SQL Server table scan for the local execution adapter."""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import math
import re
import uuid

MAX_ROWS = 1_000_000
MAX_COLUMNS = 500
_NAME = re.compile(r"[^\x00-\x1f\x7f;]{1,128}\Z")
_SERVER = re.compile(r"(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)\Z")
_USER = re.compile(r"[A-Za-z0-9_@.\\$-]{1,128}\Z")
_GUID = re.compile(r"[0-9a-fA-F-]{36}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def name(value, label):
    require(isinstance(value, str) and bool(_NAME.fullmatch(value)) and value.strip() == value,
            f"Invalid SQL {label}")
    return value


def quote(value):
    return "[" + name(value, "identifier").replace("]", "]]" ) + "]"


def connection_string(connection):
    """Construct only known ODBC keywords; never accept a raw connection string."""
    require(isinstance(connection, dict), "SQL connection must be an object")
    require(set(connection) <= {"server", "port", "database", "authentication"}, "Unsupported SQL connection setting")
    server = connection.get("server")
    require(isinstance(server, str) and bool(_SERVER.fullmatch(server)) and ".." not in server,
            "Use one DNS server name or IPv4 address")
    database = name(connection.get("database"), "database name")
    port = connection.get("port", 1433)
    require(type(port) is int and 1 <= port <= 65535, "Invalid SQL port")
    auth = connection.get("authentication")
    require(isinstance(auth, dict), "Choose one SQL authentication method")
    method = auth.get("method")
    parts = [f"Server=tcp:{server},{port}", f"Database={{{database.replace('}', '}}')}}}",
             "Encrypt=yes", "TrustServerCertificate=no", "ApplicationIntent=ReadOnly"]
    if method == "sql-password":
        require(set(auth) == {"method", "username", "password"}, "SQL password authentication requires username and password")
        username = auth["username"]
        require(isinstance(username, str) and bool(_USER.fullmatch(username)), "Invalid SQL username")
        password = auth["password"]
        require(isinstance(password, str) and 0 < len(password) <= 4096 and "\x00" not in password,
                "Missing or invalid SQL password secret")
        parts.extend([f"UID={username}", "PWD={" + password.replace("}", "}}") + "}"])
    elif method == "entra-default":
        require(set(auth) == {"method"}, "Unsupported Entra default authentication setting")
        parts.append("Authentication=ActiveDirectoryDefault")
    elif method == "entra-managed-identity":
        require(set(auth) <= {"method", "client_id"}, "Unsupported managed identity setting")
        parts.append("Authentication=ActiveDirectoryMSI")
        if "client_id" in auth:
            require(isinstance(auth["client_id"], str) and bool(_GUID.fullmatch(auth["client_id"])),
                    "Managed identity client_id must be a UUID")
            parts.append(f"UID={auth['client_id']}")
    elif method == "entra-service-principal":
        require(set(auth) == {"method", "client_id", "client_secret"}, "Service principal requires client_id and client_secret")
        require(isinstance(auth["client_id"], str) and bool(_GUID.fullmatch(auth["client_id"])),
                "Service principal client_id must be a UUID")
        secret = auth["client_secret"]
        require(isinstance(secret, str) and 0 < len(secret) <= 4096 and "\x00" not in secret,
                "Missing or invalid service principal secret")
        parts.extend(["Authentication=ActiveDirectoryServicePrincipal", f"UID={auth['client_id']}",
                      "PWD={" + secret.replace("}", "}}") + "}"])
    else:
        raise ValueError("Unsupported SQL authentication method")
    return ";".join(parts) + ";"


def source_object(settings):
    require(isinstance(settings, dict) and set(settings) == {"object", "connection"},
            "SQL settings require object and connection")
    obj = settings["object"]
    require(isinstance(obj, dict) and {"schema", "table"} <= set(obj) <= {"schema", "table", "columns"},
            "Select one SQL schema and table")
    schema, table = name(obj["schema"], "schema"), name(obj["table"], "table")
    columns = obj.get("columns")
    if columns is not None:
        require(isinstance(columns, list) and 1 <= len(columns) <= MAX_COLUMNS,
                "Choose 1–500 distinct SQL columns")
        columns = [name(c, "column") for c in columns]
        require(len(columns) == len(set(columns)), "Choose 1–500 distinct SQL columns")
    return schema, table, columns


def column_type(type_name, precision, scale):
    kind = type_name.lower()
    if kind in {"tinyint", "smallint", "int", "bigint"}: return "integer"
    if kind == "bit": return "boolean"
    if kind in {"decimal", "numeric", "money", "smallmoney"}: return "number"
    if kind in {"float", "real"}: return "number"
    if kind in {"char", "varchar", "nchar", "nvarchar", "text", "ntext", "xml", "uniqueidentifier",
                "date", "time", "datetime", "datetime2", "smalldatetime", "datetimeoffset"}: return "string"
    raise ValueError(f"Unsupported SQL column type: {kind}; select supported columns explicitly")


def metadata(cursor, schema, table, selected):
    cursor.execute("""SELECT c.name, ty.name, c.precision, c.scale, c.is_nullable
        FROM sys.tables AS t
        JOIN sys.schemas AS s ON s.schema_id = t.schema_id
        JOIN sys.columns AS c ON c.object_id = t.object_id
        JOIN sys.types AS ty ON ty.user_type_id = c.user_type_id
        WHERE s.name = ? AND t.name = ? ORDER BY c.column_id""", (schema, table))
    rows = cursor.fetchall()
    require(rows, "SQL table absent or metadata not visible to this identity")
    names = [r[0] for r in rows]
    require(len(names) == len(set(names)), "Duplicate SQL column name")
    chosen = selected or names
    require(len(chosen) <= MAX_COLUMNS and set(chosen) <= set(names), "Selected SQL column missing")
    by_name = {r[0]: r for r in rows}
    result = []
    for column in chosen:
        r = by_name[column]
        result.append((column, column_type(r[1], r[2], r[3]), bool(r[4])))
    return result


def wire_value(value, kind):
    if value is None: return None
    if isinstance(value, Decimal) and kind == "number": return value
    if isinstance(value, (datetime, date, time)): return value.isoformat()
    if isinstance(value, uuid.UUID): return str(value)
    if kind == "boolean" and isinstance(value, (bool, int)): return bool(value)
    if kind == "integer" and type(value) is int: return value
    if kind == "number" and type(value) in (int, float):
        require(math.isfinite(value), "Nonfinite SQL numeric value")
        return value
    if kind == "string" and isinstance(value, str): return value
    raise ValueError("SQL row value differs from discovered type")


def scan(settings, emit=None, connect=None):
    """Discover a single table and optionally emit at most MAX_ROWS records."""
    schema, table, selected = source_object(settings)
    conn_string = connection_string(settings["connection"])
    if connect is None:
        import mssql_python
        connect = mssql_python.connect
    try:
        db = connect(conn_string, timeout=65)
    except Exception:
        raise ValueError("SQL connection failed; check access, credentials and TLS") from None
    try:
        cursor = db.cursor()
        fields = metadata(cursor, schema, table, selected)
        properties = {column: {"type": ["null", kind] if nullable else [kind]}
                      for column, kind, nullable in fields}
        result_schema = {"type": "object", "properties": properties,
                         "required": [c for c, _, nullable in fields if not nullable],
                         "additionalProperties": False}
        count = 0
        if emit is not None:
            projection = ", ".join(quote(c) for c, _, _ in fields)
            cursor.execute(f"SELECT TOP ({MAX_ROWS + 1}) {projection} FROM {quote(schema)}.{quote(table)}")
            while True:
                rows = cursor.fetchmany(1000)
                if not rows: break
                for row in rows:
                    count += 1
                    require(count <= MAX_ROWS, "SQL source exceeds one million rows")
                    require(len(row) == len(fields), "SQL row shape changed")
                    emit({field[0]: wire_value(value, field[1]) for field, value in zip(fields, row)})
        return result_schema, count
    except ValueError:
        raise
    except Exception:
        raise ValueError("SQL read failed; check table permissions and source availability") from None
    finally:
        db.close()
