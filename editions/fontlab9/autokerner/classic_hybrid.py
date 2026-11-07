"""Classic AutoResult contract with optional FontLab proposal providers.

The own/own path uses auto.run with independent composite-letter metrics.
Native imports are lazy, so this module
and its calculation adapter can be tested without an editor or a window.
"""
import copy
import math
from pathlib import Path

from . import auto
from .geometry import contours_rect, irnd
from .kerning import KernMatrix, adjust_values, make_matrix, matrix_names, plan_variable
from .options import MERGE, Options
from .spacing import SpacingItem, SpacingPlan

SPACING = ('Autokerner', 'FL Optical', 'FL Neural', 'FL Neural linked')
KERNING = ('Autokerner', 'FL Geometric', 'FL Optical', 'FL Neural')


def _aligned(masters, result):
    aligned, changes = [], []
    for w, model in enumerate(masters):
        values = {n: v[w] for n, v in result.spacing.items() if w in v}
        if w in result.space:
            i = model.glyph(32)
            if i is not None:
                values[model.name(i)] = (0, result.space[w])
        changes.append(values)
        aligned.append(model.with_metrics(values))
    return aligned, changes


def _native_plan(model, proposals, options):
    items = []
    for glyph in model.glyphs:
        box = contours_rect(glyph.contours)
        if box is None:
            continue
        left, right = box[0], glyph.advance - box[2]
        dx, width = proposals.get(glyph.name, (0, glyph.advance))
        items.append(SpacingItem(glyph.name, glyph.codes[0] if glyph.codes else None,
                                 None, glyph.advance, left, right, 0, 0,
                                 left + dx, right + width - glyph.advance - dx, width))
    rule = copy.copy(options.spacing_rule())
    rule.threshold = 0
    return SpacingPlan(items, rule, {}, model.upm, {}, 0, None)


def calculate(source, masters, *, master_names=None, options=None, fixed=(), progress=None,
              spacing_engine='Autokerner', kerning_engine='Autokerner', workdir=None, native=None):
    """Return the unmodified Classic result shape; progress exceptions cancel.

    Native provider contract: spacing(source, model, fixed, options, say) returns
    {name: (dx, advance)}; kerning(source, aligned_model, changes, names, options,
    say) returns {'left|right': value}. Providers never modify the source.
    """
    if spacing_engine not in SPACING or kerning_engine not in KERNING:
        raise ValueError('Unknown hybrid engine')
    masters = list(masters)
    if not masters:
        raise ValueError('No masters selected')
    names = list(master_names or [m.label for m in masters])
    if names != [m.label for m in masters]:
        raise ValueError('Master names must match the supplied model order')
    o = options or Options()
    native_used = (o.spacing and spacing_engine != 'Autokerner') or (o.kerning and kerning_engine != 'Autokerner')
    # The Classic default remains available for FL8 comparisons. FL9 also
    # measures the resolved shape of composite letters: inheriting only a
    # base glyph's delta cannot repair independently damaged composite metrics.
    component_metrics = o.spacing and spacing_engine == 'Autokerner' and any(
        g.components for m in masters for g in m.glyphs)
    own_kwargs = {'component_metrics': True} if component_metrics else {}
    if not native_used:
        return auto.run(masters, options=o, fixed=fixed, progress=progress, **own_kwargs)
    say = progress or (lambda message: None)
    native = native or NativeProvider(workdir, spacing_engine, kerning_engine)
    fixed = frozenset(fixed)
    base_options = Options.from_dict(o.to_dict())
    base_options.kerning = False
    if spacing_engine != 'Autokerner':
        base_options.spacing = False
    result = auto.run(masters, options=base_options, fixed=fixed, progress=progress, **own_kwargs)
    if o.spacing and spacing_engine != 'Autokerner':
        proposals = []
        for w, model in enumerate(masters):
            say('апроши: мастер %d из %d' % (w + 1, len(masters)))
            values = native.spacing(source, model, fixed, o, say)
            valid = {g.name for g in model.glyphs} - fixed
            if not set(values) <= valid:
                raise ValueError('Native spacing returned unknown or protected glyphs')
            if any(not all(math.isfinite(float(x)) for x in pair) for pair in values.values()):
                raise ValueError('Non-finite native spacing')
            proposals.append(values)
        changed = {n for w, values in enumerate(proposals) for n, (dx, width) in values.items()
                   if abs(dx) > 1e-7 or abs(width - masters[w].advance(masters[w].by_name(n))) > 1e-7}
        result.spacing = {n: {w: proposals[w].get(n, (0, model.advance(model.by_name(n))))
                              for w, model in enumerate(masters) if model.by_name(n) is not None}
                          for n in sorted(changed)}
        # Preserve the Classic NBSP follow-space result; native engines skip it.
        if o.space and o.nbsp_follows_space:
            result.spacing.update(auto._nbsp(masters, result.space, fixed))
        result.plans = [_native_plan(m, proposals[w], o) for w, m in enumerate(masters)]
    if o.kerning:
        aligned, changes = _aligned(masters, result)
        common = matrix_names(aligned[0], o.kern_law())
        matrices = []
        for w, model in enumerate(aligned):
            if kerning_engine == 'Autokerner':
                def step(row, total, w=w):
                    say('кернинг: мастер %d из %d, знак %d из %d' % (w + 1, len(masters), row + 1, total))
                matrix = adjust_values(make_matrix(model, o.kern_law(), common, step), o.kern_round,
                                       irnd(o.kern_max_tight * model.upm / 1000),
                                       irnd(o.kern_max_loose * model.upm / 1000))
            else:
                values = native.kerning(source, model, changes[w], common, o, say)
                keys = (a + '|' + b for a in common for b in common)
                numbers = []
                for key in keys:
                    if key not in values or not math.isfinite(float(values[key])):
                        raise ValueError('Incomplete or non-finite native kerning: ' + key)
                    numbers.append(float(values[key]))
                glyphs = [model.glyphs[model.by_name(n)] for n in common]
                matrix = KernMatrix(common, [bool(g.codes) for g in glyphs],
                                    [any(chr(c).isdigit() for c in g.codes) for g in glyphs],
                                    numbers, [32767] * len(numbers), 0)
            matrices.append(matrix)
        say('кернинг: классы на все мастера')
        result.kern = plan_variable(matrices, [m.weight for m in masters], masters[0].upm,
                                    o.kern_rule(), progress=progress)
        worst = {}
        for matrix in matrices:
            for a, b, c, depth in matrix.collisions:
                worst[a, b, c] = max(depth, worst.get((a, b, c), 0))
        result.collisions = sorted(((a, b, c, d) for (a, b, c), d in worst.items()), key=lambda r: -r[3])
    result.hybrid_metadata = {'spacing_engine': spacing_engine, 'kerning_engine': kerning_engine,
                              'native_used': True,
                              'warnings': ['Native kerning class packing has no geometric collision-slack guarantee.']
                              if o.kerning and kerning_engine != 'Autokerner' else []}
    return result


