
from decimal import Decimal
from fractions import Fraction as Q

from qforge_toolkit.checkers.inertia import check_inertia, inertia


def test_closed_forms():
    assert inertia([[0, 1], [1, 0]]) == (1, 1, 0)
    assert inertia([[1, 0, 0], [0, -2, 0], [0, 0, 0]]) == (1, 1, 1)
    assert inertia([[0, 0], [0, 0]]) == (0, 0, 2)
    assert inertia([[2, 1], [1, 2]], Q(5, 2))[1] == 1
    assert inertia([[Q(0), Q(1)], [Q(1), Q(0)]], policy="last") == (1, 1, 0)


def test_orders_agree():
    matrix = [[0, 1, 0], [1, 0, 0], [0, 0, 5]]
    assert inertia(matrix, policy="first") == inertia(matrix, policy="last") == (2, 1, 0)


def test_refuses_non_rational_and_non_symmetric():
    for bad in ("1/3", Decimal(1), 1.5, True):
        try:
            inertia([[bad]])
        except ValueError:
            pass
        else:
            raise AssertionError(f"should refuse {bad!r}")
    try:
        inertia([[1, 2], [0, 1]])
    except ValueError:
        pass
    else:
        raise AssertionError("should refuse a non-symmetric matrix")


def test_claimed_count_and_plants():
    matrix = [[1, 0], [0, -3]]
    assert check_inertia(matrix, (1, 1, 0))["accepted"] is True
    plant = check_inertia(matrix, (2, 0, 0))
    assert plant["accepted"] is False
