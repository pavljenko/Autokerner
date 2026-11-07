"""Protect authored FEA coverage in Classic proposals, without inventing values.

These are editing/report adapters, not a shaping engine. Numeric values always
come from the visual kerning tables; authored text may position text differently.
"""
import copy


class CoverageOld:
    def __init__(self, visual, coverage):
        self.visual = visual
        self.coverage = coverage
        self.visual_count = visual.count
        # Positive count is a routing sentinel: Classic must choose MISSING,
        # even when the authored kerning exists only in feature code.
        self.count = visual.count + bool(coverage.pairs or coverage.glyphs)
        self.classes = visual.classes

    def has_author(self, left, right):
        return self.coverage.has(left, right)

    def has(self, left, right):
        return self.visual.has(left, right) or self.has_author(left, right)

    def value(self, left, right):
        return self.visual.value(left, right)

    def __getattr__(self, name):
        return getattr(self.visual, name)


def old_factory(visual_factory, coverages):
    """One ordered wrapper for each selected master in Classic _calculate."""
    iterator = iter(coverages)
    def create(*args):
        try:
            coverage = next(iterator)
        except StopIteration:
            raise RuntimeError('Classic text coverage/master order differs') from None
        return CoverageOld(visual_factory(*args), coverage)
    return create


def authored_pair(old_views, left, right):
    return any(getattr(old, 'has_author', lambda a, b: False)(left, right) for old in old_views)


def visual_report(report, old_views, models):
    """Do not display routing sentinels or numeric authored control-pair values."""
    result = copy.copy(report)
    result.kern_before = [(label, getattr(old, 'visual_count', old.count), old.classes)
                          for (label, _, _), old in zip(report.kern_before, old_views)]
    if not models:
        return result
    model = models[0]
    result.control = []
    for text, values in report.control:
        if len(text) == 2:
            a, b = model.glyph(ord(text[0])), model.glyph(ord(text[1]))
            if a is not None and b is not None and authored_pair(old_views, model.name(a), model.name(b)):
                continue
        result.control.append((text, values))
    return result
