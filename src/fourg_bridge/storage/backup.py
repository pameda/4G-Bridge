"""Recoverable local SQLite snapshots; never delete or reset source records."""

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4


def backup_database(path: Path, *, corrupt: bool = False) -> Path:
    directory = path.parent / "backups" / f"{path.stem}-{uuid4().hex}"
    directory.mkdir(parents=True, mode=0o700)
    target = directory / path.name
    if corrupt:
        # Preserve the complete file group. The caller must have stopped its own writers.
        for suffix in ("", "-wal", "-shm", "-journal"):
            source = Path(str(path) + suffix)
            if source.exists():
                saved = directory / source.name
                shutil.copy2(source, saved)
                saved.chmod(0o600)
    else:
        with (
            closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection,
            closing(sqlite3.connect(target)) as destination,
        ):
            connection.backup(destination)
        target.chmod(0o600)
    return directory
