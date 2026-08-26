from pathlib import Path

import pytest

from sportstaxer.config import Config, ConfigError, find_config, load_config


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "sportstaxer.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.fps == 2.0
    assert config.dedup.enabled is True


def test_partial_override_keeps_other_defaults(tmp_path):
    path = write(tmp_path, "fps: 4\ndedup:\n  hash_distance: 8\n")
    config = load_config(path)
    assert config.fps == 4
    assert config.dedup.hash_distance == 8
    assert config.dedup.enabled is True
    assert config.stitch.min_correlation == 0.9


def test_relative_paths_resolve_against_config_file(tmp_path):
    path = write(tmp_path, "work_dir: artifacts\n")
    config = load_config(path)
    assert config.work_dir == tmp_path / "artifacts"


def test_unknown_key_is_an_error(tmp_path):
    path = write(tmp_path, "fpz: 4\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_out_of_range_value_is_an_error(tmp_path):
    path = write(tmp_path, "stitch:\n  min_correlation: 1.5\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_missing_explicit_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_find_config_searches_upwards(tmp_path):
    path = write(tmp_path, "fps: 1\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_config(nested) == path


def test_stage_dir(tmp_path):
    config = Config(work_dir=tmp_path)
    assert config.stage_dir("run1", "frames") == tmp_path / "run1" / "frames"


def test_example_config_is_valid():
    load_config(Path("sportstaxer.example.yaml"))
