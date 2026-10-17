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
from datetime import date, datetime
from temporal_types import temporal_value
import pyarrow as pa
import pyarrow.parquet as pq
from quality_rules import QualityFailed, evaluate


CHECKPOINT_ERRORS = {
    'CHECKPOINT_HISTORY': 'Incremental commit history is incomplete or changed. Restore the committed output and receipts before retrying.',
    'CHECKPOINT_MIGRATION': 'The reviewed checkpoint transition is absent, changed or belongs to another history. Inspect the migration before continuing.',
    'CHECKPOINT_MIGRATION_STALE': 'Checkpoint history changed after review. Preview the current migration before applying it.',
    'CHECKPOINT_POLICY': 'The incremental source, schema or policy changed. Review a migration before continuing this output namespace.',
    'CHECKPOINT_LIMIT': 'Incremental history reached its supported limit of 10000 batches. Review an archive migration before continuing.',
    'CHECKPOINT_CURSOR': 'The connector returned an invalid or regressing cursor. Check the reviewed ordered append policy before retrying.',
    'CHECKPOINT_MISSING': 'The connector omitted its final checkpoint. Output and cursor were not committed.',
}


class CheckpointError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(CHECKPOINT_ERRORS[code])


def canonical(value):
    return simplejson.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, use_decimal=True)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class _CompilerNumber(str):
    """A number token already serialised by the compiler's JSON writer."""


def project_specification_digest(text):
    """Hash a compiler-written project lock without changing runtime hashes.

    The compiler sorts keys using UTF-16 and writes UTF-8 JSON. Preserve its
    number tokens rather than rounding/reformatting them through Python floats.
    Runtime receipts, schema hashes and checkpoints retain their existing codec.
    """
    def invalid_constant(value):
        raise ValueError('Invalid compiler JSON number')

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate project lock key')
            result[key] = value
        return result

    project = json.loads(text, parse_int=_CompilerNumber,
                         parse_float=_CompilerNumber, parse_constant=invalid_constant,
                         object_pairs_hook=unique_object)
    if not isinstance(project, dict):
        raise ValueError('Project lock must be an object')
    project.pop('specificationSha256')

    def string(value):
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        # JSON.stringify escapes unpaired surrogates, while valid pairs arrive
        # as Unicode code points from the compiler's UTF-8 JSON file.
        return ''.join('\\u%04x' % ord(c) if 0xd800 <= ord(c) <= 0xdfff else c
                       for c in encoded)

    def ordered_keys(value):
        indices, other = [], []
        for key in value:
            if (len(key) <= 10 and re.fullmatch(r'0|[1-9][0-9]*', key)
                    and int(key) < 4294967295):
                indices.append(key)
            else:
                other.append(key)
        return (sorted(indices, key=int)
                + sorted(other, key=lambda k: k.encode('utf-16-be', 'surrogatepass')))

    def serialise(value):
        if isinstance(value, _CompilerNumber):
            return str(value)
        if isinstance(value, dict):
            return '{' + ','.join(string(k) + ':' + serialise(value[k])
                                  for k in ordered_keys(value)) + '}'
        if isinstance(value, list):
            return '[' + ','.join(serialise(v) for v in value) + ']'
        return string(value)

    return hashlib.sha256(serialise(project).encode('utf8')).hexdigest()


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
        "date": pa.date32(),
        "timestamp": pa.timestamp("us"),
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
    if kind in ("date", "timestamp"):
        return temporal_value(value, kind)
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


def checkpoint_binding(identity):
    return digest({k: v for k, v in identity.items() if k != 'run_id'})


def _migration_identity(identity):
    if not isinstance(identity, dict):
        raise CheckpointError('CHECKPOINT_MIGRATION')
    return {k: v for k, v in identity.items() if k != 'run_id'}


