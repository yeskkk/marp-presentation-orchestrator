from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from mpres.util import MPresError, utc_now


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Store:
    """Short transactions only. External work never runs while a writer is held."""

    def __init__(self, task: Path):
        self.task = task.resolve()
        self.path = self.task / '.mpres' / 'task.sqlite3'

    SCHEMA_VERSION = 12

    def readonly(self):
        """No DDL, schema upgrade, lockfile creation, or hidden state changes."""
        from .maintenance_lock import readonly_connection
        return readonly_connection(self.path)

    def connect(self) -> sqlite3.Connection:
        if not self.path.is_file():raise MPresError(f'No compact task database: {self.path}')
        from .maintenance_lock import writable_connection
        conn=writable_connection(self.path,self.task,timeout=30,isolation_level=None)
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON');conn.execute('PRAGMA busy_timeout=30000');conn.execute('PRAGMA synchronous=FULL')
        try:
            self._migrate(conn)
            return conn
        except Exception:
            conn.close();raise

    @staticmethod
    def _audit_schema(conn):
        conn.execute("CREATE TABLE IF NOT EXISTS migration_audit (id INTEGER PRIMARY KEY, from_version INTEGER, to_version INTEGER NOT NULL, program_version TEXT NOT NULL, trigger_json TEXT NOT NULL, actor TEXT, started_at TEXT NOT NULL, finished_at TEXT, state TEXT NOT NULL, error TEXT)")

    def _migrate(self,conn):
        import sys
        from mpres import __version__
        version=conn.execute('PRAGMA user_version').fetchone()[0]
        if not 1<=version<=self.SCHEMA_VERSION:raise MPresError('Unsupported compact database schema; do not auto-recreate it')
        self._audit_schema(conn)
        while version<self.SCHEMA_VERSION:
            # One serialized transition. A failed transition rolls back DDL and
            # keeps a separate durable failure record, never forged old history.
            conn.execute('BEGIN IMMEDIATE')
            version=conn.execute('PRAGMA user_version').fetchone()[0]
            if version>=self.SCHEMA_VERSION:
                conn.commit();break
            target=version+1;stamp=utc_now()
            trigger=encode({'argv':sys.argv,'entry':'Store.connect','explicit_actor_label':getattr(self,'migration_actor',None),'historical_actor':'unknown'})
            conn.execute('SAVEPOINT migration_body')
            try:
                if target==2:
                    conn.execute("CREATE TABLE pool_slots (id INTEGER PRIMARY KEY,key TEXT NOT NULL UNIQUE,kind TEXT NOT NULL CHECK(kind IN ('write','edit','review')),channel TEXT NOT NULL,family TEXT NOT NULL,model TEXT NOT NULL,effort TEXT NOT NULL,ordinal INTEGER NOT NULL,session_id TEXT UNIQUE REFERENCES sessions(id),state TEXT NOT NULL CHECK(state IN ('pending','creating','ready','uncertain')))")
                    conn.execute("CREATE TABLE runtime_host (singleton INTEGER PRIMARY KEY CHECK(singleton=1),report_json TEXT NOT NULL,observed_at TEXT NOT NULL)")
                    conn.execute('ALTER TABLE task ADD COLUMN author_slots_limit INTEGER')
                else:
                    for statement in Path(__file__).with_name(f'migrate_{target}.sql').read_text().split(';'):
                        if statement.strip():conn.execute(statement)
                conn.execute(f'PRAGMA user_version={target}')
                conn.execute('RELEASE migration_body')
                conn.execute('INSERT INTO migration_audit(from_version,to_version,program_version,trigger_json,started_at,finished_at,state) VALUES(?,?,?,?,?,?,?)',(version,target,__version__,trigger,stamp,utc_now(),'succeeded'))
                conn.commit();version=target
            except Exception as exc:
                conn.execute('ROLLBACK TO migration_body');conn.execute('RELEASE migration_body')
                conn.execute('INSERT INTO migration_audit(from_version,to_version,program_version,trigger_json,started_at,finished_at,state,error) VALUES(?,?,?,?,?,?,?,?)',(version,target,__version__,trigger,stamp,utc_now(),'failed',f'{type(exc).__name__}: {exc}'))
                conn.commit();raise

    def initialize(self, title: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise MPresError('Task database already exists')
        from .maintenance_lock import writable_connection
        conn = writable_connection(self.path,self.task)
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.executescript(Path(__file__).with_name('schema.sql').read_text())
            conn.execute('INSERT INTO task(singleton,title,status,created_at) VALUES(1,?,?,?)',
                         (title, 'draft', utc_now()))
            self._audit_schema(conn)
            from mpres import __version__
            conn.execute('INSERT INTO migration_audit(to_version,program_version,trigger_json,started_at,finished_at,state) VALUES(?,?,?,?,?,?)',(self.SCHEMA_VERSION,__version__,encode({'entry':'Store.initialize'}),utc_now(),utc_now(),'initialized'))
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def rows(self, query: str, params: tuple = ()) -> list[dict]:
        conn = self.connect()
        try:
            return [dict(row) for row in conn.execute(query, params)]
        finally:
            conn.close()

    def backup(self, destination: Path) -> None:
        if destination.exists():
            raise MPresError('Refusing to replace an existing backup')
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self.connect()
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()


def event(conn: sqlite3.Connection, kind: str, detail: Any, job: str | None = None) -> None:
    conn.execute('INSERT INTO events(kind,job_id,detail_json,created_at) VALUES(?,?,?,?)',
                 (kind, job, encode(detail), utc_now()))
