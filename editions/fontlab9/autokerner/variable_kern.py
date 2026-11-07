"""Managed VF export: FontLab outlines, master-specific authored GPOS.

The editor document is never rewritten. Native export currently rebuilds kern;
we merge the GPOS/GDEF of real static exports with fontTools VariationMerger.
All copies close before the next opens. Output is published only after readback.
"""
import copy
from pathlib import Path
import shutil
import tempfile
import re

from .temporary import temporary_font
from . import text_kern, axis_map

COMPATIBLE_TT_PROFILE = 'Autokerner9 compatible TT'


def check_preservation_profile(definition):
    """Reject edited profiles instead of trusting a familiar profile name."""
    values = dict(line.split('=', 1) for line in definition.splitlines() if '=' in line)
    values = {k.strip(): v.strip() for k, v in values.items()}
    required = {'SetFormat.FileFormat': 'ttf', 'SetOutline.OutlineConversion': 'tt',
                'SetOutline.Round': 'none'}
    required.update({('SetOutline.' + key): 'False' for key in
                     ('CorrectDirection', 'RemoveOverlaps', 'RemoveLoops',
                      'NodesAtExtremesX', 'NodesAtExtremesY', 'CleanUp')})
    if any(values.get(k) != v for k, v in required.items()):
        raise RuntimeError('Профиль Autokerner9 compatible TT изменён: восстановите '
                           'профиль из resources перед экспортом VF')


def _native_export(identifier, directory, profile, plan=None, master=None):
    # A native wrapper retained by an exception traceback can outlive the copy
    # and crash FontLab during close. Collapse that traceback before exit.
    import traceback
    try:
        return _export_native_impl(identifier, directory, profile, plan, master)
    except Exception:
        error = traceback.format_exc()
    raise RuntimeError(error)


def _export_native_impl(identifier, directory, profile, plan=None, master=None):
    import fontlab as fl
    import fontgate as fg
    from PythonQt import QtCore, QtGui
    def output():
        return '\n'.join(str(w.toPlainText()) for w in QtGui.QApplication.allWidgets()
                         if str(w.objectName) == 'textOutput' and hasattr(w, 'toPlainText'))
    log_before = output()
    font = next(f for f in fl.AllFonts() if fl.flPackage(f).fgId == identifier)
    package = fl.flPackage(font)
    if plan is not None:
        values = plan['parameters'][master]
        layout = fg.fgOTLayout(font)
        # Resolve only in the disposable copy. Preserve original source bytewise.
        layout.set_prefix(text_kern.resolve(plan['prefix'], values))
        for tag in list(layout.keys()):
            layout.set_feature(tag, text_kern.resolve(layout.get_feature(tag), values))
        body = text_kern.resolve(plan['body'], values)
        rules = ['  pos \\%s \\%s %d;' % (*k.split('|'), v)
                 for k, v in sorted(plan['pairs'][master].items())]
        merged = text_kern.append_rules(layout.get_prefix(), body, plan['names'], rules) if rules else body
        layout.set_feature('kern', merged)
    settings = QtCore.QSettings()
    if profile == COMPATIBLE_TT_PROFILE:
        definitions = settings.value('profiles') or []
        if isinstance(definitions, str):
            definitions = [definitions]
        matching = [str(d) for d in definitions
                    if ('ProfileName = ' + profile) in str(d).splitlines()]
        if len(matching) != 1:
            raise RuntimeError('Импортируйте resources/Autokerner9-compatible-TT.fl_profile '
                               'через Файл → Профили экспорта перед экспортом VF')
        check_preservation_profile(matching[0])
    keys = ['export.profile', 'export.profiles']
    saved = {k: settings.value(k) for k in keys}
    try:
        settings.setValue('export.profile', profile)
        settings.setValue('export.profiles', [profile])
        control = fl.ExportControl(); control.load()
        control.profileName = profile
        if control.profileName != profile:
            raise RuntimeError('Профиль экспорта не установлен: %s. Импортируйте '
                               'resources/Autokerner9-compatible-TT.fl_profile через '
                               'Файл → Профили экспорта.' % profile)
        control.destinationFolder = str(directory)
        control.destinationMode = 3
        control.groupFamily = control.groupProfiles = False
        control.contentMode = 0
        package.update()
        fl.flItems.notifyPackageContentUpdated(package.id)
        fl.Update()
        fl.flWorkspace.instance().exportFont(package, control)
        QtGui.QApplication.processEvents()
    finally:
        for key, value in saved.items():
            settings.setValue(key, value)
    files = list(directory.rglob('*.otf')) + list(directory.rglob('*.ttf'))
    log_after = output()
    fresh = log_after[len(log_before):] if log_after.startswith(log_before) else log_after
    if any(message in fresh.lower() for message in ('fea compiler error', 'features compilation failed',
                                                    'ошибка в данных функций', "couldn't merge")):
        raise RuntimeError('FontLab сообщил об ошибке компиляции; неполный экспорт отклонён:\n' + fresh[-2500:])
    if len(files) != 1:
        raise RuntimeError('FontLab не выдал ровно один файл: проверьте журнал экспорта')
    return files[0]


