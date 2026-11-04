from pathlib import Path

import adobe_access.database as database


def test_sync_completely_replaces_catalog(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.initialize()

    first = database.replace_managed_groups([
        {"name": "ACME-CJA-A", "system": "CJA", "member_count": 2},
        {"name": "ACME-AEM-B", "system": "AEM", "member_count": 3},
    ])
    assert first["groups"] == 2
    assert set(database.read_managed_groups()["adobe_group_name"]) == {"ACME-CJA-A", "ACME-AEM-B"}

    second = database.replace_managed_groups([
        {"name": "ACME-CJA-C", "system": "CJA", "member_count": 1},
    ])
    assert second["groups"] == 1
    rows = database.read_managed_groups()
    assert rows["adobe_group_name"].tolist() == ["ACME-CJA-C"]
    assert "enabled" not in rows.columns
    assert "missing_from_adobe" not in rows.columns


def test_duplicate_groups_are_inserted_once(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.initialize()
    database.replace_managed_groups([
        {"name": "ACME-CJA-A", "system": "CJA"},
        {"name": "ACME-CJA-A", "system": "CJA"},
        {"name": "", "system": "Other"},
    ])
    assert len(database.read_managed_groups()) == 1
