import json
from pathlib import Path

import pytest
from PIL import Image

from sportstaxer.adapters import load_adapter
from sportstaxer.config import Config
from sportstaxer.extract import (
    ExtractionError,
    ModelField,
    ModelResponse,
    ModelRow,
    ReplayBackend,
    Tile,
    build_prompt,
    extract_canvas,
    load_extraction,
    plan_tiles,
)
from sportstaxer.stitch import stitch
from sportstaxer.synthetic import make_capture

ADAPTER = load_adapter("synthbook", Path("adapters"))


def row(y_top: int, y_bottom: int, stake="$10.00", payout="$25.00", date="2025-03-04") -> ModelRow:
    def field(value, confidence=0.95):
        return ModelField(value=value, confidence=confidence)

    return ModelRow(
        date=field(date),
        description=field(f"Lakers v Heat #{y_top}"),
        bet_type=field("Moneyline"),
        stake=field(stake),
        payout=field(payout),
        result=field("Won"),
        balance=ModelField(value=None, confidence=0.0),
        y_top=y_top,
        y_bottom=y_bottom,
    )


class FakeBackend:
    """Returns scripted responses keyed by tile, optionally differing per pass."""

    def __init__(self, per_tile: dict[tuple[int, int], list[ModelResponse]]):
        self.name = "fake"
        self.per_tile = per_tile
        self.calls: list[tuple[int, int]] = []

    def read_tile(self, tile: Tile, image: Image.Image, adapter) -> ModelResponse:
        key = (tile.segment, tile.index)
        responses = self.per_tile[key]
        seen = self.calls.count(key)
        self.calls.append(key)
        return responses[min(seen, len(responses) - 1)]


@pytest.fixture
def canvas(tmp_path):
    capture = make_capture(row_count=20, frame_height=640, step=300)
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    paths = []
    for i, frame in enumerate(capture.frames):
        path = frames_dir / f"frame_{i:04d}.png"
        frame.save(path)
        paths.append(path)
    manifest = stitch(paths, tmp_path / "canvas", Config())
    return manifest, tmp_path / "canvas"


def test_tiles_cover_the_canvas_with_overlap(canvas):
    manifest, canvas_dir = canvas
    config = Config(extract={"tile_height": 600, "tile_overlap": 150})

    tiles = plan_tiles(manifest, canvas_dir, config)

    assert tiles[0].y_offset == 0
    assert len(tiles) > 1
    for a, b in zip(tiles, tiles[1:], strict=False):
        assert b.y_offset - a.y_offset == 450
    last = tiles[-1]
    assert last.y_offset + Image.open(last.image_path).height >= manifest.height
    for tile in tiles:
        assert Image.open(tile.image_path).height <= 600


def test_rows_are_placed_in_canvas_coordinates(canvas):
    manifest, canvas_dir = canvas
    config = Config(extract={"tile_height": 600, "tile_overlap": 150, "money_passes": 1})
    tiles = plan_tiles(manifest, canvas_dir, config)
    backend = FakeBackend({(t.segment, t.index): [ModelResponse(rows=[])] for t in tiles})
    backend.per_tile[(0, 1)] = [ModelResponse(rows=[row(100, 190)])]

    result = extract_canvas(manifest, canvas_dir, ADAPTER, config, backend)

    assert len(result.rows) == 1
    assert result.rows[0].bbox.y == 450 + 100
    assert result.rows[0].bbox.height == 90
    assert result.rows[0].bbox.width == manifest.width


def test_same_row_read_in_two_tiles_is_not_duplicated(canvas):
    manifest, canvas_dir = canvas
    config = Config(extract={"tile_height": 600, "tile_overlap": 150, "money_passes": 1})
    tiles = plan_tiles(manifest, canvas_dir, config)
    responses = {(t.segment, t.index): [ModelResponse(rows=[])] for t in tiles}
    # The same bet, sitting in the overlap: y 500-590 of tile 0 is y 50-140 of tile 1.
    responses[(0, 0)] = [ModelResponse(rows=[row(500, 590)])]
    responses[(0, 1)] = [ModelResponse(rows=[row(50, 140)])]

    result = extract_canvas(manifest, canvas_dir, ADAPTER, config, FakeBackend(responses))

    assert len(result.rows) == 1
    assert result.rows[0].flags == []


def test_money_disagreement_is_flagged_not_resolved(canvas):
    manifest, canvas_dir = canvas
    config = Config(extract={"tile_height": 600, "tile_overlap": 150, "money_passes": 2})
    tiles = plan_tiles(manifest, canvas_dir, config)
    responses = {(t.segment, t.index): [ModelResponse(rows=[])] for t in tiles}
    responses[(0, 0)] = [
        ModelResponse(rows=[row(100, 190, stake="$10.00")]),
        ModelResponse(rows=[row(100, 190, stake="$70.00")]),
    ]

    result = extract_canvas(manifest, canvas_dir, ADAPTER, config, FakeBackend(responses))

    assert len(result.rows) == 1
    kept = result.rows[0]
    assert kept.flags == ["money disagreement: stake $10.00 vs $70.00"]
    # The first reading is kept as-is with its confidence zeroed. Nothing is averaged and
    # no winner is picked.
    assert kept.stake.value == "$10.00"
    assert kept.stake.confidence == 0.0
    assert kept.payout.confidence == 0.95