def locations(metadata, font):
    """Design coordinates normalized after axis mapping, as GPOS VarStore expects."""
    from fontTools.varLib.models import normalizeLocation, piecewiseLinearMap
    axes = metadata.get('axes', [])
    if 'avar' in font and font['avar'].majorVersion >= 2:
        raise RuntimeError('Экспорт kern с avar v2 пока не проверен')
    tags = [a.axisTag for a in font['fvar'].axes]
    if set(tags) != {a['tag'] for a in axes}:
        raise RuntimeError('Оси VF не совпали с исходником')
    ranges = {}
    for axis in axes:
        # VFJ stores design -> user coordinates, opposite to avar's mapping.
        graph = {float(v): float(k) for k, v in axis.get('axisGraph', {}).items()}
        if len(graph) != len(axis.get('axisGraph', {})):
            raise RuntimeError('Неоднозначное отображение координат оси')
        default = piecewiseLinearMap(axis['default'], graph) if graph else axis['default']
        ranges[axis['tag']] = (axis.get('designMinimum', axis['minimum']), default,
                               axis.get('designMaximum', axis['maximum']))
    result = []
    for record in metadata['masters']:
        master = record['fontMaster']
        location = master.get('location', {})
        result.append(normalizeLocation({a['tag']: location.get(a['shortName'], ranges[a['tag']][1])
                                         for a in axes}, ranges))
    return tags, result


def merge_positioning(variable, masters, metadata):
    from fontTools.varLib.models import VariationModel
    from fontTools.varLib.merger import VariationMerger
    from fontTools.ttLib import newTable
    from fontTools.ttLib.tables import otTables
    tags, coords = locations(metadata, variable)
    model = VariationModel(coords, axisOrder=tags)
    default = coords.index({}) if {} in coords else next(i for i, c in enumerate(coords) if not any(c.values()))
    order = variable.getGlyphOrder()
    def unicode_ids(font):
        return {u: font.getGlyphID(name) for table in font['cmap'].tables if table.isUnicode()
                for u, name in getattr(table, 'cmap', {}).items()}
    unicode_gids = unicode_ids(variable)
    encoded = set(unicode_gids.values())
    for font in masters:
        old = font.getGlyphOrder()
        if len(old) != len(order) or unicode_ids(font) != unicode_gids:
            raise RuntimeError('Glyph ID / Unicode статического мастера и VF не совпали')
        # FontLab may choose different names for a multiply-encoded glyph
        # (micro vs mu, Delta vs increment). Shared Unicode->GID proves identity.
        if any(a != b and i not in encoded for i, (a, b) in enumerate(zip(old, order))):
            raise RuntimeError('Неоднозначное соответствие не закодированных глифов')
        if old != order:
            font.setGlyphOrder(order)
            # Decode positioning with the VF names, preserving actual glyph IDs.
            for tag in ('GPOS', 'GDEF'):
                if tag in font:
                    table = newTable(tag); table.decompile(font.reader[tag], font); font[tag] = table
    reference = (variable['GDEF'].table if 'GDEF' in variable else
                 masters[default]['GDEF'].table if 'GDEF' in masters[default] else None)
    gsub_dependency = _gsub_gdef_signature(variable, reference)
    # Some native static exports encode an empty GDEF as v1.0, others as v1.2.
    # Missing and explicit None are the same optional field, not different data.
    definitions = [f['GDEF'].table for f in masters if 'GDEF' in f]
    if len(definitions) == len(masters):
        version = max(g.Version for g in definitions)
        if version <= 0x10002:
            for g in definitions:
                g.Version = version
                if version >= 0x10002 and not hasattr(g, 'MarkGlyphSetsDef'):
                    g.MarkGlyphSetsDef = None
    # Start with authored static layout, never with FontLab's rebuilt VF kern.
    for tag in ('GPOS', 'GDEF'):
        if tag in masters[default]:
            variable[tag] = copy.deepcopy(masters[default][tag])
        elif tag in variable:
            del variable[tag]
    merger = VariationMerger(model, tags, variable)
    merger.mergeTables(variable, masters, ['GPOS', 'GDEF'])
    store = merger.store_builder.finish()
    if store:
        if 'GDEF' not in variable:
            table = variable['GDEF'] = newTable('GDEF')
            table.table = otTables.GDEF()
            table.table.Version = 0x10003
            for name in ('GlyphClassDef', 'AttachList', 'LigCaretList', 'MarkAttachClassDef', 'MarkGlyphSetsDef'):
                setattr(table.table, name, None)
        gdef = variable['GDEF'].table
        gdef.Version = max(gdef.Version, 0x10003)
        gdef.VarStore = store
        indices = store.optimize()
        done = set()
        gdef.remap_device_varidxes(indices, done=done)
        if 'GPOS' in variable:
            variable['GPOS'].table.remap_device_varidxes(indices, done=done)
    if _gsub_gdef_signature(variable, variable['GDEF'].table if 'GDEF' in variable else None) != gsub_dependency:
        raise RuntimeError('Изменились классы GDEF, используемые авторским GSUB; экспорт отменён')
    return coords


