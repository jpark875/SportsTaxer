from pathlib import Path

import pytest

from sportstaxer.adapters import AdapterError, list_adapters, load_adapter

ADAPTERS = Path("adapters")


def write(tmp_path: Path, name: str, text: str) -> Path:
    (tmp_path / f"{name}.yaml").write_text(text, encoding="utf-8")
    return tmp_path


MINIMAL = """
name: {name}
display_name: Test Book
payout_includes_stake: true
"""


def test_shipped_profiles_all_load():
    names = list_adapters(ADAPTERS)
    assert "synthbook" in names
    for name in names:
        load_adapter(name, ADAPTERS)


def test_synthbook_crop_matches_the_generator():
    adapter = load_adapter("synthbook", ADAPTERS)
    assert (adapter.crop.top, adapter.crop.bottom) == (60, 50)
    assert adapter.payout_includes_stake is False


def test_payout_convention_must_be_stated(tmp_path):
    write(tmp_path, "book", "name: book\ndisplay_name: Book\n")
    with pytest.raises(AdapterError, match="payout_includes_stake"):
        load_adapter("book", tmp_path)


def test_unknown_key_is_an_error(tmp_path):
    write(tmp_path, "book", MINIMAL.format(name="book") + "payout_include_stake: true\n")
    with pytest.raises(AdapterError, match="invalid adapter profile"):
        load_adapter("book", tmp_path)


def test_filename_and_declared_name_must_agree(tmp_path):
    write(tmp_path, "book", MINIMAL.format(name="other"))
    with pytest.raises(AdapterError, match="expected 'book'"):
        load_adapter("book", tmp_path)


def test_missing_profile_lists_what_is_available(tmp_path):
    write(tmp_path, "book", MINIMAL.format(name="book"))
    with pytest.raises(AdapterError, match="have: book"):
        load_adapter("nope", tmp_path)


def test_terminology_defaults_are_present(tmp_path):
    write(tmp_path, "book", MINIMAL.format(name="book"))
    adapter = load_adapter("book", tmp_path)
    assert "risk" in adapter.terminology.stake
    assert "cash out" in adapter.terminology.cashout
