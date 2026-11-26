
from fractions import Fraction as Q

from qforge_toolkit.checkers.temple import check_temple_enclosure, temple_lower_bound, rayleigh


def test_exact_eigenvector_bound_is_mu():
    A = [[1, 0], [0, 4]]
    mu = rayleigh(A, [1, 0])
    assert mu == 1
    rec = check_temple_enclosure(A, [1, 0], zeta=3, claimed_lo=1)
    assert rec["accepted"] is True
    assert rec["temple_lo"] == "1"


def test_temple_formula_and_tighter_claim_refused():
    # r^2 = 1, mu = 2, zeta = 4 -> lo = 2 - 1/2 = 3/2
    lo = temple_lower_bound(2, 1, 4)
    assert lo == Q(3, 2)
    A = [[2, 1], [1, 2]]  # eigenvalues 1 and 3; [1,0] has mu=2, r>0
    rec = check_temple_enclosure(A, [1, 0], zeta=3, claimed_lo=2)
    assert rec["accepted"] is False  # 2 is mu, tighter than temple_lo < mu


def test_zeta_not_above_mu_refused():
    A = [[1, 0], [0, 4]]
    rec = check_temple_enclosure(A, [1, 0], zeta=1, claimed_lo=0)
    assert rec["accepted"] is False
    try:
        temple_lower_bound(2, 1, 2)
    except ValueError:
        pass
    else:
        raise AssertionError("zeta == mu must be refused")
