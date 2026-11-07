"""Exact avar v1 provenance for imported one-axis weight VFs.

Restore a reference table only while the editor still has its import-rounded
mapping. Authored axis edits always win. No outlines or positioning are copied.
"""
import copy
import hashlib
import json
import struct
from pathlib import Path

LIB_KEY = 'org.autokerner9.originalAvar.v1'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def embedded_value(package):
    values = package.packageLib
    if LIB_KEY not in values:
        return None
    value = values[LIB_KEY]
    if not isinstance(value,str):
        raise RuntimeError('Повреждены встроенные данные avar в VFJ; экспорт остановлен')
    return value


def _validate_bytes(reference):
    raw = bytes.fromhex(reference['avar_hex'])
    if hashlib.sha256(raw).hexdigest() != reference['avar_sha256']:
        raise ValueError('avar checksum')
    major, minor, reserved, count, points = struct.unpack('>5H', raw[:10])
    if (major, minor, reserved, count) != (1, 0, 0, 1) or len(raw) != 10 + 4 * points:
        raise ValueError('avar structure')
    pairs = [struct.unpack('>hh', raw[i:i+4]) for i in range(10, len(raw), 4)]
    if not all(p in pairs for p in [(-16384,-16384),(0,0),(16384,16384)]):
        raise ValueError('avar anchors')
    if any(a[0] >= b[0] or a[1] >= b[1] for a,b in zip(pairs,pairs[1:])):
        raise ValueError('avar monotonicity')
    return raw


def decode_embedded(blob):
    try:
        envelope = json.loads(blob)
        payload = envelope['payload']
        if envelope['schema'] != 1 or hashlib.sha256(canonical(payload).encode()).hexdigest() != envelope['sha256']:
            raise ValueError('payload checksum/schema')
        ref = payload['reference']
        _validate_bytes(ref)
        if len(ref['axes_snapshot']) != 1 or ref['axes_snapshot'][0]['tag'] != 'wght':
            raise ValueError('axis scope')
        if type(payload['restore_allowed']) is not bool:
            raise ValueError('restore flag')
        canonical(payload['saved_axes'])
        return payload
    except (ValueError, TypeError, KeyError, struct.error) as error:
        raise RuntimeError('Повреждены встроенные данные avar в VFJ; экспорт остановлен') from error


def encode_embedded(reference, axes, restore_allowed=True):
    ref = {k: copy.deepcopy(reference[k]) for k in
           ('avar_hex','avar_sha256','axes_snapshot','fvar_limits','master_locations')}
    ref['source_sha256'] = reference.get('file_sha256', reference.get('source_sha256'))
    payload = {'reference': ref, 'saved_axes': copy.deepcopy(axes), 'restore_allowed': restore_allowed}
    blob = canonical({'schema':1, 'payload':payload,
                      'sha256':hashlib.sha256(canonical(payload).encode()).hexdigest()})
    decode_embedded(blob)
    return blob


def effective_axes(package):
    axes = native_axes(package)
    blob = embedded_value(package)
    if blob is not None:
        payload = decode_embedded(blob)
        # VFJ rounds axis numbers. Retain an explicitly saved authored map in
        # our own metadata, only while the reopened editor matches that save.
        if not payload['restore_allowed']:
            saved = payload['saved_axes']
            rounded = copy.deepcopy(saved)
            for a in rounded:
                a['axisGraph'] = [(round(k,1),round(v,1)) for k,v in a['axisGraph']]
            if canonical(axes) == canonical(rounded):
                return copy.deepcopy(saved)
    return axes


def reference_for(source, metadata, axes):
    blob = embedded_value(source.package)
    if blob is None:
        return capture(source.font.path, metadata, axes)
    payload = decode_embedded(blob)
    ref = payload['reference']
    if not payload['restore_allowed'] or canonical(axes) != canonical(ref['axes_snapshot']):
        return {'status':'authored', 'reason':'В VFJ сохранена авторская шкала; исходная avar не подставляется'}
    return dict(copy.deepcopy(ref), status='ready', origin='vfj')


def native_axes(package):
    return [{'tag': str(a.tag), 'shortName': str(a.shortName),
             'minimum': float(a.minimal), 'default': float(a.default), 'maximum': float(a.maximum),
             'designMinimum': float(a.designMin), 'designDefault': float(a.designDef),
             'designMaximum': float(a.designMax),
             'axisGraph': sorted((float(k), float(v)) for k, v in a.map.items())}
            for a in package.axes]


def with_native_axes(metadata, axes):
    """Do not round newly authored mappings through VFJ's decimal serializer."""
    result = copy.deepcopy(metadata)
    by_tag = {a['tag']: a for a in axes}
    for item in result.get('axes', []):
        native = by_tag[item['tag']]
        for key in ('minimum', 'default', 'maximum', 'designMinimum', 'designMaximum'):
            item[key] = native[key]
        item['axisGraph'] = {str(k): v for k, v in native['axisGraph']}
    return result


