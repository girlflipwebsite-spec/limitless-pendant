import pytest

from pendant import config


def test_get_pendant_address_raises_when_nothing_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "PENDANT_ADDRESS_FILE", tmp_path / "pendant_address.txt")
    monkeypatch.delenv("PENDANT_ADDRESS", raising=False)

    with pytest.raises(RuntimeError):
        config.get_pendant_address()


def test_scan_saves_address_and_get_reads_it_back(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "PENDANT_ADDRESS_FILE", tmp_path / "pendant_address.txt")
    monkeypatch.delenv("PENDANT_ADDRESS", raising=False)

    config.save_pendant_address("AA:BB:CC:DD:EE:FF")

    assert config.get_pendant_address() == "AA:BB:CC:DD:EE:FF"


def test_env_var_overrides_saved_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "PENDANT_ADDRESS_FILE", tmp_path / "pendant_address.txt")

    config.save_pendant_address("from-file")
    monkeypatch.setenv("PENDANT_ADDRESS", "from-env")

    assert config.get_pendant_address() == "from-env"
