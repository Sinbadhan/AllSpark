import os
import stat
from pathlib import Path

from allspark.core.i18n import t

PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


class StoragePermissionError(PermissionError):
    """Raised when local sensitive data cannot be stored with a safe boundary."""


def _is_untrusted_symlink(path: Path) -> bool:
    return path.is_symlink() and path.lstat().st_uid != 0


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _require_owned(path: Path) -> None:
    if os.name != "posix" or not hasattr(os, "getuid"):
        return
    if path.stat().st_uid != os.getuid():
        raise StoragePermissionError(t("storage_path_not_owned", path=str(path)))


def ensure_private_directory(path: Path, *, create: bool = True) -> None:
    """Create or migrate an AllSpark-owned directory to owner-only access."""
    if os.name != "posix":
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return

    if _is_untrusted_symlink(path):
        raise StoragePermissionError(t("storage_directory_symlink", path=str(path)))
    if create:
        path.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
    if not path.exists():
        return
    if not path.is_dir():
        raise StoragePermissionError(t("storage_path_not_directory", path=str(path)))
    _require_owned(path)
    path.chmod(PRIVATE_DIRECTORY_MODE)


def validate_no_directory_symlinks(path: Path) -> None:
    """Reject lexical directory components that redirect sensitive storage."""
    if os.name != "posix":
        return
    current = path.absolute()
    for directory in (current, *current.parents):
        if _is_untrusted_symlink(directory):
            raise StoragePermissionError(
                t("storage_directory_symlink", path=str(directory))
            )


def validate_ancestor_chain(path: Path) -> None:
    """Reject an ancestor chain that permits directory-entry replacement."""
    if os.name != "posix":
        return
    current = path.resolve()
    for directory in (current, *current.parents):
        if not directory.is_dir():
            raise StoragePermissionError(
                t("storage_path_not_directory", path=str(directory))
            )
        mode = _mode(directory)
        writable_by_others = bool(mode & 0o022)
        sticky_directory = bool(mode & stat.S_ISVTX)
        if writable_by_others and not sticky_directory:
            raise StoragePermissionError(
                t(
                    "storage_parent_writable",
                    path=str(directory),
                    mode=f"{mode:04o}",
                )
            )


def ensure_private_file(path: Path) -> None:
    """Migrate one existing sensitive regular file to owner-only access."""
    if os.name != "posix" or not path.exists():
        return
    if path.is_symlink() or not path.is_file():
        raise StoragePermissionError(t("storage_path_not_regular", path=str(path)))
    _require_owned(path)
    path.chmod(PRIVATE_FILE_MODE)


def prepare_database_path(db_path: Path, *, managed_root: Path | None) -> None:
    """Prepare a SQLite path without mutating an unrelated custom parent."""
    validate_no_directory_symlinks(db_path.parent)
    parent_existed = db_path.parent.exists()
    existing_ancestor = db_path.parent
    while not existing_ancestor.exists():
        existing_ancestor = existing_ancestor.parent
    validate_ancestor_chain(existing_ancestor)
    db_path.parent.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)

    if managed_root is not None:
        ensure_private_directory(managed_root)
        if db_path.parent != managed_root:
            ensure_private_directory(db_path.parent)
    elif not parent_existed:
        ensure_private_directory(db_path.parent)

    validate_no_directory_symlinks(db_path.parent)
    validate_ancestor_chain(db_path.parent)

    secure_database_files(db_path)


def secure_database_files(db_path: Path) -> None:
    """Harden the database plus any SQLite journal sidecars that exist."""
    for path in (
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
        Path(f"{db_path}-journal"),
    ):
        ensure_private_file(path)
