#!/usr/bin/env python3
"""Build and verify a self-contained macOS offline delivery bundle.

The build host may use the network to install build dependencies. The produced
archive contains the Python runtime, application dependencies, bundled core
knowledge, integrity metadata, and offline install/rollback launchers.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EPOCH = 1_700_000_000
MANIFEST_NAME = "delivery-manifest.json"
CHECKSUM_NAME = "SHA256SUMS"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_version() -> str:
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]

    with (ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def _source_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _source_is_dirty() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _target_name() -> str:
    machine = platform.machine().lower()
    if sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    if sys.platform == "darwin" and machine == "x86_64":
        return "macos-x86_64"
    raise RuntimeError("offline desktop bundles must be built on the target macOS architecture")


def _iter_files(root: Path) -> Iterable[Path]:
    return sorted((path for path in root.rglob("*") if path.is_file()), key=lambda p: p.as_posix())


def _normalize_tree(root: Path, epoch: int) -> None:
    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix()):
        if path.is_symlink():
            continue
        mode = path.stat().st_mode
        if path.is_dir():
            path.chmod(0o755)
        elif mode & stat.S_IXUSR:
            path.chmod(0o755)
        else:
            path.chmod(0o644)
        os.utime(path, (epoch, epoch), follow_symlinks=False)


def _normalize_macho_uuid(executable: Path) -> None:
    """Replace PyInstaller's random arm64 Mach-O UUID with a content-derived UUID."""
    data = bytearray(executable.read_bytes())
    if data[:4] != b"\xcf\xfa\xed\xfe":
        raise ValueError("expected a thin little-endian 64-bit Mach-O executable")
    ncmds = struct.unpack_from("<I", data, 16)[0]
    offset = 32
    uuid_offset = None
    for _ in range(ncmds):
        command, command_size = struct.unpack_from("<II", data, offset)
        if command_size < 8 or offset + command_size > len(data):
            raise ValueError("invalid Mach-O load command")
        if command == 0x1B:  # LC_UUID
            if command_size != 24:
                raise ValueError("invalid Mach-O LC_UUID command")
            uuid_offset = offset + 8
            break
        offset += command_size
    if uuid_offset is None:
        raise ValueError("Mach-O executable has no LC_UUID command")

    data[uuid_offset : uuid_offset + 16] = b"\0" * 16
    normalized_uuid = bytearray(hashlib.sha256(data).digest()[:16])
    normalized_uuid[6] = (normalized_uuid[6] & 0x0F) | 0x50
    normalized_uuid[8] = (normalized_uuid[8] & 0x3F) | 0x80
    data[uuid_offset : uuid_offset + 16] = normalized_uuid
    executable.write_bytes(data)


def _resign_main_executable(payload: Path, sign_identity: str | None) -> None:
    executable = payload / "AllSpark"
    subprocess.run(["codesign", "--remove-signature", str(executable)], check=True)
    _normalize_macho_uuid(executable)
    command = ["codesign", "--force", "--identifier", "io.github.sinbadhan.allspark"]
    if sign_identity:
        command.extend(["--options", "runtime", "--timestamp", "--sign", sign_identity])
    else:
        command.extend(["--sign", "-"])
    command.append(str(executable))
    subprocess.run(command, check=True)
    subprocess.run(["codesign", "--verify", "--strict", "--verbose=2", str(executable)], check=True)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _write_executable(path: Path, content: str, epoch: int) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)
    os.utime(path, (epoch, epoch))


