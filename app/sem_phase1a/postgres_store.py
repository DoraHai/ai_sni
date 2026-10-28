"""Injected SQLAlchemy unit of work. No URL/config/engine creation or DDL.

PostgreSQL row locks serialize plan -> preview; CAS also protects audit-only writes.
SQLite is accepted solely for disposable contract fixtures. Schema comes from 0077.
"""
from contextlib import contextmanager
import json

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.sem_phase0.store import RevisionConflict


class SQLAlchemyShadowStore:
    def __init__(self, connection_factory):
        # Typically an explicitly supplied Engine.begin; never app.database.engine.
        self.connection_factory = connection_factory

    @contextmanager
    def transaction(self):
        with self.connection_factory() as db:
            tx = _Transaction(db)
            yield tx
            tx.plans.flush()
            tx.previews.flush()

    def cleanup_previews(self, now):
        with self.connection_factory() as db:
            return db.execute(text('DELETE FROM sem_phase1a_shadow_previews WHERE expires_at<=:now'),
                              {'now': now}).rowcount


class _Records:
    def __init__(self, db, table):
        self.db, self.table, self.loaded = db, table, {}

    def get(self, key):
        if key not in self.loaded:
            suffix = ' FOR UPDATE' if self.db.dialect.name == 'postgresql' else ''
            row = self.db.execute(text(f'SELECT revision,payload FROM {self.table} WHERE id=:id' + suffix),
                                  {'id': key}).first()
            if row is None:
                return None
            self.loaded[key] = [row[0], row[1], json.loads(row[1])]
        return self.loaded[key][2]

    def __setitem__(self, key, value):
        if key not in self.loaded:
            self.get(key)
        if key in self.loaded:
            self.loaded[key][2] = value
        else:
            self.loaded[key] = [None, None, value]

    def flush(self):
        for key, (revision, original, value) in self.loaded.items():
            payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            if payload == original:
                continue
            params = {'id': key, 'payload': payload, 'revision': revision,
                      'expiry': value['preview']['expires_at'] if self.table.endswith('previews') else None}
            if revision is None:
                try:
                    self.db.execute(text(f'INSERT INTO {self.table}(id,revision,payload,expires_at) '
                                         'VALUES(:id,1,:payload,:expiry)'), params)
                except IntegrityError:
                    raise RevisionConflict('存储版本冲突') from None
            elif self.db.execute(text(f'UPDATE {self.table} SET revision=revision+1,payload=:payload,'
                                      'expires_at=:expiry WHERE id=:id AND revision=:revision'), params).rowcount != 1:
                raise RevisionConflict('存储版本冲突')


class _Transaction:
    def __init__(self, db):
        self.plans = _Records(db, 'sem_phase1a_shadow_plans')
        self.previews = _Records(db, 'sem_phase1a_shadow_previews')
