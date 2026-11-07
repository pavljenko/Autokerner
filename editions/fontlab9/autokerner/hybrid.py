"""Local FL9 prototype. Proposals are computed on disposable document copies.

Spacing applies to one chosen master; textual MM kerning plans cover all masters.
Existing kerning is always kept.
No automatic inference that an author's spacing is wrong.
"""
import hashlib
import json
import math
from pathlib import Path

from .auto import AutoResult, run
from .fontlab_bridge import FontSource, OldKerning, Snapshot
from .geometry import contours_rect
from .options import Options
from .temporary import temporary_font, copy_metrics, copy_ink_metrics
from . import text_kern, axis_map

SPACING = ('Autokerner', 'FL Optical', 'FL Neural', 'FL Neural linked')
KERNING = ('Autokerner', 'FL Geometric', 'FL Optical', 'FL Neural')


def stable(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def metrics(source, master):
    model = source.read(masters=[master])[0]
    result = {}
    for g in model.glyphs:
        rect = contours_rect(g.contours)
        if rect:
            width = float(source.layer(g.name, master).advanceWidth)
            result[g.name] = (rect[0], width - rect[2], width)
        elif 0x20 in g.codes or 0xA0 in g.codes:
            width = float(source.layer(g.name, master).advanceWidth)
            result[g.name] = (0., width, width)
    return model, result


def state(source, master):
    return hashlib.sha256(stable(state_data(source, master)).encode('utf-8')).hexdigest()


def state_data(source, master):
    """Geometry, metrics/formulas, feature text, class members/values and marks."""
    from .fontlab_bridge import _api
    _, fg = _api()
    import fontpr
    masters = list(source.package.masters)
    models = source.read(masters=masters)
    rows = []
    for m in models:
        for g in m.glyphs:
            layer = source.layer(g.name, m.label)
            rows.append((m.label, g.name, g.codes, [c.commands for c in g.contours], g.components,
                         None if layer is None else (layer.advanceWidth, layer.metricsLeft,
                                                     layer.metricsRight, layer.metricsWidth)))
    features = fg.fgOTLayout(source.font)
    text = {str(k): str(features.get_feature(k)) for k in features.keys()}
    info = fontpr.get_font_info(font_id=source.package.fgId)
    # currentMaster is a view choice. Axis mappings, locations, parameters and
    # non-selected masters are substantive state and must invalidate proposals.
    meta = {k: info.get(k) for k in ('axes', 'masters', 'defaultMaster', 'instances', 'interpolationFlags')}
    meta['nativeAxes'] = axis_map.native_axes(source.package)
    meta['embeddedAvar'] = axis_map.embedded_value(source.package)
    data = (source.fingerprint(masters), rows, text, features.get_prefix(), meta,
            [(m.label, m.upm, m.x_height, m.cap_height, m.italic_angle) for m in models])
    return data


def eligible_pairs(source, master, pairs, protected):
    old = OldKerning(*source.kerning_now(master))
    return {k: v for k, v in pairs.items()
            if not old.has(*k.split('|')) and not set(k.split('|')) & set(protected)}


class Session:
    def __init__(self, source, master, workdir):
        if master not in source.master_names:
            raise ValueError('Неизвестный мастер')
        self.source, self.master = source, master
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.proposals, self.errors = {}, {}
        self.stage, self.token, self.snapshot = None, None, None
        self.undo_token = None
        self.protected = set()
        self.names = []
        self.lifecycle = []
        self.text_coverage = None
        self.applied_pairs = {}
        self.master_proposals = {}
        self.review_plan = None
        self.options = Options(space=False)
        self.options_snapshot = None

    @property
    def multimaster(self):
        return (self.stage == 'kerning' and len(self.source.master_names) > 1
                and self.source.has_kern_feature())

    def protected_names(self, explicit=()):
        o = Options(keep_marked=True, keep_metric_keys=True)
        masters = self.source.master_names if self.stage == 'kerning' else [self.master]
        names = set(self.source.protected(o, masters=masters)) | set(explicit)
        # A protected base also protects dependent composites, recursively.
        glyphs = [g for m in self.source.read(masters=masters) for g in m.glyphs]
        while True:
            more = {g.name for g in glyphs if set(g.components) & names} - names
            if not more:
                return names
            names.update(more)

    def compare(self, stage, names, protected=(), engines=None, options=None):
        import fontpr
        if stage not in ('spacing', 'kerning'):
            raise ValueError(stage)
        available = SPACING if stage == 'spacing' else KERNING
        selected_engines = tuple(available if engines is None else engines)
        if not selected_engines or len(set(selected_engines)) != len(selected_engines) or any(e not in available for e in selected_engines):
            raise ValueError('Выберите доступный движок расчёта')
        self.stage, self.proposals, self.errors = stage, {}, {}
        self.options = Options.from_dict((options or Options(space=False)).to_dict())
        self.options_snapshot = self.options.to_dict()
        self.master_proposals = {}
        self.protected = self.protected_names(protected)
        self.names = sorted(set(names))
        self.requested_names = list(self.names)
        m, before = metrics(self.source, self.master)
        if stage == 'spacing' and self.options.space and 'Autokerner' in selected_engines:
            spaces = [g.name for g in m.glyphs if 0x20 in g.codes or
                      (self.options.nbsp_follows_space and 0xA0 in g.codes)]
            self.names = sorted(set(self.names) | set(spaces))
        unknown = set(self.names) - set(before)
        if unknown:
            raise ValueError('Нет контуров у знаков: ' + ', '.join(sorted(unknown)))
        if not self.names:
            raise ValueError('Выберите знаки')
        if stage == 'kerning' and len(self.names) > 80:
            raise ValueError('Прототип: не более 80 знаков для сравнения кернинга')
        self.before = before
        original_state = state_data(self.source, self.master)
        self.token = hashlib.sha256(stable(original_state).encode('utf-8')).hexdigest()
        self.text_coverage = None
        info = fontpr.get_font_info(font_id=self.source.package.fgId)
        native = axis_map.effective_axes(self.source.package)
        self.master_info = axis_map.with_native_axes(info, native)
        self.axis_reference = axis_map.reference_for(self.source, self.master_info, native) if self.multimaster else None
        self.parameter_values = parameters(info)
        if stage == 'kerning' and self.source.has_kern_feature():
            import fontgate as fg
            layout = fg.fgOTLayout(self.source.font)
            self.text_coverage = text_kern.Coverage()
            for values in self.parameter_values.values():
                owned = text_kern.coverage(text_kern.resolve(layout.get_prefix(), values),
                                          text_kern.resolve(layout.get_feature('kern'), values),
                                          [g.name for g in m.glyphs])
                self.text_coverage.pairs.extend(owned.pairs)
                self.text_coverage.glyphs.update(owned.glyphs)
        keys = ['editor.autospace_method', 'editor.autospace_link',
                'editor.autokern_method']
        prefs = {p['key']: p['value'] for p in fontpr.get_preferences(keys=keys)['preferences']}
        try:
            for engine in selected_engines:
                try:
                    if stage == 'spacing':
                        self.proposals[engine] = self._spacing(engine, m, before)
                    else:
                        by_master = {}
                        selected = self.master
                        try:
                            for model in self.source.read(masters=self.source.master_names if self.multimaster else [selected]):
                                self.master = model.label
                                by_master[model.label] = self._kerning(engine, model)
                        finally:
                            self.master = selected
                        if len(by_master) > 1:
                            by_master = self._limit_master_pairs(by_master)
                        self.master_proposals[engine] = by_master
                        self.proposals[engine] = by_master[selected]
                except Exception as error:
                    self.errors[engine] = str(error)
        finally:
            fontpr.set_preferences(patch=prefs)
            fontpr.set_active_font(font_id=self.source.package.fgId)
        final_state = state_data(self.source, self.master)
        if self.token != hashlib.sha256(stable(final_state).encode('utf-8')).hexdigest():
            self.proposals.clear()
            self._guard_details = (original_state, final_state)
            raise RuntimeError('Исходник изменился во время сравнения. Пересчитайте.')
        return self.proposals

    def _spacing(self, engine, model, before):
        import fontpr
        targets = set(self.names) - self.protected
        if not targets:
            return {}
        if engine == 'Autokerner':
            fixed = {g.name for g in model.glyphs} - targets
            o = Options.from_dict(self.options.to_dict())
            o.spacing, o.kerning = True, False
            plan = run([model], options=o, fixed=fixed)
            proposal = {n: place[0] for n, place in plan.spacing.items() if n in targets}
            space = next((g.name for g in model.glyphs if 0x20 in g.codes), None)
            if space in targets and 0 in plan.space:
                proposal[space] = (0., float(plan.space[0]))
            return proposal
        empty = {g.name for g in model.glyphs if not g.contours}
        targets -= empty  # Native spacing does not propose a word-space width.
        if not targets:
            return {}
        with temporary_font(self.source.package.fgId, self.master, self.workdir, self.lifecycle) as identifier:
            fontpr.set_preferences(patch={'editor.autospace_method': 0 if engine == 'FL Optical' else 3,
                                          'editor.autospace_link': engine == 'FL Neural linked'})
            check(fontpr.run_actions(font_id=identifier, actions=[{'id': 'auto_space'}],
                                    glyph_names=sorted(targets), layer_mode='active', undo=False))
            after = copy_ink_metrics(identifier, self.master, sorted(targets))
        return {n: (after[n][0] - before[n][0], after[n][2]) for n in sorted(targets)}

    def _kerning(self, engine, model):
        import fontpr
        pairs = [(a, b) for a in self.names for b in self.names]
        if engine == 'Autokerner':
            # Keep all glyphs as context, but only calculate the requested matrix.
            from .kerning import make_matrix, adjust_values, plan_variable, KernRule
            o = self.options
            matrix = adjust_values(make_matrix(model, o.kern_law(), names=self.names),
                                   o.kern_round, round(o.kern_max_tight * model.upm / 1000),
                                   round(o.kern_max_loose * model.upm / 1000))
            grouped = plan_variable([matrix], [0], model.upm,
                                    KernRule(threshold=o.kern_threshold, visible=o.kern_precision, exception_limit=0))
            values = {a + '|' + b: float(grouped.value(a, b, 0))
                      for a in matrix.names for b in matrix.names}
            return values if self.multimaster else self._limit_pairs(values)
        rows = []
        with temporary_font(self.source.package.fgId, self.master, self.workdir, self.lifecycle) as identifier:
            fontpr.set_preferences(patch={'editor.autokern_method': KERNING.index(engine) - 1})
            for start in range(0, len(pairs), 128):
                response = fontpr.run_actions(font_id=identifier,
                                             actions=[{'id': 'auto_kern', 'apply': False,
                                                       'master_name': self.master,
                                                       'pairs': [{'left': a, 'right': b} for a, b in pairs[start:start + 128]]}],
                                             undo=False)
                check(response)
                rows.extend(response['metrics_actions'][0]['result']['pairs'])
        if {(r['left'], r['right']) for r in rows} != set(pairs):
            raise RuntimeError('Нативный движок вернул неполный набор пар')
        o = self.options
        # FontLab does not expose these as engine parameters. They are explicit
        # proposal adjustments; never alter an existing authored pair.
        values = {}
        for r in rows:
            v = float(r['value']) * o.kern_strength / 100.
            if o.kern_round > 1:
                v = math.ceil(v / o.kern_round) * o.kern_round
            if o.kern_max_tight:
                v = max(v, -round(o.kern_max_tight * model.upm / 1000))
            if o.kern_max_loose:
                v = min(v, round(o.kern_max_loose * model.upm / 1000))
            if abs(v) < o.kern_threshold * model.upm / 1000:
                v = 0.
            values[r['left'] + '|' + r['right']] = v
        return values if self.multimaster else self._limit_pairs(values)

    def _limit_master_pairs(self, by_master):
        keys = set().union(*(set(v) for v in by_master.values()))
        peaks = {k: max((v.get(k, 0.) for v in by_master.values()), key=abs) for k in keys}
        limited = self._limit_pairs(peaks)
        removed = {k for k in keys if peaks[k] and not limited[k]}
        return {m: {k: (0. if k in removed else value) for k, value in values.items()}
                for m, values in by_master.items()}

    def _limit_pairs(self, values):
        limit = self.options.kern_limit
        if not limit:
            return values
        nonzero = [k for k, v in values.items() if v]
        if len(nonzero) <= limit:
            return values
        old = [OldKerning(*self.source.kerning_now(m)) for m in
               (self.source.master_names if self.multimaster else [self.master])]
        def locked(key):
            a, b = key.split('|')
            return (bool({a, b} & self.protected) or
                    bool(self.text_coverage and self.text_coverage.has(a, b)) or
                    any(k.has(a, b) for k in old))
        candidates = [k for k in nonzero if not locked(k)]
        retained = set(sorted(candidates, key=lambda k: (-abs(values[k]), k))[:limit])
        removed = set(candidates) - retained
        return {k: (0. if k in removed else v) for k, v in values.items()}

    def _check_options(self):
        if self.options_snapshot is not None and self.options.to_dict() != self.options_snapshot:
            raise RuntimeError('Settings changed after calculation. Recalculate the proposals.')

    def apply(self, engine, accepted):
        self._check_options()
        if self.stage is None or engine not in self.proposals:
            raise RuntimeError('Сначала сравните предложения выбранного движка')
        if state(self.source, self.master) != self.token:
            raise RuntimeError('Шрифт изменён после расчёта. Пересчитайте: ручная правка сохранена.')
        if self.multimaster:
            return self._plan_masters(engine, accepted)
        proposal = {k: v for k, v in self.proposals[engine].items() if k in set(accepted)}
        source = self.source
        snap = Snapshot([self.master])
        snap.text_kern = None
        snap.added_pairs = []
        # _apply_spacing records each layer immediately before its first mutation.
        try:
            if self.stage == 'spacing':
                from PythonQt import QtGui
                proposal = {n: v for n, v in proposal.items() if n not in self.protected}
                plan = AutoResult([0], {n: {0: v} for n, v in proposal.items()}, {}, None, [])
                source._apply_spacing(plan, 0, self.master, QtGui, snap)
                _, actual = metrics(source, self.master)
                for n, (dx, width) in proposal.items():
                    if abs(actual[n][0] - self.before[n][0] - dx) > .01 or abs(actual[n][2] - width) > .01:
                        raise RuntimeError('Обратное чтение метрик не совпало: ' + n)
            else:
                proposal = eligible_pairs(source, self.master, proposal, self.protected)
                if source.has_kern_feature():
                    import fontgate as fg
                    layout = fg.fgOTLayout(source.font)
                    original = layout.get_feature('kern')
                    # Resolve parameters only for analysis; keep author's source.
                    values = self.parameter_values[self.master]
                    rules = {k: v for k, v in proposal.items() if v and
                             not self.text_coverage.has(*k.split('|'))}
                    lines = ['  pos \\%s \\%s %d;' % (*k.split('|'), round(v)) for k, v in sorted(rules.items())]
                    merged = text_kern.append_rules(layout.get_prefix(), original,
                                                    [g.name for g in source.font.glyphs], lines,
                                                    lambda code: text_kern.resolve(code, values)) if lines else original
                    proposal = {k: round(v) for k, v in rules.items()}
                    snap.text_kern = original
                    if proposal:
                        self._write_text_kern(merged)
                        if layout.get_feature('kern') != merged:
                            raise RuntimeError('Обратное чтение текста kern не совпало')
                else:
                    pairs = [(tuple(k.split('|')), v) for k, v in sorted(proposal.items()) if v]
                    # Only new entries are written. Undo removes just these entries,
                    # never clears/recreates author pairs or kerning groups.
                    snap.added_pairs = [key for key, _ in pairs]
                    if pairs:
                        source.package.kerning(self.master).setPlainPairs(pairs)
                    readback = OldKerning(*source.kerning_now(self.master))
                    for (a, b), v in pairs:
                        if readback.value(a, b) != v:
                            raise RuntimeError('Обратное чтение кернинга не совпало: ' + a + ' ' + b)
                    proposal = {a + '|' + b: v for (a, b), v in pairs}
                self.applied_pairs = dict(proposal)
            source._refresh()
        except Exception:
            self._restore(snap)
            raise
        self.snapshot = snap
        self.undo_token = state(source, self.master)
        self.token = None  # Applied proposals cannot be re-used.
        return len(proposal)

    def undo(self):
        if self.snapshot is None:
            raise RuntimeError('Нет записи для возврата')
        if state(self.source, self.master) != self.undo_token:
            raise RuntimeError('После применения шрифт изменён. Возврат заблокирован для защиты ручных правок.')
        if getattr(self.snapshot, 'planned', False):
            self.review_plan = self.snapshot.previous_plan
            self.applied_pairs = {}
        else:
            self._restore(self.snapshot)
        self.snapshot = None
        self.token = None

    def pair_locked(self, key):
        a, b = key.split('|')
        return (bool({a, b} & self.protected) or
                bool(self.text_coverage and self.text_coverage.has(a, b)) or
                any(OldKerning(*self.source.kerning_now(m)).has(a, b)
                    for m in (self.source.master_names if self.multimaster else [self.master])))

    def _plan_masters(self, engine, accepted):
        import math
        import fontgate as fg
        proposed = self.master_proposals[engine]
        keys = sorted(set(accepted) & set(self.proposals[engine]))
        keys = [k for k in keys if not self.pair_locked(k)]
        if any(not math.isfinite(values[k]) for values in proposed.values() for k in keys):
            raise ValueError('Нечисловой кернинг')
        pairs = {m: {k: round(values[k]) for k in keys} for m, values in proposed.items()}
        keys = [k for k in keys if any(p[k] for p in pairs.values())]
        pairs = {m: {k: p[k] for k in keys} for m, p in pairs.items()}
        layout = fg.fgOTLayout(self.source.font)
        body = layout.get_feature('kern') if self.source.has_kern_feature() else ''
        prefix = layout.get_prefix()
        names = [g.name for g in self.source.font.glyphs]
        # Compile every master's proposal before accepting a review plan.
        for m, values in pairs.items():
            text_kern.merge(text_kern.resolve(prefix, self.parameter_values[m]),
                            text_kern.resolve(body, self.parameter_values[m]), names, values)
        snap = Snapshot(self.source.master_names)
        snap.planned, snap.previous_plan = True, self.review_plan
        self.review_plan = {'pairs': pairs, 'prefix': prefix, 'body': body,
                            'parameters': self.parameter_values, 'metadata': self.master_info,
                            'names': names, 'token': self.token, 'engine': engine,
                            'accepted': sorted(set(accepted)), 'axis_reference': self.axis_reference}
        self.applied_pairs = {k: {m: p[k] for m, p in pairs.items()} for k in keys}
        self.snapshot, self.undo_token, self.token = snap, self.token, None
        return len(keys)

    def export_variable(self, path, evidence=None):
        self._check_options()
        if not self.review_plan:
            raise RuntimeError('Сначала подготовьте MM/VF план')
        if state(self.source, self.master) != self.review_plan['token']:
            raise RuntimeError('Шрифт изменён после расчёта. Экспорт заблокирован: пересчитайте.')
        if not self.review_plan['metadata'].get('axes'):
            raise RuntimeError('Нет осей вариаций: используйте экспорт статических мастеров')
        from .variable_kern import export_variable
        return export_variable(self.source, self.review_plan, path, self.workdir, self.lifecycle, evidence,
                               lambda: state(self.source, self.master) == self.review_plan['token'])

    def export_masters(self, path):
        self._check_options()
        if not self.review_plan:
            raise RuntimeError('Сначала подготовьте MM/VF план')
        if state(self.source, self.master) != self.review_plan['token']:
            raise RuntimeError('Шрифт изменён после расчёта. Экспорт заблокирован: пересчитайте.')
        from .variable_kern import export_masters
        return export_masters(self.source, self.review_plan, path, self.workdir, self.lifecycle,
                              lambda: state(self.source, self.master) == self.review_plan['token'])

    def _restore(self, snap):
        if snap.text_kern is not None:
            import fontgate as fg
            fg.fgOTLayout(self.source.font).set_feature('kern', snap.text_kern)
        for a, b in snap.added_pairs:
            kern = self.source.package.kerning(self.master)
            if OldKerning(*self.source.kerning_now(self.master)).has(a, b):
                kern.remove(((a, False), (b, False)))
        self.source.restore(snap)

    def _write_text_kern(self, text):
        import fontgate as fg
        fg.fgOTLayout(self.source.font).set_feature('kern', text)


def check(response):
    if response.get('success') is False or response.get('status') in ('error', 'failed') or response.get('isError'):
        raise RuntimeError(stable(response))
    return response


def parameters(info):
    result = {}
    for item in info['masters']:
        master = item['fontMaster']
        values = {v['name']: v.get('value', 0) for v in master.get('variables', [])}
        values.update({key: master.get(field, 0) for key, field in
                       [('x_height', 'xHeight'), ('caps_height', 'capsHeight'),
                        ('ascender', 'ascender'), ('descender', 'descender')]})
        result[master['name']] = values
    return result