def _gsub_gdef_signature(font, gdef):
    """Unchanged GSUB bytes also require unchanged referenced GDEF classes/sets."""
    result = {}
    if 'GSUB' not in font:
        return result
    for lookup in font['GSUB'].table.LookupList.Lookup:
        flag = lookup.LookupFlag
        for mask, field in ((0xE, 'GlyphClassDef'), (0xFF00, 'MarkAttachClassDef')):
            if flag & mask:
                value = getattr(gdef, field, None)
                result[field] = dict(value.classDefs) if value is not None else None
        if flag & 0x10:
            index = lookup.MarkFilteringSet
            sets = getattr(gdef, 'MarkGlyphSetsDef', None)
            result['filter-%d' % index] = (tuple(sets.Coverage[index].glyphs)
                                          if sets is not None and index < len(sets.Coverage) else None)
    return result


def _base_from_masters(masters, metadata, target):
    """Fallback when native VF export cannot merge its own GDEF versions."""
    from fontTools.designspaceLib import DesignSpaceDocument,AxisDescriptor,SourceDescriptor,InstanceDescriptor
    from fontTools.varLib import build
    order = masters[0].getGlyphOrder()
    if any(f.getGlyphOrder() != order for f in masters):
        raise RuntimeError('Имена/порядок статических мастеров различаются; резервная сборка отменена')
    # varLib can warn and omit incompatible gvar deltas. Make this a hard error
    # before building, rather than silently delivering a partly static font.
    for name in order:
        shapes = [f['glyf'][name] for f in masters]
        if any(g.isComposite() != shapes[0].isComposite() for g in shapes):
            raise RuntimeError('Несовместимый тип контуров: ' + name)
        if shapes[0].isComposite():
            signatures = [[(c.glyphName, c.getComponentInfo()[1][:4]) for c in g.components] for g in shapes]
        else:
            signatures = [(g.numberOfContours, tuple(g.getCoordinates(f['glyf'])[1]),
                           tuple(flag & 1 for flag in g.getCoordinates(f['glyf'])[2]))
                          for g, f in zip(shapes, masters)]
        if any(s != signatures[0] for s in signatures):
            raise RuntimeError('Несовместимые мастера глифа: ' + name)
    if any(('GSUB' in f) != ('GSUB' in masters[0]) for f in masters):
        raise RuntimeError('GSUB различается между мастерами; безопасный резервный экспорт невозможен')
    if 'GSUB' in masters[0] and any(f.reader['GSUB'] != masters[0].reader['GSUB'] for f in masters):
        raise RuntimeError('GSUB различается между мастерами; безопасный резервный экспорт невозможен')
    doc = DesignSpaceDocument()
    axes = metadata['axes']
    for item in axes:
        axis = AxisDescriptor(); axis.name = item['name']; axis.tag = item['tag']
        axis.minimum, axis.default, axis.maximum = item['minimum'], item['default'], item['maximum']
        axis.map = sorted((float(v), float(k)) for k, v in item.get('axisGraph', {}).items())
        doc.addAxis(axis)
    for font, record in zip(masters, metadata['masters']):
        item = record['fontMaster']; source = SourceDescriptor()
        source.name = item['name']; source.font = font
        source.location = {a['name']: item.get('location', {}).get(a['shortName'], doc.axes[i].map_forward(a['default']))
                           for i, a in enumerate(axes)}
        doc.addSource(source)
    for item in metadata.get('instances', []):
        instance = InstanceDescriptor(); instance.styleName = item['name']
        instance.location = {a['name']: item.get('location', {}).get(a['shortName'], doc.axes[i].map_forward(a['default']))
                             for i, a in enumerate(axes)}
        doc.addInstance(instance)
    import logging
    warnings = []
    class Capture(logging.Handler):
        def emit(self, record):
            warnings.append(record.getMessage())
    handler = Capture(level=logging.WARNING)
    logger = logging.getLogger('fontTools.varLib'); logger.addHandler(handler)
    try:
        # IUP optimization permits lossy point deltas (default tolerance 0.5 U).
        # Preserve exact interpolation from the exported master coordinates.
        variable, _, _ = build(doc, exclude=['GPOS', 'GDEF'], optimize=False)
    finally:
        logger.removeHandler(handler)
    try:
        if warnings:
            raise RuntimeError('Резервная сборка выдала предупреждение; файл не создан: ' + '\n'.join(warnings))
        variable.save(target)
    finally:
        variable.close()


