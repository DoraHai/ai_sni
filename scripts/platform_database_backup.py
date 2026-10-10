"""Create a private PostgreSQL archive and publish metadata for the admin console.

Run explicitly as the backup operator. No migration, restore, retention deletion,
provider call, credential output or backup download endpoint is performed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from sqlalchemy.engine import make_url


def publish_status(path, record):
    records = []
    if path.exists():
        previous = json.loads(path.read_text(encoding='utf-8'))
        if previous.get('schema') != 1 or not isinstance(previous.get('records'), list):
            raise ValueError('Invalid prior metadata')
        records = previous['records']
    records = [record, *records][:20]
    temporary = path.with_name(path.name + '.tmp-' + str(uuid4()))
    with temporary.open('x', encoding='utf-8') as handle:
        os.chmod(temporary, 0o600)
        json.dump({'schema': 1, 'records': records}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    # Metadata contains only status and counts, never paths or business rows.
    os.chmod(path, 0o644)


def backup(env_file, directory, status_file):
    identifier = str(uuid4())
    record = {'id': identifier, 'scope': 'public_schema', 'state': 'failed',
              'bytes': 0, 'archive_verified': False, 'restore_verified': False}
    error = None
    try:
        url = make_url(dotenv_values(env_file)['DATABASE_URL'])
        if not url.drivername.startswith('postgresql') or not url.host or not url.database or not url.username:
            raise ValueError('PostgreSQL configuration required')
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / ('database-' + identifier)
        target.mkdir(mode=0o700)
        archive = target / 'public.dump'
        environment = {**os.environ, 'PGPASSWORD': url.password or ''}
        # Secrets are passed only in the child environment; output is captured.
        command = ['pg_dump', '--host', url.host, '--port', str(url.port or 5432),
                   '--username', url.username, '--dbname', url.database, '--no-password',
                   '--format=custom', '--schema=public', '--no-owner', '--no-privileges', '--file', str(archive)]
        subprocess.run(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       check=True, timeout=600)
        os.chmod(archive, 0o600)
        record['bytes'] = archive.stat().st_size
        if not record['bytes']:
            raise ValueError('Empty archive')
        listing = subprocess.run(['pg_restore', '--list', str(archive)], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, check=True, timeout=60)
        if b'TABLE DATA' not in listing.stdout:
            raise ValueError('Archive has no table data')
        record.update(state='succeeded', archive_verified=True)
    except Exception as exc:
        error = type(exc).__name__
    record['completed_at'] = datetime.now(timezone.utc).isoformat()
    publish_status(status_file, record)
    print(json.dumps({**record, 'error_class': error}))
    return 0 if record['state'] == 'succeeded' else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--directory', type=Path, default=Path('/opt/sem-backend-backups'))
    parser.add_argument('--status-file', type=Path, default=Path('/opt/sem-backend/platform-backup-status.json'))
    args = parser.parse_args()
    return backup(args.env_file, args.directory, args.status_file)


if __name__ == '__main__':
    raise SystemExit(main())
