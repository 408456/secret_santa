import random

import pytest

from app.algorithm import DrawImpossibleError, make_draw


def test_draw_is_bijection_and_derangement():
    ids = list(range(1, 21))
    result = make_draw(ids, rng=random.Random(42))
    assert set(result) == set(ids)
    assert set(result.values()) == set(ids)
    assert all(giver != receiver for giver, receiver in result.items())


def test_draw_honors_bidirectional_exclusions():
    result = make_draw([1, 2, 3, 4], [(1, 2), (3, 4)], rng=random.Random(7))
    assert result[1] != 2 and result[2] != 1
    assert result[3] != 4 and result[4] != 3


def test_impossible_draw_raises():
    with pytest.raises(DrawImpossibleError):
        make_draw([1, 2], [(1, 2)])

