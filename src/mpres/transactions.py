from __future__ import annotations

import inspect
import json
import os
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from copy import deepcopy
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, ParamSpec, TypeVar, cast

from mpres.util import MPresError, read_json, read_yaml, task_path, utc_now, write_json_atomic, write_yaml_atomic

P = ParamSpec("P")
R = TypeVar("R")
STORE_SCHEMA_VERSION = 1
DATABASE_FILENAME = "mutable-state.sqlite3"


class ConcurrentStateUpdateError(MPresError):
    """A stale mutable-state snapshot attempted to overwrite a newer revision."""


class MutableStateStoreError(MPresError):
    """The task-local transactional mutable-state store is unavailable or malformed."""


@dataclass
class _PendingProjection:
    document_id: str
    revision: int
    payload: dict[str, Any]
    path: Path
    format: str


@dataclass
class _Session:
    root: Path
    slug: str
    connection: sqlite3.Connection
    depth: int = 1
    rollback_only: bool = False
    pending: dict[str, _PendingProjection] = field(default_factory=dict)


_ACTIVE_SESSION: ContextVar[_Session | None] = ContextVar("mpres_mutable_state_session", default=None)


def database_path(root: Path, slug: str) -> Path:
    return task_path(root, slug) / "state" / DATABASE_FILENAME


