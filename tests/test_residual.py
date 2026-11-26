
from fractions import Fraction as Q

from qforge_toolkit.checkers.residual import (
    check_eigenpair,
    residual_disk,
    residual_ratio_sq,
)


def test_exact_eigenpair():
    # diag(1, 4), vector e1
    A = [[1, 0], [0, 4]]
    assert residual_ratio_sq(A, [1, 0], 1) == 0
    assert check_eigenpair(A, [1, 0], 1)["accepted"] is True


def test_wrong_lambda_is_refused():
    A = [[1, 0], [0, 4]]
    plant = check_eigenpair(A, [1, 0], 4)
    assert plant["accepted"] is False
    assert Q(plant["residual_ratio_sq"]) > 0


def test_residual_disk_normal_and_plant():
    A = [[2, 1], [1, 2]]  # symmetric, so normal
    disk = residual_disk(A, [1, 1], 3)
    assert disk["normal"] is True
    assert disk["encloses_an_eigenvalue"] is True
    assert disk["radius_sq"] == "0"
    # Non-normal (rotation + shear)
    B = [[0, -1], [2, 0]]
    disk_b = residual_disk(B, [1, 0], 0)
    assert disk_b["normal"] is False
    assert disk_b["encloses_an_eigenvalue"] is False
