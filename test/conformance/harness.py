"""Connector conformance suite (PB-064 phase 3).

Every table connector passes the same checks before release. A test module
subclasses Conformance and supplies a fixture; the suite drives the connector
through the kit's wiring (source_config, discovery, read) exactly as the runtime
does, so passing here means the connector honours the interface contract.

Fixture methods:
    make_connector()          the connector instance (installed through the kit)
    settings()                connection settings for sourceSettings
    tables()                  {stream: {'source': {...}, 'columns': [...]}}
    load(stream, rows)        make the source table hold these rows
    rows(stream)              a few representative rows for that table
    change_schema(stream)     make the source table's schema differ
    break_source(stream)      make reading that table fail
    secret_values()           strings that must never appear in errors
"""
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import singer_runtime
# Bundles ship the shared runtime as snapshot_runtime.py.
sys.modules.setdefault('snapshot_runtime', singer_runtime)
_original = (singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review)
import connector_kit as kit


class Conformance:
    """Mix into unittest.TestCase with the fixture methods above."""

    def setUp(self):
        self.connector = self.make_connector()
        kit.install(self.connector)
        # Installing patches the shared module; restore it for other tests.
        self.addCleanup(self._restore)
        for stream in self.tables():
            self.load(stream, self.rows(stream))

    @staticmethod
    def _restore():
        (singer_runtime.source_config, singer_runtime.tap_output,
         singer_runtime.review) = _original

    def config(self, tables=None):
        return {'sourceSettings': self.settings(),
                'projectLock': {'tables': {
                    stream: {'source': {**table['source'], 'stream': stream},
                             'columns': table['columns']}
                    for stream, table in (tables or self.tables()).items()}}}

    def discover(self, source):
        return json.loads(b''.join(self.connector.output(None, source, None, 10, True)))

    def read(self, source, catalog):
        for stream in catalog['streams']:
            stream['metadata'] = [{'breadcrumb': [], 'metadata': {'selected': True}}]
        return [json.loads(line, parse_float=Decimal) for line in
                b''.join(self.connector.output(None, source, catalog, 10)).splitlines()]

    def test_discovery_is_deterministic_and_covers_every_table(self):
        source = self.connector.source_config(self.config())
        first, second = self.discover(source), self.discover(source)
        self.assertEqual(first, second)
        self.assertEqual([s['tap_stream_id'] for s in first['streams']], list(self.tables()))
        for stream in first['streams']:
            self.assertEqual(stream['schema'].get('type'), 'object')
            self.assertIn('properties', stream['schema'])

    def test_read_emits_schemas_then_records_for_each_table(self):
        source = self.connector.source_config(self.config())
        lines = self.read(source, self.discover(source))
        streams = list(self.tables())
        self.assertEqual([l['stream'] for l in lines if l['type'] == 'SCHEMA'], streams)
        for stream in streams:
            records = [l for l in lines if l['type'] == 'RECORD' and l['stream'] == stream]
            self.assertEqual(len(records), len(self.rows(stream)), stream)
        first_record = next(i for i, l in enumerate(lines) if l['type'] == 'RECORD')
        self.assertTrue(all(l['type'] == 'SCHEMA' for l in lines[:first_record]))

    def test_empty_table_reads_no_records(self):
        stream = next(iter(self.tables()))
        self.load(stream, [])
        source = self.connector.source_config(self.config())
        lines = self.read(source, self.discover(source))
        self.assertFalse([l for l in lines if l['type'] == 'RECORD' and l['stream'] == stream])

    def test_schema_drift_fails_before_any_record(self):
        source = self.connector.source_config(self.config())
        catalog = self.discover(source)
        self.change_schema(next(iter(self.tables())))
        # Connectors may detect drift in metadata or in the first row; either
        # way the run fails before anything is yielded for commit.
        for stream in catalog['streams']:
            stream['metadata'] = [{'breadcrumb': [], 'metadata': {'selected': True}}]
        with self.assertRaises(ValueError):
            next(self.connector.output(None, source, catalog, 10))

    def test_failure_in_last_table_publishes_nothing(self):
        source = self.connector.source_config(self.config())
        catalog = self.discover(source)
        self.break_source(list(self.tables())[-1])
        output = self.connector.output(None, source,
                                       {**catalog, 'streams': [{**s, 'metadata': [{'breadcrumb': [], 'metadata': {'selected': True}}]}
                                                                for s in catalog['streams']]}, 10)
        with self.assertRaises(Exception) as caught:
            next(output)
        self.assertNotIsInstance(caught.exception, StopIteration)

    def test_errors_never_carry_secrets_or_source_values(self):
        stream = list(self.tables())[-1]
        source = self.connector.source_config(self.config())
        catalog = self.discover(source)
        self.break_source(stream)
        try:
            self.read(source, catalog)
        except Exception as error:
            message = str(error)
        else:
            self.fail('A broken source must fail')
        for value in self.secret_values():
            self.assertNotIn(value, message)
        for text in self.connector.errors.values():
            for value in self.secret_values():
                self.assertNotIn(value, text)

    def test_locked_project_bounds_are_enforced(self):
        tables = self.tables()
        stream, table = next(iter(tables.items()))
        with self.assertRaisesRegex(ValueError, 'stream identity'):
            self.connector.source_config({**self.config(), 'projectLock': {'tables': {
                stream: {'source': {**table['source'], 'stream': 'other'}, 'columns': table['columns']}}}})
        with self.assertRaisesRegex(ValueError, 'distinct columns'):
            self.connector.source_config(self.config({stream: {**table, 'columns': table['columns'] * 2}}))
        with self.assertRaisesRegex(ValueError, 'locked project'):
            self.connector.source_config({'sourceSettings': self.settings()})
        with self.assertRaisesRegex(ValueError, 'Review every table'):
            source = self.connector.source_config(self.config())
            self.connector.review({'catalog': self.discover(source)}, {})
