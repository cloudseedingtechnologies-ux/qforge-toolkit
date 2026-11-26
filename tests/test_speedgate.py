
from qforge_toolkit.speedgate import decide


def _spec(exact=True, complete=True, cand=None):
    return {"cases": [{
        "name": "toy",
        "exact": exact,
        "complete_task": complete,
        "threads": 1,
        "base_s": [10, 10, 10],
        "cand_s": cand or [8, 8, 8],  # 20% faster
    }]}


def test_adopt_stage_reject():
    assert decide(_spec())["overall"] == "ADOPT"
    assert decide(_spec(cand=[9.5, 9.5, 9.5]))["overall"] == "STAGE"  # 5%
    assert decide(_spec(complete=False))["overall"] == "STAGE"
    assert decide(_spec(exact=False))["overall"] == "REJECT"