def _installer_script(version: str, artifact_id: str) -> str:
    version_dir = f"{version}-{artifact_id}"
    return f"""#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"
shasum -a 256 -c {CHECKSUM_NAME}

replace_link() {{
  TARGET=$1
  LINK=$2
  rm -f "$LINK.next"
  ln -s "$TARGET" "$LINK.next"
  if mv -f -T "$LINK.next" "$LINK" 2>/dev/null; then return 0; fi
  mv -f -h "$LINK.next" "$LINK"
}}

BASE="$HOME/Applications/AllSpark"
VERSIONS="$BASE/versions"
DEST="$VERSIONS/{version_dir}"
mkdir -p "$VERSIONS"
if [ ! -d "$DEST" ]; then
  TMP="$VERSIONS/.{version_dir}.$$"
  rm -rf "$TMP"
  cp -R "$ROOT/payload/AllSpark" "$TMP"
  mv "$TMP" "$DEST"
fi

CURRENT=""
if [ -L "$BASE/current" ]; then CURRENT=$(readlink "$BASE/current"); fi
if [ -n "$CURRENT" ] && [ "$CURRENT" != "$DEST" ]; then
  replace_link "$CURRENT" "$BASE/previous"
fi
replace_link "$DEST" "$BASE/current"
cp "$ROOT/Launch AllSpark Web.command" "$BASE/Launch AllSpark Web.command"
cp "$ROOT/Launch AllSpark CLI.command" "$BASE/Launch AllSpark CLI.command"
cp "$ROOT/Roll Back AllSpark.command" "$BASE/Roll Back AllSpark.command"
cp "$ROOT/Install Optional Model.command" "$BASE/Install Optional Model.command"
chmod 755 "$BASE"/*.command
printf '\nAllSpark {version} installed in %s\n' "$DEST"
printf 'Open %s to start the supported Web flow.\n' "$BASE/Launch AllSpark Web.command"
"""


def _web_launcher() -> str:
    return """#!/bin/sh
set -eu
BASE="$HOME/Applications/AllSpark"
BIN="$BASE/current/AllSpark"
if [ ! -x "$BIN" ]; then
  printf 'AllSpark is not installed. Run Install AllSpark.command first.\n' >&2
  exit 1
fi
"$BIN" --web --host 127.0.0.1 --port 8000 &
PID=$!
trap 'kill "$PID" 2>/dev/null || true' INT TERM EXIT
sleep 2
open http://127.0.0.1:8000/
wait "$PID"
"""


def _cli_launcher() -> str:
    return """#!/bin/sh
set -eu
BIN="$HOME/Applications/AllSpark/current/AllSpark"
if [ ! -x "$BIN" ]; then
  printf 'AllSpark is not installed. Run Install AllSpark.command first.\n' >&2
  exit 1
fi
exec "$BIN" "$@"
"""


def _rollback_script() -> str:
    return """#!/bin/sh
set -eu
replace_link() {
  TARGET=$1
  LINK=$2
  rm -f "$LINK.next"
  ln -s "$TARGET" "$LINK.next"
  if mv -f -T "$LINK.next" "$LINK" 2>/dev/null; then return 0; fi
  mv -f -h "$LINK.next" "$LINK"
}
BASE="$HOME/Applications/AllSpark"
if [ ! -L "$BASE/previous" ]; then
  printf 'No previous AllSpark installation is available.\n' >&2
  exit 1
fi
CURRENT=$(readlink "$BASE/current")
PREVIOUS=$(readlink "$BASE/previous")
if [ ! -x "$PREVIOUS/AllSpark" ]; then
  printf 'The previous installation is incomplete; current was not changed.\n' >&2
  exit 1
fi
replace_link "$PREVIOUS" "$BASE/current"
replace_link "$CURRENT" "$BASE/previous"
printf 'Rolled back to %s\n' "$PREVIOUS"
"""


def _model_installer_script() -> str:
    return """#!/bin/sh
set -eu
MODEL=${1:-}
if [ -z "$MODEL" ]; then
  printf 'Drag a .gguf file onto this command, or enter its full path:\n'
  IFS= read -r MODEL
fi
SUM_FILE="$MODEL.sha256"
META_FILE="$MODEL.metadata.json"
if [ ! -f "$MODEL" ] || [ ! -f "$SUM_FILE" ] || [ ! -f "$META_FILE" ]; then
  printf 'The model, .sha256 file, and .metadata.json file must be together.\n' >&2
  exit 1
fi
EXPECTED=$(awk 'NR==1 {print $1}' "$SUM_FILE")
ACTUAL=$(shasum -a 256 "$MODEL" | awk '{print $1}')
if [ "$EXPECTED" != "$ACTUAL" ]; then
  printf 'Model checksum mismatch; nothing was installed.\n' >&2
  exit 1
fi
DEST="$HOME/.allspark/models"
mkdir -p "$DEST"
chmod 700 "$HOME/.allspark" "$DEST" 2>/dev/null || true
cp "$MODEL" "$SUM_FILE" "$META_FILE" "$DEST/"
chmod 600 "$DEST/$(basename "$MODEL")" "$DEST/$(basename "$SUM_FILE")" "$DEST/$(basename "$META_FILE")"
printf 'Verified and installed %s. Optional model support remains Experimental.\n' "$(basename "$MODEL")"
"""