def export_variable(source, plan, target, workdir, events, evidence=None, validate=None):
    from fontTools.ttLib import TTFont
    target = Path(target)
    if target.suffix.lower() != '.ttf':
        raise ValueError('Для VF нужен файл .ttf')
    if target.exists():
        raise FileExistsError('Файл уже существует; выберите новое имя')
    if not plan['body'].strip():
        raise RuntimeError('Этот маршрут требует явную текстовую kern')
    identifier = source.package.fgId
    scratch = Path(tempfile.mkdtemp(prefix='.vf-export-', dir=str(workdir)))
    opened = []
    try:
        paths = []
        for i, record in enumerate(plan['metadata']['masters']):
            master = record['fontMaster']['name']
            directory = scratch / str(i); directory.mkdir()
            with temporary_font(identifier, master, scratch / 'copies', events) as copy_id:
                # Static production defaults can add extrema/clean each master
                # independently, breaking compatible quadratic contours. Use an
                # explicit preservation profile for the managed multi-master base.
                profile = COMPATIBLE_TT_PROFILE if len(plan['metadata']['masters']) > 2 else 'OpenType TT'
                paths.append(_native_export(copy_id, directory, profile, plan, master))
        masters = [TTFont(p) for p in paths]; opened.extend(masters)
        gdef_fields = [sorted(vars(f['GDEF'].table)) if 'GDEF' in f else [] for f in masters]
        gdef_versions = [f['GDEF'].table.Version if 'GDEF' in f else 0 for f in masters]
        directory = scratch / 'vf'; directory.mkdir()
        # Two-master native VF geometry is verified independently. For more
        # masters use the standard builder, avoiding the observed native GDEF
        # modal failure. Incompatible TT outlines are rejected, never repaired.
        native_base = len(masters) == 2 and len(set(gdef_versions)) == 1
        if native_base:
            route = 'FontLab Variable TT outlines + managed positioning'
            with temporary_font(identifier, plan['metadata']['defaultMaster'], scratch / 'copies', events) as copy_id:
                native = _native_export(copy_id, directory, 'Variable TT')
        else:
            route = 'varLib from native TT masters'
            native = directory / 'base.ttf'
            _base_from_masters(masters, plan['metadata'], native)
        variable = TTFont(native); opened.append(variable)
        if 'fvar' not in variable:
            raise RuntimeError('Нативный экспорт не является VF')
        # The native import can round axis mappings before VFJ sees them.
        # Recover only a proven, unchanged imported mapping from its source TTF.
        axis_result = axis_map.restore(variable, plan.get('axis_reference'), axis_map.native_axes(source.package))
        if evidence is not None:
            evidence = Path(evidence); evidence.mkdir()
            for i, path in enumerate(paths):
                shutil.copyfile(path, evidence / ('master-%d.ttf' % i))
            shutil.copyfile(native, evidence / ('native-vf.ttf' if native_base else 'base-vf.ttf'))
        retained = {tag: (variable.getTableData(tag) if tag == 'avar' and axis_result.get('status') == 'preserved'
                          else variable.reader[tag]) for tag in variable.keys()
                    if tag not in ('GlyphOrder', 'GPOS', 'GDEF', 'head')}
        # Decode a restored raw avar for the positioning preflight, then freeze
        # its original bytes again along with every non-positioning table.
        if axis_result.get('status') == 'preserved':
            from fontTools.ttLib import newTable
            restored = newTable('avar'); restored.decompile(variable.getTableData('avar'), variable)
            variable['avar'] = restored
        coords = merge_positioning(variable, masters, plan['metadata'])
        # feaLib/varLib may decompile unrelated tables. Freeze their original
        # bytes so saving cannot normalize name/cmap or rebuild any outlines.
        from fontTools.ttLib.tables.DefaultTable import DefaultTable
        positioning = {tag: variable.getTableData(tag) for tag in ('GPOS', 'GDEF') if tag in variable}
        for tag, binary in dict(retained, **positioning).items():
            table = DefaultTable(tag); table.data = binary; variable[tag] = table
        variable.recalcBBoxes = variable.recalcTimestamp = False
        candidate = scratch / 'candidate.ttf'
        variable.save(candidate)
        check = TTFont(candidate); opened.append(check)
        check.ensureDecompiled()
        for tag, binary in retained.items():
            if check.reader[tag] != binary:
                raise RuntimeError('Изменилась таблица вне позиционирования: ' + tag)
        if validate is not None and not validate():
            raise RuntimeError('Шрифт изменён во время экспорта. Файл не записан; пересчитайте.')
        axis_map.verify_reference(plan.get('axis_reference'), axis_map.native_axes(source.package))
        # Never overwrite a user's font. Exclusive creation also closes the race.
        created = False
        try:
            with target.open('xb') as stream, candidate.open('rb') as incoming:
                created = True
                shutil.copyfileobj(incoming, stream)
        except Exception:
            if created:
                target.unlink(missing_ok=True)
            raise
        return {'file': str(target), 'masters': list(plan['pairs']), 'locations': coords,
                'pairs': len(next(iter(plan['pairs'].values()))), 'source_unchanged': True,
                'mode': 'FontLab outlines + merged static GPOS/GDEF',
                'base_route': route, 'native_gdef_fields': gdef_fields, 'native_gdef_versions': gdef_versions,
                'axis_map': axis_result}
    finally:
        for font in reversed(opened):
            font.close()
        shutil.rmtree(scratch)


