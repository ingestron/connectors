"""Bounded, read-only table scans for PostgreSQL, MySQL and Oracle (PB-064 phase 3).

One DB-API path with a dialect table: metadata query, type mapping, identifier
quoting, row limit and driver connection. Drivers: pg8000 (BSD-3-Clause),
PyMySQL (MIT) and python-oracledb thin mode (UPL-1.0 or Apache-2.0); none needs
a native client. Values are checked against the discovered type on every row.
"""
from __future__ import annotations

from datetime import date, datetime, time
from temporal_types import TemporalError
from decimal import Decimal
import math
import re
import uuid

MAX_ROWS = 1_000_000
MAX_COLUMNS = 500
_NAME = re.compile(r"[^\x00-\x1f\x7f;]{1,128}\Z")
_HOST = re.compile(r"(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)\Z")
_USER = re.compile(r"[A-Za-z0-9_@.$-]{1,128}\Z")


class DatabaseSourceError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def name(value, label):
    require(isinstance(value, str) and _NAME.fullmatch(value), f"Invalid {label}")
    return value


def temporal_type(dialect, source_type, scale):
    """Source-native metadata only; scan wire schemas keep JSON string types."""
    kind = source_type.lower()
    if dialect == 'postgresql':
        if kind == 'date': return 'date'
        if kind == 'timestamp without time zone':
            if scale is not None and not 0 <= int(scale) <= 6:
                raise TemporalError('TEMPORAL_PRECISION')
            return 'timestamp'
    elif dialect == 'mysql':
        if kind == 'date': return 'date'
        if kind == 'datetime':
            if scale is not None and not 0 <= int(scale) <= 6:
                raise TemporalError('TEMPORAL_PRECISION')
            return 'timestamp'
        # MySQL TIMESTAMP is session-timezone dependent; preserve its STRING policy.
    elif dialect == 'oracle':
        if kind == 'date': return 'timestamp'  # Oracle DATE includes time of day.
        if kind.startswith('timestamp'):
            match = re.fullmatch(r'timestamp(?:\(([0-9])\))?', kind)
            if match is None:
                raise TemporalError('TEMPORAL_TIMEZONE')
            fraction = int(match[1]) if match[1] is not None else (int(scale) if scale is not None else 6)
            if not 0 <= fraction <= 6 or (scale is not None and int(scale) != fraction):
                raise TemporalError('TEMPORAL_PRECISION')
            return 'timestamp'
    return 'string'


def _postgres_type(t, precision, scale):
    temporal_type("postgresql", t, scale)
    t = t.lower()
    if t in {"smallint", "integer", "bigint"}: return "integer"
    if t in {"numeric", "real", "double precision", "money"}: return "number"
    if t == "boolean": return "boolean"
    if t in {"text", "character varying", "character", "uuid", "date", "time without time zone",
             "time with time zone", "timestamp without time zone", "timestamp with time zone"}:
        return "string"
    raise ValueError(f"Unsupported PostgreSQL column type: {t}; select supported columns explicitly")


def _mysql_type(t, precision, scale):
    temporal_type("mysql", t, scale)
    t = t.lower()
    if t in {"tinyint", "smallint", "mediumint", "int", "bigint"}: return "integer"
    if t in {"decimal", "float", "double"}: return "number"
    if t in {"char", "varchar", "tinytext", "text", "mediumtext", "longtext", "enum", "set",
             "date", "datetime", "timestamp", "time", "year"}: return "string"
    raise ValueError(f"Unsupported MySQL column type: {t}; select supported columns explicitly")


def _oracle_type(t, precision, scale):
    temporal_type("oracle", t, scale)
    t = re.sub(r"\(.*", "", t.upper())
    if t == "NUMBER": return "integer" if scale == 0 else "number"
    if t in {"FLOAT", "BINARY_FLOAT", "BINARY_DOUBLE"}: return "number"
    if t in {"VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR", "CLOB", "NCLOB", "DATE", "TIMESTAMP"}:
        return "string"
    raise ValueError(f"Unsupported Oracle column type: {t}; select supported columns explicitly")