def _readme_text(version: str, target: str, signed: bool, artifact_id: str) -> str:
    signature = "Developer ID signed" if signed else "unsigned internal RC"
    return f"""AllSpark {version} offline delivery bundle

Target: {target}
Artifact ID: {artifact_id}
Signature status: {signature}

1. Disconnect the target Mac from the network if validating the offline path.
2. Open Verify AllSpark.command, then Install AllSpark.command.
3. Open ~/Applications/AllSpark/Launch AllSpark Web.command.
4. Complete the minimum assessment and confirm the first 24-hour plan.

The deterministic supported loop and core knowledge are included. No model is
required. Optional GGUF models remain Experimental and must be accompanied by
matching .sha256 and .metadata.json files before using Install Optional Model.

Runtime data stays under ~/.allspark and is not removed by upgrade or rollback.
Roll Back AllSpark.command only switches the installed application version.
This bundle does not claim application-layer encryption.
"""


def _manifest_entries(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in _iter_files(root):
        relative = path.relative_to(root).as_posix()
        entries.append(
            {
                "path": relative,
                "sha256": _sha256(path),
                "size": path.stat().st_size,
                "mode": oct(stat.S_IMODE(path.stat().st_mode)),
            }
        )
    return entries


def _write_checksums(bundle_root: Path, entries: list[dict[str, Any]], epoch: int) -> None:
    lines = [f"{entry['sha256']}  {entry['path']}" for entry in entries]
    (bundle_root / CHECKSUM_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    os.utime(bundle_root / CHECKSUM_NAME, (epoch, epoch))


def _write_deterministic_tar(source: Path, destination: Path, epoch: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                paths = [source, *sorted(source.rglob("*"), key=lambda p: p.as_posix())]
                for path in paths:
                    arcname = path.relative_to(source.parent).as_posix()
                    info = archive.gettarinfo(str(path), arcname)
                    info.uid = 0
                    info.gid = 0
                    info.uname = "root"
                    info.gname = "root"
                    info.mtime = epoch
                    if path.is_file():
                        with path.open("rb") as handle:
                            archive.addfile(info, handle)
                    else:
                        archive.addfile(info)


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    """Extract an archive after rejecting traversal and special-file entries."""
    root = destination.resolve()
    for member in archive.getmembers():
        member_path = Path(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise ValueError(f"unsafe archive path: {member.name}")
        resolved = (root / member_path).resolve(strict=False)
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"archive path escapes destination: {member.name}")
        if member.isdev() or member.isfifo():
            raise ValueError(f"unsupported special file in archive: {member.name}")
        if member.issym() or member.islnk():
            link = Path(member.linkname)
            if link.is_absolute():
                raise ValueError(f"unsafe archive link: {member.name}")
            base = member_path.parent if member.issym() else Path()
            link_target = (root / base / link).resolve(strict=False)
            if link_target != root and root not in link_target.parents:
                raise ValueError(f"archive link escapes destination: {member.name}")
    archive.extractall(destination)


def assemble_bundle(
    payload: Path,
    output_dir: Path,
    *,
    version: str,
    target: str,
    source_commit: str,
    signed: bool,
    source_dirty: bool = False,
    epoch: int = DEFAULT_EPOCH,
) -> tuple[Path, Path]:
    executable = payload / "AllSpark"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("payload must contain an executable named AllSpark")

    artifact_seed = f"{version}:{target}:{source_commit}:{_sha256(executable)}"
    artifact_id = hashlib.sha256(artifact_seed.encode("utf-8")).hexdigest()[:12]
    bundle_name = f"AllSpark-{version}-{target}-{artifact_id}"
    bundle_root = output_dir / bundle_name
    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    (bundle_root / "payload").mkdir(parents=True)
    shutil.copytree(payload, bundle_root / "payload" / "AllSpark", symlinks=True)

    _write_executable(bundle_root / "Install AllSpark.command", _installer_script(version, artifact_id), epoch)
    _write_executable(bundle_root / "Verify AllSpark.command", f"#!/bin/sh\nset -eu\ncd \"$(dirname \"$0\")\"\nshasum -a 256 -c {CHECKSUM_NAME}\n", epoch)
    _write_executable(bundle_root / "Launch AllSpark Web.command", _web_launcher(), epoch)
    _write_executable(bundle_root / "Launch AllSpark CLI.command", _cli_launcher(), epoch)
    _write_executable(bundle_root / "Roll Back AllSpark.command", _rollback_script(), epoch)
    _write_executable(bundle_root / "Install Optional Model.command", _model_installer_script(), epoch)
    (bundle_root / "README.txt").write_text(
        _readme_text(version, target, signed, artifact_id), encoding="utf-8", newline="\n"
    )
    _normalize_tree(bundle_root, epoch)

    checksum_entries = _manifest_entries(bundle_root / "payload")
    for entry in checksum_entries:
        entry["path"] = f"payload/{entry['path']}"
    checksum_entries.extend(
        {
            "path": path.relative_to(bundle_root).as_posix(),
            "sha256": _sha256(path),
            "size": path.stat().st_size,
            "mode": oct(stat.S_IMODE(path.stat().st_mode)),
        }
        for path in _iter_files(bundle_root)
        if path.parent == bundle_root and path.name not in {MANIFEST_NAME, CHECKSUM_NAME}
    )
    checksum_entries.sort(key=lambda item: item["path"])
    _write_checksums(bundle_root, checksum_entries, epoch)

    manifest = {
        "schema_version": 1,
        "product": "AllSpark",
        "version": version,
        "release_channel": "release-candidate",
        "target": target,
        "source_commit": source_commit,
        "source_dirty": source_dirty,
        "artifact_id": artifact_id,
        "signature": "developer-id" if signed else "unsigned-internal-rc",
        "model_required": False,
        "core_knowledge_included": True,
        "files": checksum_entries,
    }
    manifest_path = bundle_root / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.utime(manifest_path, (epoch, epoch))

    archive_path = output_dir / f"{bundle_name}.tar.gz"
    _write_deterministic_tar(bundle_root, archive_path, epoch)
    return bundle_root, archive_path


def _freeze_payload(work_dir: Path, sign_identity: str | None, epoch: int) -> Path:
    dist_dir = work_dir / "dist"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "AllSpark",
        "--osx-bundle-identifier",
        "io.github.sinbadhan.allspark",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir / "build"),
        "--specpath",
        str(work_dir / "spec"),
        "--collect-all",
        "allspark",
        "--collect-submodules",
        "allspark.commands",
    ]
    if sign_identity:
        command.extend(["--codesign-identity", sign_identity])
    command.append(str(ROOT / "packaging" / "pyinstaller" / "entrypoint.py"))
    env = {
        **os.environ,
        "PYTHONHASHSEED": "0",
        "SOURCE_DATE_EPOCH": str(epoch),
    }
    subprocess.run(command, cwd=ROOT, check=True, env=env)
    payload = dist_dir / "AllSpark"
    _resign_main_executable(payload, sign_identity)
    return payload


def _build_release_dmg(
    bundle_root: Path,
    output_dir: Path,
    *,
    version: str,
    sign_identity: str,
    notary_profile: str,
) -> Path:
    """Create the Apple-supported notarization container and staple its ticket."""
    dmg = output_dir / f"{bundle_root.name}.dmg"
    subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            f"AllSpark {version}",
            "-srcfolder",
            str(bundle_root),
            "-ov",
            "-format",
            "UDZO",
            str(dmg),
        ],
        check=True,
    )
    subprocess.run(
        ["codesign", "--force", "--timestamp", "--sign", sign_identity, str(dmg)],
        check=True,
    )
    subprocess.run(["codesign", "--verify", "--verbose=2", str(dmg)], check=True)
    subprocess.run(
        ["xcrun", "notarytool", "submit", str(dmg), "--keychain-profile", notary_profile, "--wait"],
        check=True,
    )
    subprocess.run(["xcrun", "stapler", "staple", str(dmg)], check=True)
    subprocess.run(["xcrun", "stapler", "validate", str(dmg)], check=True)
    subprocess.run(
        ["spctl", "--assess", "--type", "open", "--context", "context:primary-signature", "--verbose=4", str(dmg)],
        check=True,
    )
    return dmg


