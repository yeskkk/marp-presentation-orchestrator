"""Cross-process maintenance leases; native Windows conservatively serializes.

A lease is advisory for mpres processes, not a claim to control unrelated tools.
No stale PID deletion, no permission elevation, no lockfile-as-execution-status.
"""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from mpres.util import MPresError

class Lease:
    def __init__(self, task: Path, *, exclusive=False):
        path=task/'.mpres'/'maintenance.lock'
        path.parent.mkdir(parents=True,exist_ok=True)
        self.file=path.open('a+b');self.closed=False
        try:
            if os.name=='nt':
                import msvcrt
                if self.file.seek(0,2)==0:self.file.write(b'0');self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK if exclusive else msvcrt.LK_NBRLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)|fcntl.LOCK_NB)
        except (OSError,ImportError) as exc:
            self.file.close();self.closed=True
            raise MPresError('Task is in use or maintenance is active; stop the adapter and retry at a safe point') from exc
    def close(self):
        if self.closed:return
        try:
            if os.name=='nt':
                import msvcrt
                self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
        finally:self.file.close();self.closed=True
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

class LeasedConnection(sqlite3.Connection):
    _lease=None
    def close(self):
        try:super().close()
        finally:
            if self._lease:self._lease.close();self._lease=None

def writable_connection(path: Path, task: Path, **kwargs):
    lease=Lease(task)
    try:
        c=sqlite3.connect(path,factory=LeasedConnection,**kwargs);c._lease=lease;return c
    except Exception:lease.close();raise

def readonly_connection(path: Path):
    if not path.is_file() or path.is_symlink():raise MPresError('Missing/unsafe database: '+str(path))
    c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=10,isolation_level=None)
    c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');return c