def _migration_documents(base):
    folder = base / '.migrations'
    if folder.is_symlink():
        raise CheckpointError('CHECKPOINT_MIGRATION')
    if not folder.exists():
        return []
    if not folder.is_dir():
        raise CheckpointError('CHECKPOINT_MIGRATION')
    files = [p for p in folder.iterdir() if not p.name.startswith('.')]
    if len(files) > 1000:
        raise CheckpointError('CHECKPOINT_LIMIT')
    result = []
    for path in files:
        if (path.is_symlink() or not path.is_file() or path.stat().st_size > 1000000
                or not re.fullmatch(r'[a-f0-9]{64}\.json', path.name)):
            raise CheckpointError('CHECKPOINT_MIGRATION')
        try:
            document = json.loads(path.read_text(), parse_float=Decimal)
            payload = {k: v for k, v in document.items() if k != 'id'}
            if (set(document) != {'apiVersion', 'strategy', 'namespace', 'fromBinding', 'toBinding',
                                  'fromIdentity', 'toIdentity', 'policyDigest', 'head', 'initial', 'id'}
                    or document['apiVersion'] != 'ingestron.checkpoint-migration/v1'
                    or document['strategy'] != 'preserve-cursor-runtime-upgrade'
                    or document['id'] != digest(payload) or path.name != document['id'] + '.json'
                    or document['namespace'] != base.name
                    or not re.fullmatch(r'[a-f0-9]{64}', document['policyDigest'])
                    or document['fromBinding'] != checkpoint_binding(document['fromIdentity'])
                    or document['toBinding'] != checkpoint_binding(document['toIdentity'])
                    or 'run_id' in document['fromIdentity'] or 'run_id' in document['toIdentity']
                    or document['fromIdentity'].get('namespace') != base.name
                    or document['toIdentity'].get('namespace') != base.name
                    or document['fromBinding'] == document['toBinding']
                    or set(document['head']) != {'sequence', 'receiptSha256', 'bookmarks'}
                    or type(document['head']['sequence']) is not int
                    or not 1 <= document['head']['sequence'] <= 10000
                    or not re.fullmatch(r'[a-f0-9]{64}', document['head']['receiptSha256'])):
                raise ValueError('Invalid migration')
            validate_bookmarks(document['initial'], {k: '0' for k in document['initial']})
            validate_bookmarks(document['head']['bookmarks'], document['initial'])
            result.append(document)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise CheckpointError('CHECKPOINT_MIGRATION') from None
    if len({m['head']['sequence'] for m in result}) != len(result):
        raise CheckpointError('CHECKPOINT_MIGRATION')
    return result


def _migration_transition(document, previous, before_identity, after_identity, initial, policy_digest):
    if (document['head'] != previous or document['initial'] != initial
            or document['policyDigest'] != policy_digest
            or document['fromIdentity'] != _migration_identity(before_identity)
            or document['toIdentity'] != _migration_identity(after_identity)):
        raise CheckpointError('CHECKPOINT_MIGRATION')


def restore_checkpoint(base, identity, initial, policy_digest=None, verify_all=False):
    """Restore immutable deltas and explicitly reviewed identity transitions under the writer lock."""
    binding = checkpoint_binding(identity)
    migrations = _migration_documents(base)
    if migrations and not re.fullmatch(r'[a-f0-9]{64}', policy_digest or ''):
        raise CheckpointError('CHECKPOINT_POLICY')
    links = {m['head']['sequence']: m for m in migrations}
    runs = [p for p in base.iterdir() if not p.name.startswith('.')]
    if len(runs) >= 10000: raise CheckpointError('CHECKPOINT_LIMIT')
    committed = []
    for run in runs:
        commit = run / 'commit.json'
        if run.is_symlink() or not run.is_dir() or commit.is_symlink() or not commit.is_file() or commit.stat().st_size > 1000000:
            raise CheckpointError('CHECKPOINT_HISTORY')
        try:
            receipt = json.loads(commit.read_text(), parse_float=Decimal)
        except (ValueError, UnicodeError):
            raise CheckpointError('CHECKPOINT_HISTORY') from None
        if not isinstance(receipt, dict) or not isinstance(receipt.get('identity'), dict):
            raise CheckpointError('CHECKPOINT_HISTORY')
        state = receipt.get('state')
        if (receipt.get('format') != 'ingestron-local-incremental/v1' or not isinstance(state, dict)
                or state.get('apiVersion') != 'ingestron.local-checkpoint/v1'
                or type(state.get('sequence')) is not int or not 1 <= state['sequence'] <= 10000
                or state.get('binding') != checkpoint_binding(receipt['identity'])
                or receipt['identity'].get('run_id') != run.name
                or receipt['identity'].get('namespace') != identity.get('namespace')):
            raise CheckpointError('CHECKPOINT_POLICY')
        committed.append((state['sequence'], receipt, run))
    committed.sort(key=lambda item: item[0])
    chain_binding = committed[0][1]['state']['binding'] if migrations and committed else binding
    previous = {'sequence': 0, 'receiptSha256': digest({'binding': chain_binding, 'initial': initial}), 'bookmarks': dict(initial)}
    last_identity = None
    consumed = set()
    for sequence, receipt, run in committed:
        state = receipt['state']
        transition = links.get(previous['sequence'])
        if transition is not None:
            _migration_transition(transition, previous, last_identity, receipt['identity'], initial, policy_digest)
            chain_binding = transition['toBinding']
            consumed.add(previous['sequence'])
        if state['binding'] != chain_binding:
            raise CheckpointError('CHECKPOINT_POLICY')
        if sequence != previous['sequence'] + 1 or state.get('parent') != previous['receiptSha256']:
            raise CheckpointError('CHECKPOINT_HISTORY')
        validate_bookmarks(state.get('bookmarks'), previous['bookmarks'])
        if type(state.get('hasMore')) is not bool: raise CheckpointError('CHECKPOINT_HISTORY')
        if migrations or verify_all:
            try: verify_commit(run, receipt['identity'])
            except (ValueError, KeyError, TypeError, OSError): raise CheckpointError('CHECKPOINT_HISTORY') from None
        previous = {'sequence': sequence, 'receiptSha256': digest(receipt), 'bookmarks': state['bookmarks']}
        last_identity = receipt['identity']
    pending = links.get(previous['sequence'])
    if pending is not None:
        _migration_transition(pending, previous, last_identity, identity, initial, policy_digest)
        chain_binding = pending['toBinding']
        consumed.add(previous['sequence'])
    if len(consumed) != len(migrations): raise CheckpointError('CHECKPOINT_MIGRATION')
    if chain_binding != binding: raise CheckpointError('CHECKPOINT_POLICY')
    if committed and not migrations and not verify_all:
        _, last, run = committed[-1]
        try: verify_commit(run, last['identity'])
        except (ValueError, KeyError, TypeError, OSError): raise CheckpointError('CHECKPOINT_HISTORY') from None
    return previous