class NativeProvider:
    """Sequential owned copies; lazy FontLab access, cancellable between batches."""
    def __init__(self, workdir=None, spacing_engine='FL Neural', kerning_engine='FL Neural'):
        self.workdir = Path(workdir or '/private/tmp/autokerner-classic-hybrid')
        self.spacing_engine, self.kerning_engine = spacing_engine, kerning_engine

    def spacing(self, source, model, fixed, options, say):
        import fontpr
        from .hybrid import Session
        prefs = {p['key']: p['value'] for p in fontpr.get_preferences(
            keys=['editor.autospace_method', 'editor.autospace_link'])['preferences']}
        session = Session(source, model.label, self.workdir)
        session.names = [g.name for g in model.glyphs]
        session.protected = set(fixed)
        session.options = options
        before = {g.name: (g.rect[0], g.advance - g.rect[2], g.advance)
                  for g in model.glyphs if g.rect is not None}
        try:
            answer = session._spacing(self.spacing_engine, model, before)
        finally:
            fontpr.set_preferences(patch=prefs)
        say('апроши: ' + model.label)
        return answer

    def kerning(self, source, model, changes, names, options, say):
        import fontlab as fl
        import fontpr
        from PythonQt import QtGui
        from .fontlab_bridge import FontSource, Snapshot
        from .hybrid import check
        from .temporary import temporary_font
        prefs = {p['key']: p['value'] for p in fontpr.get_preferences(keys=['editor.autokern_method'])['preferences']}
        result = {}
        try:
            with temporary_font(source.package.fgId, model.label, self.workdir) as identifier:
                owned = FontSource(next(f for f in fl.AllFonts() if fl.flPackage(f).fgId == identifier))
                try:
                    plan = auto.AutoResult([model.weight], {n: {0: v} for n, v in changes.items()}, {}, None, [])
                    owned._apply_spacing(plan, 0, model.label, QtGui, Snapshot([model.label]))
                    owned._refresh()
                    check(fontpr.set_preferences(patch={'editor.autokern_method': KERNING.index(self.kerning_engine) - 1}))
                    batch = []
                    total = len(names) ** 2
                    done = 0
                    def flush():
                        nonlocal done
                        say('кернинг: %s, пар %d из %d' % (model.label, done, total))
                        response = check(fontpr.run_actions(font_id=identifier, actions=[{
                            'id': 'auto_kern', 'apply': False, 'master_name': model.label, 'pairs': list(batch)}], undo=False))
                        rows = response['metrics_actions'][0]['result']['pairs']
                        expected = {(r['left'], r['right']) for r in batch}
                        if len(rows) != len(expected) or {(r['left'], r['right']) for r in rows} != expected:
                            raise ValueError('Native kerning batch is incomplete')
                        for row in rows:
                            v = float(row['value']) * options.kern_strength / 100
                            if options.kern_round > 1:
                                v = math.ceil(v / options.kern_round) * options.kern_round
                            if options.kern_max_tight:
                                v = max(v, -round(options.kern_max_tight * model.upm / 1000))
                            if options.kern_max_loose:
                                v = min(v, round(options.kern_max_loose * model.upm / 1000))
                            if abs(v) < options.kern_threshold * model.upm / 1000:
                                v = 0
                            result[row['left'] + '|' + row['right']] = v
                        done += len(batch)
                        batch.clear()
                    for a in names:
                        for b in names:
                            batch.append({'left': a, 'right': b})
                            if len(batch) == 128:
                                flush()
                    if batch:
                        flush()
                finally:
                    owned._glyphs.clear()
                    owned.package = owned.font = None
        finally:
            fontpr.set_preferences(patch=prefs)
        say('кернинг: ' + model.label)
        return result


