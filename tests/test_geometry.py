"""Обмер контуров: округления Swift, габарит как у BoundsPen, профиль чернил"""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from autokerner.geometry import (Contour, f32, ink_profile, polygon_edges, polygons,  # noqa: E402
                                    rnd, split_contours)


def профиль_по_строкам(полигоны, low, high, step):
    """Профиль дословно как в исходной программе: каждая строка — все рёбра"""
    import math
    строк = max(1, int(math.ceil((high - low) / step)))
    слева, справа = [None] * строк, [None] * строк
    for r in range(строк):
        y = low + (r + 0.5) * step
        кресты = []
        for п in полигоны:
            for i in range(len(п)):
                a, b = п[i], п[(i + 1) % len(п)]
                if (a[1] <= y) == (b[1] <= y):
                    continue
                t = (y - a[1]) / (b[1] - a[1])
                кресты.append(a[0] + (b[0] - a[0]) * t)
        if кресты:
            слева[r], справа[r] = min(кресты), max(кресты)
    return слева, справа


def случайный_контур(rng):
    точки = [(rng.uniform(-50, 600), rng.uniform(-200, 900)) for _ in range(rng.randint(3, 7))]
    команды = [("moveTo", точки[0])]
    for p in точки[1:]:
        if rng.random() < 0.5:
            команды.append(("lineTo", p))
        else:
            команды.append(("curveTo", (rng.uniform(-80, 650), rng.uniform(-250, 950)),
                            (rng.uniform(-80, 650), rng.uniform(-250, 950)), p))
    команды.append(("closePath",))
    return команды


class RoundingTest(unittest.TestCase):
    def test_half_away_from_zero(self):
        self.assertEqual(rnd(2.5), 3)
        self.assertEqual(rnd(-2.5), -3)
        self.assertEqual(rnd(0.49999999999999994), 0)
        self.assertEqual(rnd(-0.5), -1)
        self.assertEqual(rnd(1.4999), 1)

    def test_single_precision(self):
        self.assertEqual(f32(0.1), 0.10000000149011612)
        self.assertEqual(f32(float("inf")), float("inf"))


class BoundsTest(unittest.TestCase):
    def test_bounds_match_fonttools(self):
        try:
            from fontTools.pens.boundsPen import BoundsPen
        except ImportError:
            self.skipTest("нет fontTools")
        rng = random.Random(7)
        for _ in range(300):
            команды = случайный_контур(rng)
            перо = BoundsPen(None)
            for к in команды:
                getattr(перо, к[0])(*к[1:])
            self.assertEqual(Contour(команды).rect, перо.bounds)

    def test_split_drops_open_tail(self):
        команды = [("moveTo", (0, 0)), ("lineTo", (10, 0)), ("lineTo", (10, 10)), ("closePath",),
                   ("moveTo", (20, 0)), ("lineTo", (30, 0))]
        self.assertEqual(len(split_contours(команды)), 1)


class ProfileTest(unittest.TestCase):
    def test_profile_equals_row_by_row(self):
        rng = random.Random(11)
        for _ in range(60):
            контуры = [Contour(случайный_контур(rng)) for _ in range(rng.randint(1, 3))]
            полигоны = polygons(контуры)
            for low, high, step in ((-600.0, 1500.0, 5.0), (-0.0, 700.0, 1000 / 256),
                                    (347.5, 352.5, 5.0)):
                п = ink_profile(polygon_edges(полигоны), low, high, step)
                слева, справа = профиль_по_строкам(полигоны, low, high, step)
                self.assertEqual(п.left, слева)
                self.assertEqual(п.right, справа)


if __name__ == "__main__":
    unittest.main()
