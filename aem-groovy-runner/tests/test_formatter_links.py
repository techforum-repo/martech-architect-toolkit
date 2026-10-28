from __future__ import annotations

import json

import pytest

from groovy_runner import formatter_links as fl
from groovy_runner.scripts_registry import discover


def test_load_normalizes_default_first_and_short_form(tmp_path):
    path = tmp_path / "links.json"
    path.write_text(json.dumps({
        "a": {"formatters": ["generic-excel", "asset-reference-excel"], "default": "asset-reference-excel"},
        "b": ["generic-excel"],                      # short form
        "c": {"formatters": []},                     # nothing usable -> dropped
    }))
    assert fl.load(path) == {"a": (["asset-reference-excel", "generic-excel"], "asset-reference-excel"),
                             "b": (["generic-excel"], "generic-excel")}


def test_link_for_and_reverse_lookup():
    links = {"a": (["asset-reference-excel", "generic-excel"], "asset-reference-excel")}
    assert fl.link_for("a", links).linked and fl.link_for("a", links).default == "asset-reference-excel"
    unlinked = fl.link_for("zzz", links)
    assert not unlinked.linked and unlinked.formatters == ("generic-excel",)
    assert fl.scripts_linked_to("generic-excel", links) == ["a"]
    assert fl.link_for("x", {"x": (["nope"], "nope")}).unknown == ["nope"]


def test_save_round_trip_is_sorted_and_atomic(tmp_path):
    path = tmp_path / "links.json"
    links = {"z": (["generic-excel"], "generic-excel"), "a": (["asset-reference-excel"], "asset-reference-excel")}
    fl.save(links, path)
    assert list(json.loads(path.read_text())) == ["a", "z"]
    assert fl.load(path) == links
    assert [p.name for p in tmp_path.iterdir()] == ["links.json"]  # no temp files left behind


def test_invalid_file_raises_clear_error(tmp_path):
    path = tmp_path / "links.json"
    path.write_text("{oops")
    with pytest.raises(ValueError, match="not valid JSON"):
        fl.load(path)


def test_migration_runs_once_and_later_sources_win(tmp_path):
    path = tmp_path / "links.json"
    legacy = [("a", ["asset-reference-excel", "generic-excel"]), ("b", []), ("a", ["generic-excel"])]
    assert fl.migrate_if_missing(legacy, path) is True
    assert fl.load(path) == {"a": (["generic-excel"], "generic-excel")}
    assert fl.migrate_if_missing([("b", ["generic-excel"])], path) is False  # never overwrites


def test_shipped_links_cover_bundled_scripts():
    links = fl.load(fl.DEFAULTS_PATH)
    for script in discover():
        link = fl.link_for(script.id, links)
        assert link.linked and not link.unknown, script.id
    assert links["asset-reference-report"][1] == "asset-reference-excel"


def test_from_grid_rules():
    existing = {"gone": (["generic-excel"], "generic-excel"), "a": (["generic-excel"], "generic-excel")}
    rows = [
        {"script_id": "a", "default": "asset-reference-excel", "ticked": ["generic-excel"]},  # default not ticked -> added
        {"script_id": "b", "default": None, "ticked": ["generic-excel", "asset-reference-excel"]},  # first ticked = default
        {"script_id": "c", "default": None, "ticked": []},  # nothing -> unlinked
    ]
    links = fl.from_grid(rows, existing, {"a", "b", "c"})
    assert links == {
        "gone": (["generic-excel"], "generic-excel"),  # script not in scripts/ right now: kept
        "a": (["asset-reference-excel", "generic-excel"], "asset-reference-excel"),
        "b": (["generic-excel", "asset-reference-excel"], "generic-excel"),
    }


def test_redirected_links_path_is_honoured(tmp_path, monkeypatch):
    """Regression: defaults used to be bound at import, so redirecting
    LINKS_PATH still wrote the project's real file."""
    target = tmp_path / "links.json"
    monkeypatch.setattr(fl, "LINKS_PATH", target)
    monkeypatch.setattr(fl, "DEFAULTS_PATH", tmp_path / "defaults.json")
    real = fl.PROJECT_ROOT / "formatter_links.json"
    real_before = real.read_text() if real.exists() else None
    fl.save({"x": (["generic-excel"], "generic-excel")})
    assert fl.load() == {"x": (["generic-excel"], "generic-excel")} and target.exists()
    assert (real.read_text() if real.exists() else None) == real_before


def test_local_links_override_shipped_defaults(tmp_path, monkeypatch):
    defaults, local = tmp_path / "defaults.json", tmp_path / "links.json"
    monkeypatch.setattr(fl, "DEFAULTS_PATH", defaults)
    monkeypatch.setattr(fl, "LINKS_PATH", local)
    fl.save({"a": (["generic-excel"], "generic-excel"),
             "new-script": (["asset-reference-excel"], "asset-reference-excel")}, defaults)
    assert fl.load() == fl.load(defaults)  # no local file yet: shipped links apply
    fl.save({"a": (["asset-reference-excel", "generic-excel"], "asset-reference-excel")})
    merged = fl.load()
    assert merged["a"] == (["asset-reference-excel", "generic-excel"], "asset-reference-excel")  # local wins
    assert merged["new-script"] == (["asset-reference-excel"], "asset-reference-excel")  # shipped fills the gap
    assert json.loads(defaults.read_text())["a"]["default"] == "generic-excel"  # defaults never rewritten


def test_local_links_file_is_not_tracked():
    ignored = (fl.PROJECT_ROOT / ".gitignore").read_text().splitlines()
    assert "/formatter_links.json" in ignored and fl.DEFAULTS_PATH.exists()