def _migration_result(document, applied):
    return {'apiVersion': 'ingestron.checkpoint-migration-preview/v1',
            'digest': document['id'], 'applied': applied, 'strategy': document['strategy'],
            'namespace': document['namespace'], 'fromBinding': document['fromBinding'],
            'toBinding': document['toBinding'], 'policyDigest': document['policyDigest'],
            'head': document['head']}


def _preview_checkpoint_migration(base, from_identity, to_identity, initial, policy_digest):
    before, after = _migration_identity(from_identity), _migration_identity(to_identity)
    if (before.get('namespace') != base.name or after.get('namespace') != base.name
            or not re.fullmatch(r'[a-f0-9]{64}', policy_digest or '')
            or checkpoint_binding(before) == checkpoint_binding(after)):
        raise CheckpointError('CHECKPOINT_POLICY')
    validate_bookmarks(initial, {name: '0' for name in initial})
    documents = _migration_documents(base)
    existing = [m for m in documents if m['toIdentity'] == after and m['fromIdentity'] == before
                and m['initial'] == initial and m['policyDigest'] == policy_digest]
    if existing:
        if len(existing) != 1: raise CheckpointError('CHECKPOINT_MIGRATION')
        restore_checkpoint(base, after, initial, policy_digest)
        return existing[0], True
    previous = restore_checkpoint(base, before, initial, policy_digest, verify_all=True)
    if previous['sequence'] < 1: raise CheckpointError('CHECKPOINT_HISTORY')
    if any(m['head']['sequence'] == previous['sequence'] for m in documents):
        raise CheckpointError('CHECKPOINT_MIGRATION')
    payload = {'apiVersion': 'ingestron.checkpoint-migration/v1',
               'strategy': 'preserve-cursor-runtime-upgrade', 'namespace': base.name,
               'fromBinding': checkpoint_binding(before), 'toBinding': checkpoint_binding(after),
               'fromIdentity': before, 'toIdentity': after, 'policyDigest': policy_digest,
               'head': previous, 'initial': initial}
    document = {**payload, 'id': digest(payload)}
    if len(canonical(document).encode('utf8')) > 1000000: raise CheckpointError('CHECKPOINT_LIMIT')
    return document, False


def _migration_lock(base):
    base = Path(base)
    lock = base / '.writer.lock'
    if base.is_symlink() or not base.is_dir() or lock.is_symlink() or not lock.is_file():
        raise CheckpointError('CHECKPOINT_HISTORY')
    return lock.open('r+')


def preview_checkpoint_migration(base, from_identity, to_identity, initial, policy_digest):
    """Read bounded cursor evidence; no source calls, output rewrites or journal creation."""
    base = Path(base)
    with _migration_lock(base) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        document, applied = _preview_checkpoint_migration(base, from_identity, to_identity, initial, policy_digest)
        return _migration_result(document, applied)


