
from qforge_toolkit.claim_lint import lint_json, lint_text


def test_flags_unbounded_and_allows_limited():
    bad = lint_text("This certified result proves the conjecture.")
    assert bad["findings"]
    good = lint_text("This does not prove the conjecture; it is only a finite experiment.")
    assert good["findings"] == []


def test_json_scans_claim_not_not_claimed():
    obj = {
        "claim": "We only report a finite experiment.",
        "not_claimed": "This proves the millennium problem.",
        "ceiling": "FINITE_EXPERIMENT",
    }
    res = lint_json(obj)
    assert res["findings"] == []
    strong = lint_json({"claim": "This is a certified proof of the result.", "ceiling": "FINITE_EXPERIMENT"})
    assert strong["findings"]
