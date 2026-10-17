"""Bounded, content-addressed metadata documents for compiler-owned bundles.

This codec does not author, approve or publish a review. Callers retain their
typed project/review validation and transaction boundary. Existing single-file
formats are unchanged; no existing runtime selects this format implicitly.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import stat

DOCUMENT_LIMIT = 2_000_000
COLLECTION_LIMIT = 7_000_000
DOCUMENT_COUNT_LIMIT = 100
API_VERSION = 'ingestron.metadata-documents/v1'
KINDS = ('project', 'selection', 'review')
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_-]{0,100}\Z')
DIGEST = re.compile(r'[a-f0-9]{64}\Z')


class MetadataDocumentLimit(ValueError):
    code = 'SOURCE_METADATA_LIMIT'

    def __init__(self):
        super().__init__('Metadata exceeds the supported 2 MB document limit')


class MetadataCollectionLimit(ValueError):
    code = 'SOURCE_METADATA_COLLECTION_LIMIT'

    def __init__(self):
        super().__init__('Metadata exceeds the supported 7 MB collection limit')


def _require(condition):
    if not condition:
        # Never include a path, source value or malformed upstream content.
        raise ValueError('Invalid or changed reviewed metadata document')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _constant(_value):
    _require(False)


def _decode(content):
    _require(isinstance(content, bytes))
    if len(content) > DOCUMENT_LIMIT:
        raise MetadataDocumentLimit()
    try:
        value = json.loads(content.decode('utf8'), object_pairs_hook=_unique,
                           parse_float=Decimal, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError('Invalid or changed reviewed metadata document') from None
    _require(isinstance(value, dict))
    return value


def validate_index(index, expected_kind):
    """Validate the whole index before accessing any file; do not infer a kind."""
    _require(expected_kind in KINDS and isinstance(index, dict)
             and set(index) == {'apiVersion', 'kind', 'documents', 'totalBytes'}
             and index['apiVersion'] == API_VERSION
             and index['kind'] == expected_kind)
    documents = index['documents']
    _require(isinstance(documents, dict)
             and 1 <= len(documents) <= DOCUMENT_COUNT_LIMIT)
    total = 0
    for name, record in documents.items():
        _require(isinstance(name, str) and IDENTIFIER.fullmatch(name)
                 and isinstance(record, dict)
                 and set(record) == {'path', 'sha256', 'bytes'})
        digest = record['sha256']
        _require(isinstance(digest, str) and DIGEST.fullmatch(digest)
                 and record['path'] == f'metadata/{expected_kind}/{digest}.json'
                 and type(record['bytes']) is int and record['bytes'] > 0)
        if record['bytes'] > DOCUMENT_LIMIT:
            raise MetadataDocumentLimit()
        total += record['bytes']
    _require(type(index['totalBytes']) is int and index['totalBytes'] == total)
    if total > COLLECTION_LIMIT:
        raise MetadataCollectionLimit()
    # This bounded index remains a document itself. Records count their logical
    # bytes even if two records address the same file, bounding expansion too.
    if len(json.dumps(index, separators=(',', ':'), ensure_ascii=True).encode()) > DOCUMENT_LIMIT:
        raise MetadataDocumentLimit()
    return documents


def document_index(kind, documents):
    """Return an explicit index and artifact map from exact JSON document bytes."""
    _require(kind in KINDS and isinstance(documents, dict)
             and 1 <= len(documents) <= DOCUMENT_COUNT_LIMIT)
    files, records, total = {}, {}, 0
    for name, content in documents.items():
        _require(isinstance(name, str) and IDENTIFIER.fullmatch(name))
        _decode(content)
        digest = hashlib.sha256(content).hexdigest()
        path = f'metadata/{kind}/{digest}.json'
        records[name] = {'path': path, 'sha256': digest, 'bytes': len(content)}
        files[path] = content
        total += len(content)
        if total > COLLECTION_LIMIT:
            raise MetadataCollectionLimit()
    index = {'apiVersion': API_VERSION, 'kind': kind,
             'documents': records, 'totalBytes': total}
    validate_index(index, kind)
    return index, files


def read_documents(root, index, expected_kind):
    """Yield verified metadata one document at a time beneath an owned root.

    Directory file descriptors and O_NOFOLLOW protect against path replacement
    and symlink races. A complete index is validated before the first open.
    Callers must consume/validate the whole collection before a commit.
    """
    records = validate_index(index, expected_kind)
    root = Path(root)
    _require(root.is_absolute())
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        _require(str(root) == str(root.resolve(strict=True)))
        root_fd = os.open(root, directory_flags)
        try:
            metadata_fd = os.open('metadata', directory_flags, dir_fd=root_fd)
            try:
                kind_fd = os.open(expected_kind, directory_flags, dir_fd=metadata_fd)
                try:
                    for name, record in records.items():
                        filename = record['sha256'] + '.json'
                        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                     dir_fd=kind_fd)
                        with os.fdopen(fd, 'rb') as source:
                            info = os.fstat(source.fileno())
                            _require(stat.S_ISREG(info.st_mode)
                                     and info.st_size == record['bytes'])
                            content = source.read(record['bytes'] + 1)
                        _require(len(content) == record['bytes']
                                 and hashlib.sha256(content).hexdigest() == record['sha256'])
                        yield name, _decode(content)
                finally:
                    os.close(kind_fd)
            finally:
                os.close(metadata_fd)
        finally:
            os.close(root_fd)
    except OSError:
        raise ValueError('Invalid or changed reviewed metadata document') from None
