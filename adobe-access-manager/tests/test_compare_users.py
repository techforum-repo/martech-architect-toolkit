import pandas as pd

from adobe_access.users import compare_custom_group_memberships


def test_compare_filters_to_cached_custom_groups():
    cached = pd.DataFrame([
        {"adobe_group_name": "ACME-CJA-A", "display_name": "CJA A", "system": "CJA"},
        {"adobe_group_name": "ACME-AEM-B", "display_name": "AEM B", "system": "AEM"},
        {"adobe_group_name": "ACME-AEP-C", "display_name": "AEP C", "system": "AEP"},
    ])
    left = {"groups": {"acme-cja-a", "ACME-AEM-B", "SYSTEM-GROUP"}}
    right = {"groups": {"ACME-CJA-A", "ACME-AEP-C"}}
    result = compare_custom_group_memberships(left, right, cached)
    assert set(result["adobe_group_name"]) == {"ACME-CJA-A", "ACME-AEM-B", "ACME-AEP-C"}
    values = dict(zip(result["adobe_group_name"], result["comparison"]))
    assert values["ACME-CJA-A"] == "Shared"
    assert values["ACME-AEM-B"] == "Only first user"
    assert values["ACME-AEP-C"] == "Only second user"


def test_compare_returns_empty_when_no_cached_memberships():
    cached = pd.DataFrame([{"adobe_group_name": "ACME-CJA-A", "display_name": "CJA A", "system": "CJA"}])
    result = compare_custom_group_memberships({"groups": {"SYSTEM-A"}}, {"groups": {"SYSTEM-B"}}, cached)
    assert result.empty
