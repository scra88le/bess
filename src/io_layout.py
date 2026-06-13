"""File-layout contract and the single I/O seam for the optimiser/runner.

Everything that reads or writes the date-partitioned data layout goes through
here, so the storage backend is just an fsspec URL: ``./data`` locally today,
``s3://bucket/prefix`` later, with no code change elsewhere.

Layout (``root`` is an fsspec URL):

    <root>/prices/    date=YYYY-MM-DD/ forecast.<ext>
    <root>/schedules/ date=YYYY-MM-DD/ dispatch.<ext>
    <root>/telemetry/ date=YYYY-MM-DD/ part-<minute>.<ext>
    <root>/state/     battery_state.json

Tables are written as Parquet when pyarrow is importable, else newline-delimited
JSON. The path/partition contract is identical either way.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Dict, List, Optional, Union

import fsspec

try:  # Parquet preferred; JSONL fallback keeps the contract portable.
    import pyarrow as _pa
    import pyarrow.parquet as _pq
    _HAVE_PARQUET = True
except ImportError:  # pragma: no cover - exercised only without pyarrow
    _HAVE_PARQUET = False

TABLE_EXT = "parquet" if _HAVE_PARQUET else "jsonl"

DateLike = Union[str, _dt.date]
Record = Dict[str, Any]


class MissingArtifactError(FileNotFoundError):
    """Raised when a required prices/schedule/state artifact is absent.

    Surfaces a missing day rather than silently coasting on stale data.
    """


# --------------------------------------------------------------------- #
# Path builders (the contract)
# --------------------------------------------------------------------- #
def _norm_date(date: DateLike) -> str:
    return date if isinstance(date, str) else date.isoformat()


def _base(root: str) -> str:
    return root.rstrip("/")


def prices_path(root: str, date: DateLike) -> str:
    return f"{_base(root)}/prices/date={_norm_date(date)}/forecast.{TABLE_EXT}"


def schedule_path(root: str, date: DateLike) -> str:
    return f"{_base(root)}/schedules/date={_norm_date(date)}/dispatch.{TABLE_EXT}"


def telemetry_path(root: str, date: DateLike, minute_index: int) -> str:
    return (f"{_base(root)}/telemetry/date={_norm_date(date)}/"
            f"part-{int(minute_index):04d}.{TABLE_EXT}")


def state_path(root: str) -> str:
    return f"{_base(root)}/state/battery_state.json"


# --------------------------------------------------------------------- #
# I/O primitives (fsspec-backed, atomic)
# --------------------------------------------------------------------- #
def _fs_and_path(path: str):
    return fsspec.core.url_to_fs(path)


def exists(path: str) -> bool:
    fs, p = _fs_and_path(path)
    return fs.exists(p)


def _ensure_parent(fs, p: str) -> None:
    parent = p.rsplit("/", 1)[0]
    if parent and parent != p:
        try:
            fs.makedirs(parent, exist_ok=True)
        except (FileExistsError, NotImplementedError):
            pass


def _atomic_write(fs, p: str, write_fn) -> None:
    """Write via a temp object then move into place (atomic on local + S3)."""
    _ensure_parent(fs, p)
    tmp = p + ".tmp"
    write_fn(tmp)
    if fs.exists(p):
        fs.rm(p)
    fs.mv(tmp, p)


def write_table(path: str, records: List[Record]) -> None:
    """Write a list of row dicts as Parquet (preferred) or JSONL."""
    fs, p = _fs_and_path(path)

    def _write(tmp: str) -> None:
        if _HAVE_PARQUET and p.endswith(".parquet"):
            table = _pa.Table.from_pylist(records)
            with fs.open(tmp, "wb") as fh:
                _pq.write_table(table, fh)
        else:
            with fs.open(tmp, "w") as fh:
                for rec in records:
                    fh.write(json.dumps(rec) + "\n")

    _atomic_write(fs, p, _write)


def read_table(path: str) -> List[Record]:
    """Read a table written by :func:`write_table` into a list of row dicts."""
    fs, p = _fs_and_path(path)
    if not fs.exists(p):
        raise MissingArtifactError(path)
    if _HAVE_PARQUET and p.endswith(".parquet"):
        with fs.open(p, "rb") as fh:
            return _pq.read_table(fh).to_pylist()
    with fs.open(p, "r") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_json(path: str, obj: Dict[str, Any]) -> None:
    fs, p = _fs_and_path(path)

    def _write(tmp: str) -> None:
        with fs.open(tmp, "w") as fh:
            fh.write(json.dumps(obj, indent=2))

    _atomic_write(fs, p, _write)


def read_json(path: str) -> Optional[Dict[str, Any]]:
    """Read a JSON object, or return None if the file is absent."""
    fs, p = _fs_and_path(path)
    if not fs.exists(p):
        return None
    with fs.open(p, "r") as fh:
        return json.load(fh)
