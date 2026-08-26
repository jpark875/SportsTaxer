import json
import shutil
from pathlib import Path

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


def test_frames_command_reports_counts(scroll_video, tmp_path, monkeypatch, capsys):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    (tmp_path / "sportstaxer.yaml").write_text("work_dir: work\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main(["frames", str(scroll_video), "--run-id", "r1"]) == 0
    assert "frames kept" in capsys.readouterr().out
    assert (tmp_path / "work" / "r1" / "frames" / "manifest.json").is_file()


def test_frames_command_reports_missing_video(tmp_path, capsys):
    assert main(["frames", str(tmp_path / "nope.mp4")]) == 1
    assert "video not found" in capsys.readouterr().err


def test_frames_then_stitch_end_to_end(scroll_video, tmp_path, monkeypatch, capsys):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    adapters = Path("adapters").resolve().as_posix()
    (tmp_path / "sportstaxer.yaml").write_text(
        f"work_dir: work\nadapters_dir: {adapters}\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    assert main(["frames", str(scroll_video), "--run-id", "r1"]) == 0
    assert main(["stitch", "r1", "--book", "synthbook"]) == 0

    out = capsys.readouterr().out
    assert "canvas 720x" in out
    canvas_dir = tmp_path / "work" / "r1" / "canvas"
    assert (canvas_dir / "canvas.json").is_file()
    assert list(canvas_dir.glob("canvas_*.png"))


def test_stitch_reports_an_unknown_book(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["stitch", "r1", "--book", "nosuchbook"]) == 1
    assert "no adapter profile" in capsys.readouterr().err