def prepare_text_plan(source, result, master_names, options, only=None, rejected=(), workdir=None,
                      spacing_applied=False):
    """Prepare existing Session MM/VF machinery from a Classic packed result.

    No recalculation, font write or 80-glyph limit. Only absent rules are added;
    source and all unselected masters remain author-owned.
    """
    if options.kern_mode != MERGE:
        raise ValueError('Authored text kern requires merge mode; Replace is not a preserving operation')
    if (result.spacing or result.space) and not spacing_applied:
        raise ValueError('Apply and validate the calculated spacing before preparing the MM/VF kerning plan')
    import fontpr
    import fontgate as fg
    from . import axis_map, text_kern
    from .hybrid import Session, parameters, state
    if result.kern is None or not source.has_kern_feature() or len(source.master_names) < 2:
        raise ValueError('A multimaster font with text kern and calculated kerning is required')
    master_names = list(master_names)
    session = Session(source, master_names[0], Path(workdir or '/private/tmp/autokerner-classic-hybrid'))
    session.stage = 'kerning'
    session.options = Options.from_dict(options.to_dict())
    session.options_snapshot = session.options.to_dict()
    info = fontpr.get_font_info(font_id=source.package.fgId)
    native = axis_map.effective_axes(source.package)
    session.master_info = axis_map.with_native_axes(info, native)
    session.axis_reference = axis_map.reference_for(source, session.master_info, native)
    session.parameter_values = parameters(info)
    session.token = state(source, session.master)
    session.protected = set(source.protected(options, masters=master_names))
    session.text_coverage = text_kern.Coverage()
    layout = fg.fgOTLayout(source.font)
    glyph_names = [g.name for g in source.font.glyphs]
    for values in session.parameter_values.values():
        coverage = text_kern.coverage(text_kern.resolve(layout.get_prefix(), values),
                                     text_kern.resolve(layout.get_feature('kern'), values), glyph_names)
        session.text_coverage.pairs.extend(coverage.pairs)
        session.text_coverage.glyphs.update(coverage.glyphs)
    kern = result.kern
    names = set(kern.left_class) | set(kern.right_class)
    for key in kern.pairs:
        names.update(key.split('|'))
    session.names = sorted(names)
    by_master = {m: {} for m in source.master_names}
    selected = set(only or ())
    rejected = set(rejected)
    for a in sorted(names):
        for b in sorted(names):
            key = a + '|' + b
            if key in rejected or (selected and a not in selected and b not in selected):
                continue
            values = [kern.value(a, b, w) for w in range(len(master_names))]
            if not any(values):
                continue
            for m in by_master:
                by_master[m][key] = values[master_names.index(m)] if m in master_names else 0
    engine = 'Classic hybrid plan'
    session.master_proposals = {engine: by_master}
    session.proposals = {engine: by_master[session.master]}
    session._plan_masters(engine, list(by_master[session.master]))
    return session
