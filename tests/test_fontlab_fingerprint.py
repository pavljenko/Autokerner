"""State guard tests without loading the native FontLab modules."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autokerner.fontlab_bridge import FontSource


class FingerprintTest(unittest.TestCase):
    def setUp(self):
        self.source = FontSource.__new__(FontSource)
        self.source.font = SimpleNamespace(glyphs=[SimpleNamespace(name="A")])
        self.source.master_names = ["Regular", "Bold"]
        self.layer = SimpleNamespace(advanceWidth=600)
        self.source.layer = lambda name, master: self.layer
        self.source.marked_names = lambda: []
        self.pairs = {
            "Regular": [("A", False, "V", False, -71.0)],
            "Bold": [("A", False, "V", False, -90.0)],
        }
        self.groups = {"Regular": {"Left": (["A", "Aacute"], "KernLeft")}, "Bold": {}}
        self.source.kerning_now = lambda master: (self.pairs[master], self.groups[master])
        # The old implementation reads only keys() and misses value changes.
        self.source.package = SimpleNamespace(
            kerning=lambda master: SimpleNamespace(keys=lambda: list(range(len(self.pairs[master])))))

    def test_pair_value_change_invalidates_result(self):
        before = self.source.fingerprint()
        self.pairs["Regular"][0] = ("A", False, "V", False, -133.0)
        self.assertNotEqual(before, self.source.fingerprint())

    def test_pair_replacement_with_same_count_invalidates_result(self):
        before = self.source.fingerprint()
        self.pairs["Regular"][0] = ("A", False, "W", False, -71.0)
        self.assertNotEqual(before, self.source.fingerprint())

    def test_class_membership_change_invalidates_result(self):
        before = self.source.fingerprint()
        self.groups["Regular"]["Left"] = (["A", "Abreve"], "KernLeft")
        self.assertNotEqual(before, self.source.fingerprint())

    def test_class_side_change_invalidates_result(self):
        before = self.source.fingerprint()
        self.groups["Regular"]["Left"] = (["A", "Aacute"], "KernRight")
        self.assertNotEqual(before, self.source.fingerprint())

    def test_record_order_is_not_a_change(self):
        self.pairs["Regular"].append(("T", False, "o", False, 0.0))
        before = self.source.fingerprint()
        self.pairs["Regular"].reverse()
        self.groups["Regular"]["Left"][0].reverse()
        self.assertEqual(before, self.source.fingerprint())

    def test_only_calculated_masters_are_checked(self):
        before = self.source.fingerprint(["Regular"])
        self.pairs["Bold"][0] = ("A", False, "V", False, -140.0)
        self.assertEqual(before, self.source.fingerprint(["Regular"]))
        self.assertNotEqual(self.source.fingerprint(["Regular"]), self.source.fingerprint(["Bold"]))

    def test_width_guard_remains_active(self):
        before = self.source.fingerprint()
        self.layer.advanceWidth += 1
        self.assertNotEqual(before, self.source.fingerprint())


if __name__ == "__main__":
    unittest.main()
