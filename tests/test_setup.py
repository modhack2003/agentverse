import json
import os
from pathlib import Path

import pytest

from agentcommons.setup import apply_setup, home_path, prepare_setup, read_setup


def test_setup_is_private_and_idempotent(tmp_path):
    home = tmp_path / "workspace with spaces"
    first = prepare_setup(home, 8123)
    database = home / first["database"]
    database.write_bytes(b"existing-workspace")
    assert len(first["admin_token"]) >= 32
    assert prepare_setup(home) == first
    changed = prepare_setup(home, 8124)
    assert changed["admin_token"] == first["admin_token"]
    assert changed["port"] == 8124
    assert database.read_bytes() == b"existing-workspace"
    if os.name != "nt":
        assert (home.stat().st_mode & 0o777) == 0o700
        assert ((home / "config.json").stat().st_mode & 0o777) == 0o600


@pytest.mark.parametrize("port", [0, -1, 65536, True, "8000"])
def test_invalid_port_does_not_create_setup(tmp_path, port):
    home = tmp_path / "new-install"
    with pytest.raises(ValueError, match="Port"):
        prepare_setup(home, port)
    assert not home.exists()


@pytest.mark.parametrize("content", ["{broken", "[]", json.dumps({"version": 99})])
def test_invalid_existing_config_is_never_overwritten(tmp_path, content):
    path = tmp_path / "config.json"
    path.write_text(content)
    with pytest.raises(ValueError, match="not been overwritten"):
        prepare_setup(tmp_path)
    assert path.read_text() == content


def test_setup_rejects_credentials_symlink(tmp_path):
    original = tmp_path / "original.json"
    original.write_text("do-not-touch")
    (tmp_path / "config.json").symlink_to(original)
    with pytest.raises(ValueError, match="symlink"):
        prepare_setup(tmp_path)
    assert original.read_text() == "do-not-touch"


def test_explicit_home_and_existing_deployment_environment(monkeypatch, tmp_path):
    data = prepare_setup(tmp_path)
    monkeypatch.setenv("AGENTCOMMONS_ADMIN_TOKEN", "existing-deployment-secret-long-enough")
    monkeypatch.delenv("AGENTVERSE_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("AGENTVERSE_DB", raising=False)
    monkeypatch.delenv("AGENTCOMMONS_DB", raising=False)
    apply_setup(tmp_path, data)
    assert "AGENTVERSE_ADMIN_TOKEN" not in os.environ
    assert os.environ["AGENTVERSE_DB"] == str(tmp_path / "data/agentverse.db")
    apply_setup(tmp_path, data, override=True)
    assert os.environ["AGENTVERSE_ADMIN_TOKEN"] == data["admin_token"]
    assert read_setup(tmp_path) == data
    assert home_path(str(tmp_path)) == Path(tmp_path).resolve()