def _pg_connect(c):
    import pg8000.dbapi
    import ssl
    return pg8000.dbapi.connect(
        host=c["host"], port=c.get("port", 5432), database=c["database"], user=c["user"],
        password=c["password"], timeout=65,
        ssl_context=ssl.create_default_context() if c.get("tls", "require") == "require" else None)


def _mysql_connect(c):
    import pymysql
    import ssl
    return pymysql.connect(
        host=c["host"], port=c.get("port", 3306), database=c["database"], user=c["user"],
        password=c["password"], connect_timeout=65, read_timeout=3600,
        ssl=ssl.create_default_context() if c.get("tls", "require") == "require" else None)


def _oracle_connect(c):
    import oracledb
    oracledb.defaults.fetch_decimals = True
    protocol = "tcps" if c.get("tls", "require") == "require" else "tcp"
    return oracledb.connect(user=c["user"], password=c["password"],
                            dsn=f"{protocol}://{c['host']}:{c.get('port', 1521)}/{c['service']}",
                            tcp_connect_timeout=65)


DIALECTS = {
    "postgresql": {
        "label": "PostgreSQL",
        "quote": lambda n: '"' + name(n, "identifier").replace('"', '""') + '"',
        "metadata": """SELECT column_name, data_type, numeric_precision, CASE WHEN data_type IN ('timestamp without time zone', 'timestamp with time zone', 'time without time zone', 'time with time zone') THEN datetime_precision ELSE numeric_scale END, is_nullable
            FROM information_schema.columns WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position""",
        "nullable": lambda v: v == "YES",
        "type": _postgres_type,
        "limit": lambda sql, n: f"{sql} LIMIT {n}",
        "connect": _pg_connect,
        "keys": """SELECT kcu.column_name FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name
            AND kcu.table_schema = tc.table_schema AND kcu.table_name = tc.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = %s AND tc.table_name = %s""",
        "database_key": "database",
    },
    "mysql": {
        "label": "MySQL",
        "quote": lambda n: "`" + name(n, "identifier").replace("`", "``") + "`",
        "metadata": """SELECT COLUMN_NAME, DATA_TYPE, NUMERIC_PRECISION, CASE WHEN DATA_TYPE IN ('datetime', 'timestamp', 'time') THEN DATETIME_PRECISION ELSE NUMERIC_SCALE END, IS_NULLABLE
            FROM information_schema.columns WHERE table_schema = %s AND table_name = %s
            ORDER BY ORDINAL_POSITION""",
        "nullable": lambda v: v == "YES",
        "type": _mysql_type,
        "limit": lambda sql, n: f"{sql} LIMIT {n}",
        "connect": _mysql_connect,
        "keys": """SELECT COLUMN_NAME FROM information_schema.key_column_usage
            WHERE CONSTRAINT_NAME = 'PRIMARY' AND TABLE_SCHEMA = %s AND TABLE_NAME = %s""",
        "database_key": "database",
    },
    "oracle": {
        "label": "Oracle",
        "quote": lambda n: '"' + name(n, "identifier").replace('"', '""') + '"',
        "metadata": """SELECT column_name, data_type, data_precision, data_scale, nullable
            FROM all_tab_columns WHERE owner = :1 AND table_name = :2 ORDER BY column_id""",
        "nullable": lambda v: v == "Y",
        "type": _oracle_type,
        "limit": lambda sql, n: f"{sql} FETCH FIRST {n} ROWS ONLY",
        "connect": _oracle_connect,
        "keys": """SELECT cols.column_name FROM all_constraints cons JOIN all_cons_columns cols
            ON cols.owner = cons.owner AND cols.constraint_name = cons.constraint_name
            WHERE cons.constraint_type = 'P' AND cons.owner = :1 AND cons.table_name = :2""",
        "database_key": "service",
    },
}


