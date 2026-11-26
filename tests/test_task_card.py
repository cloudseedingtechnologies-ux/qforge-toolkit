
from qforge_toolkit.task_card import validate_card

GOOD = {
    "id": "CARD-1",
    "owner": "alice",
    "reviewer": "bob",
    "question": "Does the checker refuse a swapped sector?",
    "ceiling": "BOUNDED_CERTIFICATE",
    "falsifier": "A swapped sector is accepted.",
    "planted": [{"input": "swapped", "rejected": True}],
    "not_claimed": ["This is not a general uniqueness proof."],
}


def test_good_card_and_plants():
    assert validate_card(GOOD)["ok"] is True
    same = dict(GOOD, reviewer="alice")
    assert "owner must not be the reviewer" in validate_card(same)["problems"]
    high = validate_card(GOOD, max_ceiling="FINITE_EXPERIMENT")
    assert any("ceiling exceeds" in p for p in high["problems"])
    missing = dict(GOOD, planted=[])
    assert any("planted" in p for p in validate_card(missing)["problems"])
