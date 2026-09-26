"""Customer-operated Singer snapshot commit boundary."""

from __future__ import annotations
import fcntl
import hashlib
import json
import simplejson
import math
import os
import re
import shutil
import tempfile
from pathlib import Path
from decimal import Decimal
import pyarrow as pa
import pyarrow.parquet as pq


def canonical(value):
    return simplejson.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, use_decimal=True)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def safe_name(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", value
    ):
        raise ValueError("Invalid local identity/name")
    return value


def arrow_type(field):
    name = field["type"]
    simple = {
        "string": pa.string(),
        "integer": pa.int64(),
        "boolean": pa.bool_(),
        "number": pa.float64(),
        "json": pa.string(),
    }
    if name in simple:
        return simple[name]
    if name == "decimal":
        return pa.decimal128(field["precision"], field["scale"])
    raise ValueError("Unsupported reviewed type")


def convert(value, field):
    if value is None:
        if not field.get("nullable", False):
            raise ValueError("Required field is null/missing")
        return None
    kind = field["type"]
    if kind == "json":
        if not isinstance(value, (list, dict)):
            raise ValueError("Expected structured JSON")
        return canonical(value)
    if kind == "decimal":
        if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
            raise ValueError("Decimal requires exact text/integer, not float")
        d = Decimal(value)
        if not d.is_finite():
            raise ValueError("Nonfinite decimal")
        return d
    valid = {
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "boolean": type(value) is bool,
        "number": type(value) in (int, float) and math.isfinite(value),
    }
    if not valid.get(kind, False):
        raise ValueError("Reviewed type mismatch")
    return value


def verify_commit(destination, identity):
    receipt = json.loads((destination / "commit.json").read_text(), parse_float=Decimal)
    if receipt["identity"] != identity:
        raise ValueError("Run identity changed")
    expected = {"commit.json"}
    for entry in receipt["tables"]:
        filename = safe_name(entry["stream"]) + ".parquet"
        expected.add(filename)
        path = destination / filename
        if path.is_symlink() or file_digest(path) != entry["sha256"]:
            raise ValueError("Committed output changed")
    if {p.name for p in destination.iterdir()} != expected:
        raise ValueError("Unexpected committed file")
    return receipt


def snapshot(
    root, namespace, run_id, contract, source_identity, messages, fail_at=None
):
    """messages is a lazy factory; only successful commit exposes its STATE.

    Local POSIX single-writer lock; full snapshots only. Source identity must contain
    no credentials. No incremental cursor is restored.
    """
    if not contract:
        raise ValueError("Empty stream selection")
    safe_name(namespace)
    safe_name(run_id)
    base = Path(root) / namespace
    base.mkdir(parents=True, exist_ok=True)
    identity = {
        "namespace": namespace,
        "run_id": run_id,
        "contract_sha256": digest(contract),
        "source": source_identity,
    }
    destination = base / run_id
    with (base / ".writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if destination.exists():
            return verify_commit(destination, identity)
        staging = Path(tempfile.mkdtemp(prefix=".attempt-", dir=base))
        writers, buffers, counts, seen = {}, {}, {}, set()
        sizes = {}
        schemas = {}
        state = None
        try:
            for name, spec in contract.items():
                safe_name(name)
                if not spec["fields"]:
                    raise ValueError("Empty field selection")
                schemas[name] = pa.schema(
                    [
                        pa.field(v.get("target", k), arrow_type(v), nullable=v.get("nullable", False))
                        for k, v in spec["fields"].items()
                    ]
                )
                buffers[name] = []
                sizes[name] = 0
                counts[name] = 0
                writers[name] = pq.ParquetWriter(
                    staging / (name + ".parquet"), schemas[name]
                )

            def flush(name):
                if buffers[name]:
                    writers[name].write_table(
                        pa.Table.from_pylist(buffers[name], schema=schemas[name])
                    )
                    counts[name] += len(buffers[name])
                    buffers[name].clear()
                    sizes[name] = 0

            for message in messages():
                kind = message["type"]
                if kind == "STATE":
                    state = message["value"]
                    continue
                if kind not in ("SCHEMA", "RECORD"):
                    raise ValueError("Unsupported Singer message")
                name = message["stream"]
                if name not in contract:
                    continue
                if kind == "SCHEMA":
                    if digest(message["schema"]) != contract[name]["schema_sha256"]:
                        raise ValueError("Upstream schema changed; review required")
                    seen.add(name)
                    continue
                if name not in seen:
                    raise ValueError("Record before approved schema")
                row = message["record"]
                buffers[name].append(
                    {
                        v.get("target", k): convert(row.get(k), v)
                        for k, v in contract[name]["fields"].items()
                    }
                )
                sizes[name] += len(canonical(buffers[name][-1]).encode())
                if sum(sizes.values()) >= 8 * 1024 * 1024:
                    for buffered in buffers:
                        flush(buffered)
                if len(buffers[name]) >= 256:
                    flush(name)
                if fail_at == "record":
                    raise RuntimeError("Injected record interruption")
            if seen != set(contract):
                raise ValueError("Selected stream schema absent")
            for name in writers:
                flush(name)
                writers[name].close()
            if fail_at == "files":
                raise RuntimeError("Injected pre-commit interruption")
            receipt = {
                "format": "ingestron-singer-local-snapshot/preview-1",
                "identity": identity,
                "state": state,
                "tables": [
                    {
                        "stream": n,
                        "rows": counts[n],
                        "sha256": file_digest(staging / (n + ".parquet")),
                    }
                    for n in sorted(contract)
                ],
            }
            (staging / "commit.json").write_text(canonical(receipt) + "\n")
            for p in staging.iterdir():
                with p.open("rb") as f:
                    os.fsync(f.fileno())
            fd = os.open(staging, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            os.rename(staging, destination)
            fd = os.open(base, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            if fail_at == "committed":
                raise RuntimeError("Injected post-commit acknowledgement loss")
            return verify_commit(destination, identity)
        finally:
            for writer in writers.values():
                writer.close()
            if staging.exists():
                shutil.rmtree(staging)