def export_masters(source, plan, target, workdir, events, validate):
    """Static TT masters for a multi-master project, including one without axes."""
    from fontTools.ttLib import TTFont
    target = Path(target)
    if target.exists():
        raise FileExistsError('Папка уже существует; выберите новое имя')
    scratch = Path(tempfile.mkdtemp(prefix='.mm-export-', dir=str(workdir)))
    written = []
    created = False
    try:
        paths = []
        for i, master in enumerate(plan['pairs']):
            directory = scratch / str(i); directory.mkdir()
            with temporary_font(source.package.fgId, master, scratch / 'copies', events) as identifier:
                path = _native_export(identifier, directory, 'OpenType TT', plan, master)
            with TTFont(path) as check:
                check.ensureDecompiled()
                if 'fvar' in check:
                    raise RuntimeError('Нативный экспорт мастера оказался вариативным')
            name = '%02d-%s.ttf' % (i + 1, re.sub(r'[^\w.-]', '_', master))
            paths.append((path, name))
        if not validate():
            raise RuntimeError('Шрифт изменён во время экспорта. Файлы не записаны; пересчитайте.')
        target.mkdir(); created = True
        try:
            for path, name in paths:
                output = target / name
                with output.open('xb') as stream, path.open('rb') as incoming:
                    written.append(output)
                    shutil.copyfileobj(incoming, stream)
        except Exception:
            for output in written:
                output.unlink(missing_ok=True)
            if created:
                target.rmdir()
            raise
        return {'directory': str(target), 'files': [str(p) for p in written], 'source_unchanged': True}
    finally:
        shutil.rmtree(scratch)
