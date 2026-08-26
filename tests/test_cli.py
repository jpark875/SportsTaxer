import json

import pytest

from sportstaxer.cli import main


def test_config_command_prints_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["config"]) == 0
    assert json.loads(capsys.readouterr().out)["fps"] == 2.0


def test_bad_config_exits_nonzero(tmp_path, capsys):
    path = tmp_path / "bad.yaml"
    path.write_text("fps: -1\n", encoding="utf-8")
    assert main(["--config", str(path), "config"]) == 2
    assert "error:" in capsys.readouterr().err


def test_no_subcommand_is_usage_error():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
