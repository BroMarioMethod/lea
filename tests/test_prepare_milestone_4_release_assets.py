"""Tests for secure Milestone 4 release-asset materialization."""

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _module() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts/prepare_milestone_4_release_assets.py"
    spec = importlib.util.spec_from_file_location("prepare_m4_assets", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_creates_exact_asset_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    monkeypatch.setattr(module.os, "chown", lambda *_args, **_kwargs: None)
    source = tmp_path / "source"
    source.write_bytes(b"reviewed")
    digest = hashlib.sha256(b"reviewed").hexdigest()
    destination = tmp_path / "asset"

    module._install(source, destination, digest)
    module._install(source, destination, digest)

    assert destination.read_bytes() == b"reviewed"
    assert destination.stat().st_mode & 0o777 == 0o644


def test_install_rejects_digest_mismatch_before_destination(tmp_path: Path) -> None:
    module = _module()
    source = tmp_path / "source"
    source.write_bytes(b"unreviewed")
    destination = tmp_path / "asset"

    with pytest.raises(ValueError, match="digest mismatch"):
        module._install(source, destination, "0" * 64)

    assert not destination.exists()


def test_install_rejects_symbolic_source(tmp_path: Path) -> None:
    module = _module()
    target = tmp_path / "target"
    target.write_bytes(b"reviewed")
    source = tmp_path / "source"
    source.symlink_to(target)

    with pytest.raises(ValueError, match="non-symbolic"):
        module._install(
            source,
            tmp_path / "asset",
            hashlib.sha256(b"reviewed").hexdigest(),
        )