def _connect(root: Path, slug: str) -> sqlite3.Connection:
    path = database_path(root, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        connection = sqlite3.connect(
            path,
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mutable_documents (
                document_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL CHECK (revision >= 0),
                payload_json TEXT NOT NULL,
                projection_path TEXT NOT NULL,
                projection_format TEXT NOT NULL,
                updated_utc TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transaction_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                document_id TEXT,
                revision INTEGER,
                created_utc TEXT NOT NULL,
                detail_json TEXT NOT NULL
            )
            """
        )
        return connection
    except sqlite3.Error as exc:
        raise MutableStateStoreError(f"Cannot open mutable-state store {path}: {exc}") from exc


def _active_for(root: Path, slug: str) -> _Session | None:
    active = _ACTIVE_SESSION.get()
    if active is None:
        return None
    resolved_root = root.resolve()
    if active.root != resolved_root or active.slug != slug:
        raise MutableStateStoreError(
            "Nested mutable-state transactions may not switch task roots or task slugs."
        )
    return active


def _encode(payload: Mapping[str, Any]) -> str:
    try:
        return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise MutableStateStoreError(f"Mutable state is not JSON-serializable: {exc}") from exc


def _decode(raw: str, *, document_id: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MutableStateStoreError(
            f"Transactional document {document_id!r} contains invalid JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise MutableStateStoreError(
            f"Transactional document {document_id!r} must contain a mapping."
        )
    return value


def _read_projection(path: Path, format: str) -> dict[str, Any]:
    if format == "json":
        value = read_json(path)
    elif format == "yaml":
        value = read_yaml(path)
    else:
        raise MutableStateStoreError(f"Unsupported projection format: {format!r}")
    if not isinstance(value, dict):
        raise MutableStateStoreError(f"Mutable-state projection must be a mapping: {path}")
    return value


def _write_projection(path: Path, format: str, payload: Mapping[str, Any]) -> None:
    if format == "json":
        write_json_atomic(path, dict(payload))
    elif format == "yaml":
        write_yaml_atomic(path, dict(payload))
    else:
        raise MutableStateStoreError(f"Unsupported projection format: {format!r}")


def _projection_matches(path: Path, format: str, payload: Mapping[str, Any]) -> bool:
    try:
        return _read_projection(path, format) == dict(payload)
    except MPresError:
        return False


def _event(
    connection: sqlite3.Connection,
    event_type: str,
    *,
    document_id: str | None = None,
    revision: int | None = None,
    detail: Mapping[str, Any] | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO transaction_events(event_type, document_id, revision, created_utc, detail_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            event_type,
            document_id,
            revision,
            utc_now(),
            json.dumps(dict(detail or {}), ensure_ascii=False, sort_keys=True),
        ),
    )


def _select(connection: sqlite3.Connection, document_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT document_id, revision, payload_json, projection_path, projection_format, updated_utc
        FROM mutable_documents WHERE document_id = ?
        """,
        (document_id,),
    ).fetchone()


def _ensure_document_in_connection(
    connection: sqlite3.Connection,
    *,
    document_id: str,
    projection_path: Path,
    projection_format: str,
    revision_field: str,
) -> tuple[dict[str, Any], int, bool]:
    row = _select(connection, document_id)
    if row is not None:
        payload = _decode(str(row["payload_json"]), document_id=document_id)
        revision = int(row["revision"])
        payload[revision_field] = revision
        return payload, revision, False

    payload = _read_projection(projection_path, projection_format)
    raw_revision = payload.get(revision_field, 0)
    if isinstance(raw_revision, bool) or not isinstance(raw_revision, int) or raw_revision < 0:
        raise MutableStateStoreError(
            f"{projection_path} field {revision_field!r} must be a non-negative integer."
        )
    revision = int(raw_revision)
    payload[revision_field] = revision
    connection.execute(
        """
        INSERT INTO mutable_documents(
            document_id, revision, payload_json, projection_path, projection_format, updated_utc
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            revision,
            _encode(payload),
            str(projection_path.resolve()),
            projection_format,
            utc_now(),
        ),
    )
    _event(
        connection,
        "projection-imported",
        document_id=document_id,
        revision=revision,
        detail={"projection_path": str(projection_path)},
    )
    return payload, revision, True


def _queue_projection(
    session: _Session,
    *,
    document_id: str,
    revision: int,
    payload: Mapping[str, Any],
    path: Path,
    format: str,
) -> None:
    session.pending[document_id] = _PendingProjection(
        document_id=document_id,
        revision=revision,
        payload=deepcopy(dict(payload)),
        path=path,
        format=format,
    )


def _flush_projections(root: Path, slug: str, pending: Mapping[str, _PendingProjection]) -> None:
    if not pending:
        return
    connection = _connect(root, slug)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for item in pending.values():
            row = _select(connection, item.document_id)
            if row is None or int(row["revision"]) != item.revision:
                continue
            _write_projection(item.path, item.format, item.payload)
        connection.execute("COMMIT")
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        connection.close()


@contextmanager
def task_mutation_transaction(root: Path, slug: str) -> Iterator[None]:
    """Serialize one task mutation, including nested control-plane calls.

    SQLite owns the process-safe writer lock.  Nested calls for the same task
    reuse the outer transaction, so no lock file or lock protocol is exposed to
    agents.  JSON and YAML files are projections written only after commit.
    """

    root = root.resolve()
    existing = _active_for(root, slug)
    if existing is not None:
        existing.depth += 1
        try:
            yield
        except Exception:
            existing.rollback_only = True
            raise
        finally:
            existing.depth -= 1
        return

    connection = _connect(root, slug)
    session = _Session(root=root, slug=slug, connection=connection)
    token: Token[_Session | None] = _ACTIVE_SESSION.set(session)
    committed = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        _event(connection, "transaction-began", detail={"process_id": os.getpid()})
        yield
        if session.rollback_only:
            raise MutableStateStoreError("Nested task mutation marked the transaction for rollback.")
        _event(connection, "transaction-committed", detail={"process_id": os.getpid()})
        connection.execute("COMMIT")
        committed = True
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        _ACTIVE_SESSION.reset(token)
        connection.close()
    if committed:
        _flush_projections(root, slug, session.pending)


def transactional_task_mutation(function: Callable[P, R]) -> Callable[P, R]:
    """Decorate a ``(root, slug, ...)`` task mutator with a reentrant transaction."""

    signature = inspect.signature(function)

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        bound = signature.bind_partial(*args, **kwargs)
        root = bound.arguments.get("root")
        slug = bound.arguments.get("slug")
        if root is None or slug is None:
            raise MutableStateStoreError(
                f"Transactional function {function.__name__} requires root and slug arguments."
            )
        with task_mutation_transaction(Path(cast(Any, root)), str(slug)):
            return function(*args, **kwargs)

    return wrapped


def initialize_document(
    root: Path,
    slug: str,
    *,
    document_id: str,
    payload: Mapping[str, Any],
    projection_path: Path,
    projection_format: str,
    revision_field: str,
) -> dict[str, Any]:
    """Create a canonical document and its human-readable projection once."""

    root = root.resolve()
    connection = _connect(root, slug)
    value = deepcopy(dict(payload))
    raw_revision = value.get(revision_field, 0)
    if isinstance(raw_revision, bool) or not isinstance(raw_revision, int) or raw_revision < 0:
        raise MutableStateStoreError(f"{revision_field} must be a non-negative integer.")
    revision = int(raw_revision)
    value[revision_field] = revision
    try:
        connection.execute("BEGIN IMMEDIATE")
        if _select(connection, document_id) is not None:
            raise MutableStateStoreError(f"Transactional document already exists: {document_id}")
        connection.execute(
            """
            INSERT INTO mutable_documents(
                document_id, revision, payload_json, projection_path, projection_format, updated_utc
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                revision,
                _encode(value),
                str(projection_path.resolve()),
                projection_format,
                utc_now(),
            ),
        )
        _event(
            connection,
            "document-initialized",
            document_id=document_id,
            revision=revision,
            detail={"projection_path": str(projection_path)},
        )
        connection.execute("COMMIT")
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        connection.close()
    _flush_projections(
        root,
        slug,
        {
            document_id: _PendingProjection(
                document_id=document_id,
                revision=revision,
                payload=value,
                path=projection_path,
                format=projection_format,
            )
        },
    )
    return value


def read_document(
    root: Path,
    slug: str,
    *,
    document_id: str,
    projection_path: Path,
    projection_format: str,
    revision_field: str,
) -> dict[str, Any]:
    """Read canonical state, importing an existing v0.6.3 projection on first use."""

    root = root.resolve()
    session = _active_for(root, slug)
    owns_transaction = session is None
    connection = session.connection if session else _connect(root, slug)
    pending: dict[str, _PendingProjection] = {}
    try:
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")
        payload, revision, imported = _ensure_document_in_connection(
            connection,
            document_id=document_id,
            projection_path=projection_path,
            projection_format=projection_format,
            revision_field=revision_field,
        )
        needs_projection = imported or not _projection_matches(
            projection_path, projection_format, payload
        )
        if needs_projection:
            item = _PendingProjection(
                document_id=document_id,
                revision=revision,
                payload=payload,
                path=projection_path,
                format=projection_format,
            )
            if session:
                _queue_projection(
                    session,
                    document_id=document_id,
                    revision=revision,
                    payload=payload,
                    path=projection_path,
                    format=projection_format,
                )
            else:
                pending[document_id] = item
        if owns_transaction:
            connection.execute("COMMIT")
    except Exception:
        if owns_transaction:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        raise
    finally:
        if owns_transaction:
            connection.close()
    if owns_transaction:
        _flush_projections(root, slug, pending)
    return deepcopy(payload)


def save_document(
    root: Path,
    slug: str,
    *,
    document_id: str,
    payload: Mapping[str, Any],
    projection_path: Path,
    projection_format: str,
    revision_field: str,
) -> dict[str, Any]:
    """Compare-and-swap one loaded document; stale writers fail instead of overwriting."""

    root = root.resolve()
    value = deepcopy(dict(payload))
    expected = value.get(revision_field)
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise ConcurrentStateUpdateError(
            f"{document_id} lacks a valid loaded {revision_field}; load it before saving."
        )
    session = _active_for(root, slug)
    owns_transaction = session is None
    connection = session.connection if session else _connect(root, slug)
    pending: dict[str, _PendingProjection] = {}
    try:
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")
        current, revision, _ = _ensure_document_in_connection(
            connection,
            document_id=document_id,
            projection_path=projection_path,
            projection_format=projection_format,
            revision_field=revision_field,
        )
        del current
        if revision != expected:
            raise ConcurrentStateUpdateError(
                f"Concurrent update detected for {document_id}: loaded revision {expected}, "
                f"current revision {revision}. Re-run the complete command against current state."
            )
        next_revision = revision + 1
        value[revision_field] = next_revision
        cursor = connection.execute(
            """
            UPDATE mutable_documents
            SET revision = ?, payload_json = ?, projection_path = ?, projection_format = ?, updated_utc = ?
            WHERE document_id = ? AND revision = ?
            """,
            (
                next_revision,
                _encode(value),
                str(projection_path.resolve()),
                projection_format,
                utc_now(),
                document_id,
                revision,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrentStateUpdateError(f"Concurrent update detected for {document_id}.")
        _event(
            connection,
            "document-updated",
            document_id=document_id,
            revision=next_revision,
            detail={"previous_revision": revision},
        )
        if session:
            _queue_projection(
                session,
                document_id=document_id,
                revision=next_revision,
                payload=value,
                path=projection_path,
                format=projection_format,
            )
        else:
            pending[document_id] = _PendingProjection(
                document_id=document_id,
                revision=next_revision,
                payload=value,
                path=projection_path,
                format=projection_format,
            )
        if owns_transaction:
            connection.execute("COMMIT")
    except Exception:
        if owns_transaction:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        raise
    finally:
        if owns_transaction:
            connection.close()
    if owns_transaction:
        _flush_projections(root, slug, pending)
    return value


def update_document(
    root: Path,
    slug: str,
    *,
    document_id: str,
    projection_path: Path,
    projection_format: str,
    revision_field: str,
    mutator: Callable[[dict[str, Any]], Mapping[str, Any] | None],
) -> dict[str, Any]:
    """Atomically read, validate and update a document under the task writer transaction."""

    root = root.resolve()
    session = _active_for(root, slug)
    if session is None:
        with task_mutation_transaction(root, slug):
            return update_document(
                root,
                slug,
                document_id=document_id,
                projection_path=projection_path,
                projection_format=projection_format,
                revision_field=revision_field,
                mutator=mutator,
            )

    current, revision, _ = _ensure_document_in_connection(
        session.connection,
        document_id=document_id,
        projection_path=projection_path,
        projection_format=projection_format,
        revision_field=revision_field,
    )
    working = deepcopy(current)
    result = mutator(working)
    value = deepcopy(dict(working if result is None else result))
    next_revision = revision + 1
    value[revision_field] = next_revision
    cursor = session.connection.execute(
        """
        UPDATE mutable_documents
        SET revision = ?, payload_json = ?, projection_path = ?, projection_format = ?, updated_utc = ?
        WHERE document_id = ? AND revision = ?
        """,
        (
            next_revision,
            _encode(value),
            str(projection_path.resolve()),
            projection_format,
            utc_now(),
            document_id,
            revision,
        ),
    )
    if cursor.rowcount != 1:
        raise ConcurrentStateUpdateError(f"Concurrent update detected for {document_id}.")
    _event(
        session.connection,
        "document-updated",
        document_id=document_id,
        revision=next_revision,
        detail={"previous_revision": revision},
    )
    _queue_projection(
        session,
        document_id=document_id,
        revision=next_revision,
        payload=value,
        path=projection_path,
        format=projection_format,
    )
    return value


def transaction_status(root: Path, slug: str) -> dict[str, Any]:
    root = root.resolve()
    path = database_path(root, slug)
    connection = _connect(root, slug)
    try:
        rows = connection.execute(
            """
            SELECT document_id, revision, payload_json, projection_path, projection_format, updated_utc
            FROM mutable_documents ORDER BY document_id
            """
        ).fetchall()
        documents: list[dict[str, Any]] = []
        for row in rows:
            document_id = str(row["document_id"])
            projection = Path(str(row["projection_path"]))
            projection_format = str(row["projection_format"])
            payload = _decode(str(row["payload_json"]), document_id=document_id)
            payload_revision = int(row["revision"])
            revision_field = (
                "state_revision" if document_id == "task-state" else "registry_revision"
            )
            payload[revision_field] = payload_revision
            projection_matches = _projection_matches(projection, projection_format, payload)
            documents.append(
                {
                    "document_id": document_id,
                    "revision": payload_revision,
                    "projection_path": str(projection),
                    "projection_format": projection_format,
                    "projection_exists": projection.is_file(),
                    "projection_matches": projection_matches,
                    "updated_utc": str(row["updated_utc"]),
                }
            )
        event_count = int(
            connection.execute("SELECT COUNT(*) FROM transaction_events").fetchone()[0]
        )
    finally:
        connection.close()
    return {
        "schema_version": STORE_SCHEMA_VERSION,
        "task_slug": slug,
        "database": str(path),
        "single_writer": "sqlite-begin-immediate",
        "documents": documents,
        "event_count": event_count,
        "ok": bool(documents)
        and all(item["projection_exists"] and item["projection_matches"] for item in documents),
    }