def test_agreeing_passes_leave_no_flag(canvas):
    manifest, canvas_dir = canvas
    config = Config(extract={"tile_height": 600, "tile_overlap": 150, "money_passes": 2})
    tiles = plan_tiles(manifest, canvas_dir, config)
    responses = {(t.segment, t.index): [ModelResponse(rows=[])] for t in tiles}
    responses[(0, 0)] = [ModelResponse(rows=[row(100, 190)])] * 2

    result = extract_canvas(manifest, canvas_dir, ADAPTER, config, FakeBackend(responses))
    assert result.rows[0].flags == []
    assert result.rows[0].stake.confidence == 0.95


def test_row_seen_on_only_one_pass_is_flagged(canvas):
    manifest, canvas_dir = canvas
    config = Config(extract={"tile_height": 600, "tile_overlap": 150, "money_passes": 2})
    tiles = plan_tiles(manifest, canvas_dir, config)
    responses = {(t.segment, t.index): [ModelResponse(rows=[])] for t in tiles}
    responses[(0, 0)] = [ModelResponse(rows=[]), ModelResponse(rows=[row(100, 190)])]

    result = extract_canvas(manifest, canvas_dir, ADAPTER, config, FakeBackend(responses))
    assert result.rows[0].flags == ["row seen only on pass 2"]


def test_result_is_written_and_reloads(canvas):
    manifest, canvas_dir = canvas
    config = Config(extract={"tile_height": 600, "tile_overlap": 150, "money_passes": 1})
    tiles = plan_tiles(manifest, canvas_dir, config)
    responses = {(t.segment, t.index): [ModelResponse(rows=[])] for t in tiles}
    responses[(0, 0)] = [ModelResponse(rows=[row(100, 190)])]

    result = extract_canvas(manifest, canvas_dir, ADAPTER, config, FakeBackend(responses))
    assert load_extraction(canvas_dir) == result
    assert result.backend == "fake"


def test_rows_come_back_in_canvas_order(canvas):
    manifest, canvas_dir = canvas
    config = Config(extract={"tile_height": 600, "tile_overlap": 150, "money_passes": 1})
    tiles = plan_tiles(manifest, canvas_dir, config)
    responses = {(t.segment, t.index): [ModelResponse(rows=[])] for t in tiles}
    responses[(0, 2)] = [ModelResponse(rows=[row(10, 100)])]
    responses[(0, 0)] = [ModelResponse(rows=[row(10, 100)])]

    result = extract_canvas(manifest, canvas_dir, ADAPTER, config, FakeBackend(responses))
    assert [r.bbox.y for r in result.rows] == sorted(r.bbox.y for r in result.rows)


def test_replay_backend_reads_recorded_responses(canvas, tmp_path):
    manifest, canvas_dir = canvas
    config = Config(extract={"tile_height": 600, "tile_overlap": 150, "money_passes": 2})
    responses_dir = tmp_path / "responses"
    responses_dir.mkdir()
    for tile in plan_tiles(manifest, canvas_dir, config):
        payload = ModelResponse(rows=[row(10, 100)] if tile.index == 0 else [])
        (responses_dir / ReplayBackend.filename(tile)).write_text(
            payload.model_dump_json(), encoding="utf-8"
        )

    result = extract_canvas(manifest, canvas_dir, ADAPTER, config, ReplayBackend(responses_dir))
    assert len(result.rows) == 1
    assert result.rows[0].flags == []


def test_replay_backend_reports_a_missing_recording(canvas, tmp_path):
    manifest, canvas_dir = canvas
    config = Config(extract={"tile_height": 600, "tile_overlap": 150, "money_passes": 1})
    with pytest.raises(ExtractionError, match="no recorded response"):
        extract_canvas(manifest, canvas_dir, ADAPTER, config, ReplayBackend(tmp_path / "empty"))


def test_prompt_carries_the_book_terminology_and_layout():
    prompt = build_prompt(ADAPTER)
    assert "Synth Book" in prompt
    assert "risk" in prompt
    assert "Stake $x" in prompt
    assert "to win" in prompt


def test_tile_overlap_must_be_smaller_than_tile_height(canvas):
    manifest, canvas_dir = canvas
    config = Config(extract={"tile_height": 400, "tile_overlap": 400})
    with pytest.raises(ExtractionError, match="tile overlap"):
        plan_tiles(manifest, canvas_dir, config)


def test_anthropic_backend_sends_the_image_and_schema(canvas):
    from sportstaxer.extract import AnthropicBackend

    class Recorder:
        def __init__(self):
            self.messages = self
            self.kwargs = None

        def parse(self, **kwargs):
            self.kwargs = kwargs

            class Response:
                parsed_output = ModelResponse(rows=[row(0, 90)])
                stop_reason = "end_turn"

            return Response()

    recorder = Recorder()
    backend = AnthropicBackend("claude-opus-5", 16000, client=recorder)
    tile = Tile(segment=0, index=0, y_offset=0, image_path=Path("unused"))

    response = backend.read_tile(tile, Image.new("RGB", (720, 400), (20, 20, 20)), ADAPTER)

    assert len(response.rows) == 1
    content = recorder.kwargs["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"
    assert json.loads(json.dumps(recorder.kwargs["model"])) == "claude-opus-5"
    assert recorder.kwargs["output_format"] is ModelResponse
