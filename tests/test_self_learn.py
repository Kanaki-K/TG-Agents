"""Тесты взвешенной выборки пикера (core/self_learn.weighted_sample)."""
from core import self_learn


def test_size_and_unique():
    out = self_learn.weighted_sample(list(range(20)), 5, lambda x: 1.0)
    assert len(out) == 5 and len(set(out)) == 5 and set(out) <= set(range(20))


def test_k_ge_len_returns_all():
    assert sorted(self_learn.weighted_sample([1, 2, 3], 10, lambda x: 1.0)) == [1, 2, 3]


def test_empty():
    assert self_learn.weighted_sample([], 5, lambda x: 1.0) == []


def test_favors_high_weight():
    items = ["a", "b", "c", "d"]
    w = {"a": 8.0}
    top = {it: 0 for it in items}
    for _ in range(500):
        top[self_learn.weighted_sample(items, 1, lambda x: w.get(x, 1.0))[0]] += 1
    assert top["a"] > top["b"] and top["a"] > top["c"]  # тяжёлый чаще становится топ-1