def build(args: argparse.Namespace) -> tuple[Path, Path, Path | None]:
    if sys.platform != "darwin":
        raise RuntimeError("the current delivery target must be built on macOS")
    if args.release and (not args.sign_identity or not args.notary_profile):
        raise RuntimeError("--release requires --sign-identity and --notary-profile")
    source_dirty = _source_is_dirty()
    if args.release and source_dirty:
        raise RuntimeError("--release requires a clean Git worktree")

    version = _project_version()
    target = _target_name()
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = ROOT / "build" / "offline-delivery"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    try:
        payload = _freeze_payload(work_dir, args.sign_identity, args.epoch)
        bundle_root, archive = assemble_bundle(
            payload,
            output_dir,
            version=version,
            target=target,
            source_commit=_source_commit(),
            signed=bool(args.sign_identity),
            source_dirty=source_dirty,
            epoch=args.epoch,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    verify_archive(archive)
    release_dmg = None
    if args.release:
        release_dmg = _build_release_dmg(
            bundle_root,
            output_dir,
            version=version,
            sign_identity=args.sign_identity,
            notary_profile=args.notary_profile,
        )
    return bundle_root, archive, release_dmg


def verify_archive(archive: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="allspark-verify-") as temp:
        destination = Path(temp)
        with tarfile.open(archive, "r:gz") as handle:
            _safe_extract(handle, destination)
        roots = [path for path in destination.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise ValueError("archive must contain exactly one root directory")
        root = roots[0]
        manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
        expected = {entry["path"]: entry for entry in manifest["files"]}
        for relative, entry in expected.items():
            path = root / relative
            if not path.is_file():
                raise ValueError(f"missing delivery file: {relative}")
            if path.stat().st_size != entry["size"] or _sha256(path) != entry["sha256"]:
                raise ValueError(f"delivery file failed integrity check: {relative}")
        return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build", help="freeze and assemble the current macOS target")
    build_parser.add_argument("--output", type=Path, default=ROOT / "dist" / "offline")
    build_parser.add_argument("--sign-identity", help="Apple Developer ID Application identity")
    build_parser.add_argument("--notary-profile", help="xcrun notarytool keychain profile")
    build_parser.add_argument("--release", action="store_true", help="require signing and notarization")
    build_parser.add_argument("--epoch", type=int, default=int(os.environ.get("SOURCE_DATE_EPOCH", DEFAULT_EPOCH)))
    verify_parser = subparsers.add_parser("verify", help="verify an existing delivery archive")
    verify_parser.add_argument("archive", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "build":
        bundle, archive, release_dmg = build(args)
        print(f"bundle={bundle}")
        print(f"archive={archive}")
        print(f"sha256={_sha256(archive)}")
        if release_dmg is not None:
            print(f"release_dmg={release_dmg}")
            print(f"release_dmg_sha256={_sha256(release_dmg)}")
        return 0
    manifest = verify_archive(args.archive.resolve())
    print(json.dumps({key: manifest[key] for key in ("version", "target", "artifact_id", "signature")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
