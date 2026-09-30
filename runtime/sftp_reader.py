"""Files on an SFTP server through the system OpenSSH client (PB-064 phase 7).

No SSH library is bundled: the machine's `sftp` runs in batch mode with key
authentication only, a pinned host key (StrictHostKeyChecking), no agent or
user configuration, and a connection timeout. The private key and known-hosts
entry live in private temporary files for one command. A path naming a file
reads it; a folder reads every file of the selected format directly inside
it, in name order, with one shared schema. Client output is mapped to error
codes and never echoed.
"""
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from files_reader import scan as scan_file, MAX_BYTES

MAX_FILES = 100
SUFFIX = {'csv': '.csv', 'tsv': '.tsv', 'json': '.json', 'jsonl': '.jsonl', 'parquet': '.parquet'}
HOST = re.compile(r'[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?')
USER = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]{0,63}')
HOST_KEY = re.compile(r'(ssh-ed25519|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|rsa-sha2-256|rsa-sha2-512|ssh-rsa) [A-Za-z0-9+/]+={0,2}')
ERRORS = {
    'SFTP_CLIENT': 'The OpenSSH sftp client is not installed on the machine running the flow.',
    'SFTP_AUTH': 'The SFTP server rejected the key; check the user and private key.',
    'SFTP_HOST_KEY': 'The SFTP server host key differs from the pinned host_key; verify it before changing the setting.',
    'SFTP_NOT_FOUND': 'The SFTP path was not found or is not readable.',
    'SFTP_NETWORK': 'Cannot reach the SFTP server; check host, port and network access.',
    'SFTP_RESPONSE': 'The SFTP client returned an unexpected result.',
    'SFTP_TOO_LARGE': 'A file exceeds 64 MiB or the folder has more than 100 matching files.',
    'SFTP_NO_FILES': 'The folder has no files of the selected format.',
    'SFTP_CHANGED': 'A file changed during download; retry when it is stable.',
    'SFTP_SCHEMA': 'Files in the folder have different columns; keep one schema per table.',
}


class SftpError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, message):
    if not condition: raise ValueError(message)


def settings_for(settings):
    require(isinstance(settings.get('host'), str) and HOST.fullmatch(settings['host']), 'Use a host name or address')
    port = settings.get('port', 22)
    require(type(port) is int and 1 <= port <= 65535, 'Use a TCP port')
    require(isinstance(settings.get('user'), str) and USER.fullmatch(settings['user']), 'Use a user name')
    key = settings.get('private_key')
    require(isinstance(key, str) and 'PRIVATE KEY-----' in key and len(key) <= 16384,
            'Set private_key (an OpenSSH or PEM private key) through its secret reference')
    require(isinstance(settings.get('host_key'), str) and HOST_KEY.fullmatch(settings['host_key'].strip()),
            'Pin host_key as "<type> <base64>" from the server administrator or ssh-keyscan')
    return settings['host'], port


def table_path(path):
    require(isinstance(path, str) and 0 < len(path) <= 1024 and all(ord(c) >= 32 for c in path)
            and '"' not in path and '\\' not in path
            and all(p not in ('', '.', '..') for p in path.lstrip('/').split('/')),
            'path must be a file or folder path without traversal or quotes')
    return path


class OpenSsh:
    """One sftp batch command per call; credentials in private temporary files."""

    def __init__(self, settings):
        self.settings = settings
        self.host, self.port = settings_for(settings)
        self.client = shutil.which('sftp')
        if not self.client: raise SftpError('SFTP_CLIENT')

    def run(self, commands):
        with tempfile.TemporaryDirectory(prefix='ingestron-sftp-') as folder:
            base = Path(folder)
            key, known, batch = base / 'key', base / 'known_hosts', base / 'batch'
            key.write_text(self.settings['private_key'].strip() + '\n')
            os.chmod(key, stat.S_IRUSR | stat.S_IWUSR)
            host = self.host if self.port == 22 else f'[{self.host}]:{self.port}'
            known.write_text(f"{host} {self.settings['host_key'].strip()}\n")
            batch.write_text(''.join(c + '\n' for c in commands))
            args = [self.client, '-b', str(batch), '-F', '/dev/null', '-P', str(self.port),
                    '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={known}',
                    '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'IdentitiesOnly=yes', '-o', f'IdentityFile={key}',
                    '-o', 'IdentityAgent=none', '-o', 'ConnectTimeout=30', '-o', 'LogLevel=ERROR',
                    f"{self.settings['user']}@{self.host}"]
            try:
                result = subprocess.run(args, capture_output=True, text=True, timeout=900,
                                        env={'PATH': os.environ.get('PATH', '/usr/bin:/bin')}, cwd=folder)
            except subprocess.TimeoutExpired:
                raise SftpError('SFTP_NETWORK') from None
            if result.returncode != 0:
                err = result.stderr
                if 'Host key verification failed' in err or 'REMOTE HOST IDENTIFICATION' in err:
                    raise SftpError('SFTP_HOST_KEY')
                if 'Permission denied' in err and ('publickey' in err or 'Authentication' in err):
                    raise SftpError('SFTP_AUTH')
                if 'No such file' in err or 'not found' in err or 'Permission denied' in err:
                    raise SftpError('SFTP_NOT_FOUND')
                if any(t in err for t in ('Connection refused', 'timed out', 'Could not resolve', 'Connection closed')):
                    raise SftpError('SFTP_NETWORK')
                raise SftpError('SFTP_RESPONSE')
            return result.stdout

    def list(self, path):
        """[(name, size, is_directory)] for a folder, or one entry for a file."""
        out = self.run([f'ls -ln "{path}"'])
        entries = []
        for line in out.splitlines():
            if line.startswith('sftp>') or not line.strip(): continue
            parts = line.split(None, 8)
            if len(parts) < 9 or not parts[4].isdigit(): raise SftpError('SFTP_RESPONSE')
            entries.append((parts[8].rsplit('/', 1)[-1], int(parts[4]), parts[0].startswith('d')))
        return entries

    def get(self, remote, local):
        self.run([f'get "{remote}" "{local}"'])


def scan(settings, table, emit=None, transport=None):
    remote = transport or OpenSsh(settings)
    path, fmt = table['path'], table['format']
    entries = remote.list(path)
    name = path.rstrip('/').rsplit('/', 1)[-1]
    if len(entries) == 1 and not entries[0][2] and entries[0][0] == name:
        files = [(path, entries[0][1])]
    else:
        files = sorted((f"{path.rstrip('/')}/{n}", size) for n, size, directory in entries
                       if not directory and n.lower().endswith(SUFFIX[fmt]))
        if not files: raise SftpError('SFTP_NO_FILES')
        if len(files) > MAX_FILES: raise SftpError('SFTP_TOO_LARGE')
    if emit is None: files = files[:1]
    schema = None
    with tempfile.TemporaryDirectory(prefix='ingestron-sftp-data-') as folder:
        for index, (file, size) in enumerate(files):
            if size > MAX_BYTES: raise SftpError('SFTP_TOO_LARGE')
            local = Path(folder).resolve() / f'input-{index}'
            remote.get(file, str(local))
            if not local.is_file() or local.stat().st_size != size: raise SftpError('SFTP_CHANGED')
            current, _ = scan_file({'path': str(local), 'format': fmt, 'types': table['types']}, emit)
            local.unlink()
            if schema is not None and current != schema: raise SftpError('SFTP_SCHEMA')
            schema = current
    return schema