def capture(path, metadata, axes):
    """Pure data only; no editor wrappers survive into the export plan."""
    from fontTools.ttLib import TTFont
    from fontTools.varLib.models import normalizeValue, piecewiseLinearMap
    result = {'status': 'unavailable', 'reason': 'Нет исходного TTF с avar v1'}
    path = Path(str(path))
    if path.suffix.lower() != '.ttf' or not path.is_file():
        return result
    # Deliberately narrow scope: the independently verified one-axis route.
    if len(axes) != 1 or axes[0]['tag'] != 'wght':
        return dict(result, reason='Точное сохранение avar проверено только для одной оси wght')
    with TTFont(path) as font:
        if 'avar' not in font or font['avar'].majorVersion != 1 or 'fvar' not in font:
            return result
        if len(font['fvar'].axes) != 1 or font['fvar'].axes[0].axisTag != 'wght':
            return result
        a = font['fvar'].axes[0]; native = axes[0]
        limits = (a.minValue, a.defaultValue, a.maxValue)
        if tuple(native[k] for k in ('minimum', 'default', 'maximum')) != limits or (
                tuple(native[k] for k in ('designMinimum', 'designDefault', 'designMaximum')) != limits):
            return {'status': 'authored', 'reason': 'Диапазон или default оси изменён; сохранена шкала автора'}
        def denormalize(x):
            return a.defaultValue + x * ((a.defaultValue-a.minValue) if x < 0 else (a.maxValue-a.defaultValue))
        segments = font['avar'].segments['wght']
        expected = {round(denormalize(y), 1): denormalize(x) for x, y in segments.items()}
        if dict(native['axisGraph']) != expected:
            return {'status': 'authored', 'reason': 'Шкала отличается от импортированной; сохранена шкала автора'}
        # Reject degenerate/non-monotone maps rather than guessing their inverse.
        ordered = sorted(segments.items())
        if any(y >= z for (_, y), (_, z) in zip(ordered, ordered[1:])):
            return dict(result, reason='Немонотонная исходная avar')
        # An interior default shifted by import rounding would change the design
        # origin of gvar/GPOS. Do not restore only avar in that unsupported case.
        graph = {v: k for k, v in native['axisGraph']}
        if piecewiseLinearMap(a.defaultValue, graph) != a.defaultValue:
            return dict(result, reason='Изменён design default оси')
        raw = font.reader['avar']
        return {'status': 'ready', 'path': str(path.resolve()),
                'file_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'avar_hex': raw.hex(), 'avar_sha256': hashlib.sha256(raw).hexdigest(),
                'axes_snapshot': copy.deepcopy(axes),
                'fvar_limits': list(limits),
                'master_locations': [normalizeValue(m['fontMaster'].get('location', {}).get(
                    native['shortName'], a.defaultValue), limits)
                    for m in metadata['masters']]}


def verify_reference(reference, axes):
    if not reference or reference['status'] != 'ready':
        return
    if canonical(axes) != canonical(reference['axes_snapshot']):
        raise RuntimeError('Шкала оси изменена после расчёта; исходная avar не подставлена')
    if reference.get('origin') != 'vfj':
        path = Path(reference['path'])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != reference['file_sha256']:
            raise RuntimeError('Исходный TTF изменён или недоступен; пересчитайте для сохранения avar')
    try:
        _validate_bytes(reference)
    except (ValueError,struct.error,KeyError) as error:
        raise RuntimeError('Повреждён снимок исходной avar') from error


def restore(font, reference, axes):
    """Called before freezing VF tables; byte identity is checked after save."""
    if not reference or reference['status'] != 'ready':
        return {k: v for k, v in (reference or {'status': 'unavailable'}).items() if k in ('status', 'reason')}
    verify_reference(reference, axes)
    actual = [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in font['fvar'].axes]
    if actual != [('wght', *reference['fvar_limits'])]:
        raise RuntimeError('Оси экспортируемого VF не совпали с исходной avar')
    raw = bytes.fromhex(reference['avar_hex'])
    from fontTools.ttLib.tables.DefaultTable import DefaultTable
    table = DefaultTable('avar'); table.data = raw; font['avar'] = table
    return {'status': 'preserved', 'avar_sha256': reference['avar_sha256'],
            'origin': reference.get('origin','ttf')}


def save_project(source, target):
    """Save a new portable VFJ; restore the editor's lib even on save failure."""
    import shutil
    import tempfile
    import fontpr
    from .temporary import checked
    target = Path(target)
    if target.suffix.lower() != '.vfj':
        raise ValueError('Для проекта нужен файл .vfj')
    if target.exists():
        raise FileExistsError('Файл уже существует; выберите новое имя VFJ')
    axes = effective_axes(source.package)
    blob = embedded_value(source.package)
    if blob is not None:
        previous = decode_embedded(blob)
        ref = previous['reference']
        allowed = previous['restore_allowed'] and canonical(axes) == canonical(ref['axes_snapshot'])
    else:
        info = with_native_axes(fontpr.get_font_info(font_id=source.package.fgId), axes)
        ref = capture(source.font.path, info, axes)
        if ref['status'] != 'ready':
            raise RuntimeError('Нельзя сохранить исходную avar: '+ref.get('reason','нет исходного TTF'))
        verify_reference(ref,axes)
        allowed = True
    value = encode_embedded(ref,axes,allowed)
    old = dict(source.package.packageLib)
    with tempfile.TemporaryDirectory(prefix='.ak9-vfj-', dir=str(target.parent)) as scratch:
        staged = Path(scratch)/'project.vfj'
        try:
            source.package.packageLib = dict(old, **{LIB_KEY:value})
            checked(fontpr.save_font(font_id=source.package.fgId,path=str(staged),format='vfj',overwrite=False))
        finally:
            source.package.packageLib = old
        data = json.loads(staged.read_text(encoding='utf-8'))
        if data['font'].get('lib',{}).get(LIB_KEY) != value:
            raise RuntimeError('FontLab не сохранил встроенную avar; VFJ не создан')
        created = False
        try:
            with target.open('xb') as output, staged.open('rb') as incoming:
                created = True
                shutil.copyfileobj(incoming,output)
        except Exception:
            if created:target.unlink(missing_ok=True)
            raise
    return {'file':str(target),'avar_sha256':ref['avar_sha256'],
            'restore_allowed':allowed,'source_unchanged':True,'ttf_required_after_reopen':False}
