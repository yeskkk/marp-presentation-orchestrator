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

    def connect(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise MPresError(f'No compact task database: {self.path}')
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=30000')
        conn.execute('PRAGMA synchronous=FULL')
        if conn.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            conn.close()
            raise MPresError('SQLite foreign keys could not be enabled')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version == 1:
            try:
                conn.execute('BEGIN IMMEDIATE')
                if conn.execute('PRAGMA user_version').fetchone()[0] == 1:
                    # Migration is additive and atomic. It does not alter any confirmed profile.
                    conn.execute("CREATE TABLE pool_slots (id INTEGER PRIMARY KEY,key TEXT NOT NULL UNIQUE,kind TEXT NOT NULL CHECK(kind IN ('write','edit','review')),channel TEXT NOT NULL,family TEXT NOT NULL,model TEXT NOT NULL,effort TEXT NOT NULL,ordinal INTEGER NOT NULL,session_id TEXT UNIQUE REFERENCES sessions(id),state TEXT NOT NULL CHECK(state IN ('pending','creating','ready','uncertain')))")
                    conn.execute("CREATE TABLE runtime_host (singleton INTEGER PRIMARY KEY CHECK(singleton=1),report_json TEXT NOT NULL,observed_at TEXT NOT NULL)")
                    conn.execute('ALTER TABLE task ADD COLUMN author_slots_limit INTEGER')
                    conn.execute('PRAGMA user_version=2')
                conn.commit()
            except Exception:
                conn.rollback()
                conn.close()
                raise
            version = 2
        if version == 2:
            try:
                conn.execute('BEGIN IMMEDIATE')
                if conn.execute('PRAGMA user_version').fetchone()[0] == 2:
                    sql = Path(__file__).with_name('migrate_3.sql').read_text()
                    for statement in sql.split(';'):
                        if statement.strip():
                            conn.execute(statement)
                    conn.execute('PRAGMA user_version=3')
                conn.commit()
            except Exception:
                conn.rollback()
                conn.close()
                raise
            version = 3
        if version == 3:
            try:
                conn.execute('BEGIN IMMEDIATE')
                if conn.execute('PRAGMA user_version').fetchone()[0] == 3:
                    for statement in Path(__file__).with_name('migrate_4.sql').read_text().split(';'):
                        if statement.strip():
                            conn.execute(statement)
                    conn.execute('PRAGMA user_version=4')
                conn.commit()
            except Exception:
                conn.rollback()
                conn.close()
                raise
            version = 4
        if version == 4:
            try:
                conn.execute('BEGIN IMMEDIATE')
                if conn.execute('PRAGMA user_version').fetchone()[0] == 4:
                    for statement in Path(__file__).with_name('migrate_5.sql').read_text().split(';'):
                        if statement.strip(): conn.execute(statement)
                    conn.execute('PRAGMA user_version=5')
                conn.commit()
            except Exception:
                conn.rollback(); conn.close(); raise
            version = 5
        if version == 5:
            try:
                conn.execute('BEGIN IMMEDIATE')
                if conn.execute('PRAGMA user_version').fetchone()[0] == 5:
                    for statement in Path(__file__).with_name('migrate_6.sql').read_text().split(';'):
                        if statement.strip(): conn.execute(statement)
                    conn.execute('PRAGMA user_version=6')
                conn.commit()
            except Exception:
                conn.rollback(); conn.close(); raise
            version = 6
        if version != 6:
            conn.close()
            raise MPresError('Unsupported compact database schema; do not auto-recreate it')
        return conn

    def initialize(self, title: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise MPresError('Task database already exists')
        conn = sqlite3.connect(self.path)
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.executescript(Path(__file__).with_name('schema.sql').read_text())
            conn.execute('INSERT INTO task(singleton,title,status,created_at) VALUES(1,?,?,?)',
                         (title, 'draft', utc_now()))
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