def connection_settings(dialect, connection):
    """Validate one connection's settings; secrets are already resolved."""
    d = DIALECTS[dialect]
    key = d["database_key"]
    require(isinstance(connection, dict)
            and {"host", key, "user", "password"} <= set(connection)
            <= {"host", "port", key, "user", "password", "tls"},
            f"{d['label']} connection needs host, {key}, user and password; optional port and tls")
    require(isinstance(connection["host"], str) and _HOST.fullmatch(connection["host"]),
            f"Invalid {d['label']} host")
    require(isinstance(connection["user"], str) and _USER.fullmatch(connection["user"]),
            f"Invalid {d['label']} user")
    require(isinstance(connection["password"], str) and 0 < len(connection["password"]) <= 1024,
            f"{d['label']} password must come from a secret reference")
    name(connection[key], key)
    require(type(connection.get("port", 1)) is int and 1 <= connection.get("port", 1) <= 65535,
            "Invalid port")
    require(connection.get("tls", "require") in ("require", "disable"),
            "tls must be require or disable")
    return connection


def wire_value(value, kind):
    if value is None: return None
    if isinstance(value, Decimal) and kind in ("number", "integer"):
        if kind == "integer":
            require(value == value.to_integral_value(), "Database row value differs from discovered type")
            return int(value)
        return value
    if isinstance(value, (datetime, date, time)): return value.isoformat()
    if isinstance(value, uuid.UUID): return str(value)
    if kind == "boolean" and isinstance(value, (bool, int)): return bool(value)
    if kind == "integer" and type(value) is int: return value
    if kind == "number" and type(value) in (int, float):
        require(math.isfinite(value), "Nonfinite database numeric value")
        return value
    if kind == "string" and isinstance(value, str): return value
    raise ValueError("Database row value differs from discovered type")


def catalogue(dialect, connection, table, connect=None):
    """Every column with its type, nullability and primary key; unsupported types are marked."""
    d = DIALECTS[dialect]
    schema, tname = name(table["schema"], "schema"), name(table["table"], "table")
    try:
        db = (connect or d["connect"])(connection)
    except Exception:
        raise DatabaseSourceError("DB_CONNECT", "Database connection failed") from None
    try:
        cursor = db.cursor()
        cursor.execute(d["metadata"], (schema, tname))
        rows = cursor.fetchall()
        if not rows:
            raise DatabaseSourceError("DB_TABLE", "Table absent or metadata not visible")
        cursor.execute(d["keys"], (schema, tname))
        keys = {r[0] for r in cursor.fetchall()}
        columns = []
        for column, source_type, precision, scale, nullable in rows:
            entry = {"name": column, "nullable": d["nullable"](nullable), "sourceType": str(source_type)}
            try:
                kind = d["type"](source_type, precision, scale)
                temporal = temporal_type(dialect, source_type, scale)
                entry["type"] = temporal if temporal != "string" else kind
                if temporal == "timestamp" and scale is not None:
                    entry["sourceType"] = str(source_type) if "(" in str(source_type) else f"{source_type}({int(scale)})"
                if kind == "number" and scale is not None and precision is not None and int(scale) > 0:
                    entry.update(type="decimal", precision=int(precision), scale=int(scale))
            except ValueError:
                entry.update(type="string", supported=False)
            if column in keys: entry["key"] = True
            columns.append(entry)
        return columns
    except DatabaseSourceError:
        raise
    except Exception:
        raise DatabaseSourceError("DB_READ", "Database read failed") from None
    finally:
        db.close()