def apply_checkpoint_migration(base, from_identity, to_identity, initial, policy_digest, expected_digest, fail_at=None):
    """Publish one reviewed immutable transition; retries acknowledge the same journal."""
    base = Path(base)
    with _migration_lock(base) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        document, applied = _preview_checkpoint_migration(base, from_identity, to_identity, initial, policy_digest)
        if not re.fullmatch(r'[a-f0-9]{64}', expected_digest or '') or document['id'] != expected_digest:
            raise CheckpointError('CHECKPOINT_MIGRATION_STALE')
        if not applied:
            folder = base / '.migrations'
            if folder.is_symlink(): raise CheckpointError('CHECKPOINT_MIGRATION')
            folder.mkdir(exist_ok=True)
            if not folder.is_dir(): raise CheckpointError('CHECKPOINT_MIGRATION')
            if len(_migration_documents(base)) >= 1000: raise CheckpointError('CHECKPOINT_LIMIT')
            destination = folder / (document['id'] + '.json')
            fd, name = tempfile.mkstemp(prefix='.migration-', dir=folder)
            temporary = Path(name)
            try:
                with os.fdopen(fd, 'w') as target:
                    target.write(canonical(document) + '\n'); target.flush(); os.fsync(target.fileno())
                if fail_at == 'written': raise RuntimeError('Interrupted migration before publication')
                os.link(temporary, destination)
                directory_fd = os.open(folder, os.O_RDONLY)
                try: os.fsync(directory_fd)
                finally: os.close(directory_fd)
                if fail_at == 'published': raise RuntimeError('Interrupted migration acknowledgement')
            finally:
                temporary.unlink(missing_ok=True)
        return _migration_result(document, True)



def validate_bookmarks(bookmarks, previous):
    if (not isinstance(bookmarks, dict) or set(bookmarks) != set(previous)
            or any(not isinstance(value, str) or not re.fullmatch(r'0|[1-9][0-9]{0,18}', value)
                   or not int(previous[name]) <= int(value) <= 9223372036854775807
                   for name, value in bookmarks.items())):
        raise CheckpointError('CHECKPOINT_CURSOR')


def snapshot(
    root, namespace, run_id, contract, source_identity, messages, fail_at=None,
    rules=None, checkpoint=None, checkpoint_policy_digest=None,
):
    """messages is a lazy factory; only successful commit exposes its STATE.

    Local POSIX single-writer lock. Optional checkpoint restores committed append
    cursors and commits their advancement with output. Source identity must contain
    no credentials. rules maps a stream to its
    authored ODCS contract; an error-severity rule that fails prevents the commit.
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
        previous = None
        if checkpoint is not None:
            if any(type(value) is not int or value < 0 or value > 9007199254740991 for value in checkpoint.values()):
                raise ValueError('Initial incremental cursor must be an exact nonnegative JSON integer')
            checkpoint = {name: str(value) for name, value in checkpoint.items()}
            validate_bookmarks(checkpoint, {name: '0' for name in contract})
            previous = restore_checkpoint(base, identity, checkpoint, checkpoint_policy_digest)
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

            for message in (messages(previous['bookmarks']) if previous is not None else messages()):
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
                sizes[name] += len(canonical({key: value.isoformat() if type(value) in (date, datetime) else value
                                              for key, value in buffers[name][-1].items()}).encode())
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
            quality = []
            for n in sorted(rules or {}):
                if n in contract:
                    name = rules[n]["schema"][0]["name"]
                    quality += [
                        {"stream": n, **r}
                        for r in evaluate(rules[n], staging / (n + ".parquet"), name)
                    ]
            failed = [r for r in quality if r["outcome"] == "fail" and not r["passed"]]
            if failed:
                raise QualityFailed(failed)
            if previous is not None:
                if not isinstance(state, dict) or set(state) != {'bookmarks', 'hasMore'} or type(state['hasMore']) is not bool:
                    raise CheckpointError('CHECKPOINT_MISSING')
                validate_bookmarks(state['bookmarks'], previous['bookmarks'])
                state = {'apiVersion': 'ingestron.local-checkpoint/v1', 'sequence': previous['sequence'] + 1,
                         'binding': checkpoint_binding(identity), 'parent': previous['receiptSha256'], **state}
            receipt = {
                "format": "ingestron-local-incremental/v1" if previous is not None else "ingestron-singer-local-snapshot/preview-1",
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
                **({"quality": quality} if quality else {}),
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
