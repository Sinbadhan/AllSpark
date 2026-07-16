from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build_offline_bundle.py"
    spec = importlib.util.spec_from_file_location("offline_bundle", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(tmp_path: Path) -> Path:
    payload = tmp_path / "payload"
    (payload / "_internal" / "allspark" / "data" / "knowledge").mkdir(parents=True)
    executable = payload / "AllSpark"
    executable.write_text("#!/bin/sh\necho AllSpark 1.0.3\n", encoding="utf-8")
    executable.chmod(0o755)
    (payload / "_internal" / "allspark" / "data" / "knowledge" / "tier0_en.yaml").write_text(
        "entries: []\n", encoding="utf-8"
    )
    return payload


def test_bundle_is_deterministic_and_self_describing(tmp_path: Path) -> None:
    module = _module()
    payload = _payload(tmp_path)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()

    _, first_archive = module.assemble_bundle(
        payload,
        first_dir,
        version="1.0.3",
        target="macos-arm64",
        source_commit="a" * 40,
        signed=False,
    )
    _, second_archive = module.assemble_bundle(
        payload,
        second_dir,
        version="1.0.3",
        target="macos-arm64",
        source_commit="a" * 40,
        signed=False,
    )

    assert module._sha256(first_archive) == module._sha256(second_archive)
    manifest = module.verify_archive(first_archive)
    assert manifest["release_channel"] == "release-candidate"
    assert manifest["source_dirty"] is False
    assert manifest["signature"] == "unsigned-internal-rc"
    assert manifest["model_required"] is False
    assert manifest["core_knowledge_included"] is True
    assert any(item["path"].endswith("tier0_en.yaml") for item in manifest["files"])


def test_verify_rejects_payload_tampering(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "out"
    output.mkdir()
    bundle, _ = module.assemble_bundle(
        _payload(tmp_path),
        output,
        version="1.0.3",
        target="macos-arm64",
        source_commit="b" * 40,
        signed=True,
    )
    manifest = json.loads((bundle / module.MANIFEST_NAME).read_text(encoding="utf-8"))
    executable = bundle / "payload" / "AllSpark" / "AllSpark"
    executable.write_text("tampered", encoding="utf-8")
    archive = output / "tampered.tar.gz"
    module._write_deterministic_tar(bundle, archive, module.DEFAULT_EPOCH)

    with pytest.raises(ValueError, match="integrity check"):
        module.verify_archive(archive)
    assert manifest["signature"] == "developer-id"


def test_install_and_rollback_scripts_are_fail_closed(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "out"
    output.mkdir()
    bundle, _ = module.assemble_bundle(
        _payload(tmp_path),
        output,
        version="1.0.3",
        target="macos-arm64",
        source_commit="c" * 40,
        signed=False,
    )

    install = (bundle / "Install AllSpark.command").read_text(encoding="utf-8")
    rollback = (bundle / "Roll Back AllSpark.command").read_text(encoding="utf-8")
    model = (bundle / "Install Optional Model.command").read_text(encoding="utf-8")
    assert "shasum -a 256 -c SHA256SUMS" in install
    assert "replace_link \"$DEST\" \"$BASE/current\"" in install
    assert "replace_link \"$CURRENT\" \"$BASE/previous\"" in install
    assert "current was not changed" in rollback
    assert ".sha256" in model and ".metadata.json" in model
    assert "checksum mismatch; nothing was installed" in model
    for name in (
        "Install AllSpark.command",
        "Verify AllSpark.command",
        "Launch AllSpark Web.command",
        "Roll Back AllSpark.command",
    ):
        assert os.access(bundle / name, os.X_OK)


def test_safe_extract_rejects_traversal(tmp_path: Path) -> None:
    module = _module()
    archive_path = tmp_path / "escape.tar"
    with tarfile.open(archive_path, "w") as archive:
        info = tarfile.TarInfo("../escape")
        content = b"bad"
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))

    with tarfile.open(archive_path) as archive:
        with pytest.raises(ValueError, match="unsafe archive path"):
            module._safe_extract(archive, tmp_path / "extract")
    assert not (tmp_path / "escape").exists()


@pytest.mark.skipif(not shutil.which("shasum"), reason="macOS delivery verifier requires shasum")
def test_install_upgrade_and_rollback_are_atomic(tmp_path: Path) -> None:
    module = _module()
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home)}

    first_output = tmp_path / "first-output"
    second_output = tmp_path / "second-output"
    first_output.mkdir()
    second_output.mkdir()
    first, _ = module.assemble_bundle(
        _payload(tmp_path / "first-input"),
        first_output,
        version="1.0.3",
        target="macos-arm64",
        source_commit="d" * 40,
        signed=False,
    )
    second_payload = _payload(tmp_path / "second-input")
    (second_payload / "AllSpark").write_text("#!/bin/sh\necho second\n", encoding="utf-8")
    (second_payload / "AllSpark").chmod(0o755)
    second, _ = module.assemble_bundle(
        second_payload,
        second_output,
        version="1.0.3",
        target="macos-arm64",
        source_commit="e" * 40,
        signed=False,
    )

    subprocess.run(["/bin/sh", str(first / "Install AllSpark.command")], env=env, check=True, capture_output=True)
    base = home / "Applications" / "AllSpark"
    first_target = (base / "current").resolve()
    data = home / ".allspark" / "data.db"
    data.parent.mkdir(mode=0o700)
    data.write_text("preserve", encoding="utf-8")

    subprocess.run(["/bin/sh", str(second / "Install AllSpark.command")], env=env, check=True, capture_output=True)
    second_target = (base / "current").resolve()
    assert second_target != first_target
    assert (base / "previous").resolve() == first_target

    subprocess.run(["/bin/sh", str(base / "Roll Back AllSpark.command")], env=env, check=True, capture_output=True)
    assert (base / "current").resolve() == first_target
    assert (base / "previous").resolve() == second_target
    assert data.read_text(encoding="utf-8") == "preserve"


@pytest.mark.skipif(not shutil.which("shasum"), reason="macOS delivery verifier requires shasum")
def test_tampered_bundle_installs_nothing(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "output"
    output.mkdir()
    bundle, _ = module.assemble_bundle(
        _payload(tmp_path / "input"),
        output,
        version="1.0.3",
        target="macos-arm64",
        source_commit="f" * 40,
        signed=False,
    )
    (bundle / "payload" / "AllSpark" / "AllSpark").write_text("tampered", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        ["/bin/sh", str(bundle / "Install AllSpark.command")],
        env={**os.environ, "HOME": str(home)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not (home / "Applications" / "AllSpark" / "current").exists()


def test_release_dmg_uses_apple_supported_notarization_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        if command[0] == "hdiutil":
            Path(command[-1]).write_bytes(b"dmg")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    dmg = module._build_release_dmg(
        bundle,
        tmp_path,
        version="1.0.3",
        sign_identity="Developer ID Application: Example",
        notary_profile="test-profile",
    )

    assert dmg.suffix == ".dmg"
    notary = next(command for command in calls if command[:3] == ["xcrun", "notarytool", "submit"])
    assert notary[3].endswith(".dmg")
    assert any(command[:3] == ["xcrun", "stapler", "staple"] for command in calls)
    assert any(command[:3] == ["xcrun", "stapler", "validate"] for command in calls)
    assert any(command[:4] == ["spctl", "--assess", "--type", "open"] for command in calls)


def test_freezer_uses_stable_macos_signing_identifier() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts" / "build_offline_bundle.py").read_text(
        encoding="utf-8"
    )
    assert '"--osx-bundle-identifier"' in source
    assert '"io.github.sinbadhan.allspark"' in source