def scan(dialect, connection, table, emit=None, connect=None):
    """Discover one table and optionally emit at most MAX_ROWS records."""
    d = DIALECTS[dialect]
    schema, tname = name(table["schema"], "schema"), name(table["table"], "table")
    selected = table.get("columns")
    incremental = table.get('incremental')
    if incremental is not None:
        require(isinstance(incremental, dict) and {'watermark', 'initial', 'consistency'} <= set(incremental)
                <= {'watermark', 'initial', 'consistency', 'batchSize'}
                and incremental['consistency'] == 'ordered-committed-append', 'Use an explicit ordered committed append policy')
        name(incremental['watermark'], 'watermark column')
        require(type(incremental['initial']) is int and 0 <= incremental['initial'] <= 9007199254740991,
                'Initial cursor must be an exact nonnegative JSON integer')
        require(type(incremental.get('batchSize', 100000)) is int and 1 <= incremental.get('batchSize', 100000) <= MAX_ROWS,
                'Incremental batch size must be 1..1000000')
    require(selected is None or (isinstance(selected, list) and 1 <= len(selected) <= MAX_COLUMNS
                                 and len(selected) == len(set(selected))),
            f"Choose 1–{MAX_COLUMNS} distinct columns")
    try:
        db = (connect or d["connect"])(connection)
    except Exception:
        raise DatabaseSourceError("DB_CONNECT", "Database connection failed") from None
    try:
        cursor = db.cursor()
        cursor.execute(d["metadata"], (schema, tname))
        rows = cursor.fetchall()
        if not rows:
            raise DatabaseSourceError("DB_TABLE", "Table absent or metadata not visible")
        by_name = {r[0]: r for r in rows}
        require(len(by_name) == len(rows), "Duplicate column name")
        chosen = selected or [r[0] for r in rows]
        require(set(chosen) <= set(by_name), "Selected column missing")
        fields = [(c, d["type"](by_name[c][1], by_name[c][2], by_name[c][3]),
                   d["nullable"](by_name[c][4])) for c in chosen]
        lower = None
        if incremental is not None:
            watermark = incremental['watermark']
            require(any(c == watermark and k == 'integer' and not nullable for c, k, nullable in fields),
                    'Select a required integer watermark column in the reviewed contract')
            cursor.execute(d['keys'], (schema, tname))
            require([r[0] for r in cursor.fetchall()] == [watermark],
                    'The watermark must be the single-column source primary key')
            raw_cursor = table.get('lowerCursor', incremental['initial'])
            require(type(raw_cursor) is int or isinstance(raw_cursor, str) and re.fullmatch(r'0|[1-9][0-9]{0,18}', raw_cursor),
                    'Invalid restored incremental cursor')
            lower = int(raw_cursor)
            require(incremental['initial'] <= lower <= 9223372036854775807,
                    'Invalid restored incremental cursor')
        schema_json = {"type": "object",
                       "properties": {c: {"type": ["null", k] if n else [k]} for c, k, n in fields},
                       "required": [c for c, _, n in fields if not n],
                       "additionalProperties": False}
        count = 0
        if emit is not None:
            quote = d["quote"]
            batch_size = incremental.get('batchSize', 100000) if incremental is not None else MAX_ROWS
            sql = f"SELECT {', '.join(quote(c) for c, _, _ in fields)} FROM {quote(schema)}.{quote(tname)}"
            if incremental is not None:
                sql += f" WHERE {quote(watermark)} > {':1' if dialect == 'oracle' else '%s'} ORDER BY {quote(watermark)}"
            sql = d['limit'](sql, batch_size + 1)
            if incremental is not None: cursor.execute(sql, (lower,))
            else: cursor.execute(sql)
            next_cursor, has_more = lower, False
            while True:
                batch = cursor.fetchmany(1000)
                if not batch: break
                for row in batch:
                    require(len(row) == len(fields), "Row shape changed")
                    record = {f[0]: wire_value(v, f[1]) for f, v in zip(fields, row)}
                    if incremental is not None:
                        value = record[watermark]
                        require(type(value) is int and next_cursor < value <= 9223372036854775807,
                                'Source violated the ordered integer append policy')
                        if count == batch_size:
                            has_more = True
                            break
                        next_cursor = value
                    count += 1
                    require(count <= MAX_ROWS, "Source exceeds one million rows")
                    emit(record)
                if has_more: break
            if incremental is not None: table.update(nextCursor=next_cursor, hasMore=has_more)
        return schema_json, count
    except (ValueError, DatabaseSourceError):
        raise
    except Exception:
        raise DatabaseSourceError("DB_READ", "Database read failed") from None
    finally:
        db.close()
