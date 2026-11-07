"""Additive FEA kerning. Author text is never parsed-and-rewritten.

feaLib is used for coverage and compilation preflight. Unrecognised constructs
fail closed. Contextual positioning conservatively protects involved glyphs.
"""
import hashlib
from io import StringIO
import json
import math
import uuid
import ast
import operator
import re


def resolve(text, parameters):
    """Resolve FontLab ${arithmetic} for analysis only; never rewrite author code."""
    binary = {ast.Add: operator.add, ast.Sub: operator.sub,
              ast.Mult: operator.mul, ast.Div: operator.truediv}

    def evaluate(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.Name) and node.id in parameters:
            return parameters[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in binary:
            return binary[type(node.op)](evaluate(node.left), evaluate(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return evaluate(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        raise ValueError('Неизвестный параметр или выражение kern')

    def substitute(match):
        value = evaluate(ast.parse(match.group(1), mode='eval').body)
        if not math.isfinite(value):
            raise ValueError('Нечисловой параметр kern')
        return str(round(value))
    # FEA strings and comments are literal data, including ${...} inside them.
    pieces, i, quoted = [], 0, False
    while i < len(text):
        ch = text[i]
        if quoted and ch == '\\' and i + 1 < len(text):
            pieces.append(text[i:i + 2]); i += 2; continue
        if ch == '"':
            quoted = not quoted
        if not quoted and ch == '#':
            end = text.find('\n', i)
            end = len(text) if end < 0 else end
            pieces.append(text[i:end]); i = end; continue
        if not quoted and text.startswith('${', i):
            match = re.match(r'\$\{([^{}]+)\}', text[i:])
            if match is None or len(match.group(1)) > 500:
                raise ValueError('Некорректное выражение kern')
            pieces.append(substitute(match)); i += len(match.group(0)); continue
        pieces.append(ch); i += 1
    return ''.join(pieces)


def wrapped(body):
    from fontTools.feaLib.lexer import Lexer
    tokens = [value for kind, value, _ in Lexer(body, '<kern>') if kind != Lexer.COMMENT]
    depth = 0
    for i, value in enumerate(tokens):
        if depth == 0 and value == 'feature' and tokens[i + 1:i + 3] == ['kern', '{']:
            return True
        if value == '{':
            depth += 1
        elif value == '}':
            depth -= 1
    return False


def document(prefix, body):
    return prefix + '\n' + (body if wrapped(body) else 'feature kern {\n' + body + '\n} kern;\n')


class Coverage:
    def __init__(self):
        self.pairs = []
        self.glyphs = set()

    def has(self, left, right):
        return (left in self.glyphs or right in self.glyphs or
                any(left in a and right in b for a, b in self.pairs))


def coverage(prefix, body, glyph_names):
    from fontTools.feaLib.parser import Parser
    tree = Parser(StringIO(document(prefix, body)), glyphNames=glyph_names,
                  followIncludes=False).parse()
    result = Coverage()
    visited = set()
    allowed = {'Comment', 'GlyphClassDefinition', 'MarkClassDefinition',
               'ValueRecordDefinition', 'ScriptStatement', 'LanguageStatement',
               'LanguageSystemStatement', 'SubtableStatement'}

    def glyphs(expressions):
        return {g for expression in expressions for g in expression.glyphSet()}

    def reject_includes(block):
        for statement in getattr(block, 'statements', []):
            if type(statement).__name__ == 'IncludeStatement':
                raise RuntimeError('kern содержит include(): сначала нужен самостоятельный текст фичи')
            reject_includes(statement)

    reject_includes(tree)

    def visit(block):
        if id(block) in visited:
            return
        visited.add(id(block))
        flag = 0
        for statement in block.statements:
            kind = type(statement).__name__
            if kind == 'FeatureBlock':
                if statement.name == 'kern':
                    visit(statement)
            elif kind == 'LookupBlock':
                visit(statement)
            elif kind == 'LookupReferenceStatement':
                visit(statement.lookup)
            elif kind == 'LookupFlagStatement':
                flag = statement.value
                if statement.markAttachment or statement.markFilteringSet:
                    flag = 1
            elif kind == 'PairPosStatement':
                a, b = set(statement.glyphs1.glyphSet()), set(statement.glyphs2.glyphSet())
                if flag:
                    result.glyphs.update(a | b)
                else:
                    result.pairs.append((a, b))
            elif kind == 'SinglePosStatement':
                result.glyphs.update(glyphs([g for g, _ in statement.pos] + statement.prefix + statement.suffix))
            elif kind == 'ChainContextPosStatement':
                result.glyphs.update(glyphs(statement.prefix + statement.glyphs + statement.suffix))
                for lookups in statement.lookups:
                    for lookup in lookups or []:
                        visit(lookup)
            elif kind == 'IgnorePosStatement':
                for prefix_, inputs, suffix_ in statement.chainContexts:
                    result.glyphs.update(glyphs(prefix_ + inputs + suffix_))
            elif kind not in allowed:
                raise RuntimeError('Неподдерживаемая конструкция kern: ' + kind)

    # Prefix lookups are analysed only when referenced by kern; unrelated GSUB
    # definitions must not block a valid kerning feature.
    for statement in tree.statements:
        kind = type(statement).__name__
        if kind == 'FeatureBlock' and statement.name == 'kern':
            visit(statement)
        elif kind == 'IncludeStatement':
            raise RuntimeError('kern содержит include(): сначала нужен самостоятельный текст фичи')
    return result


def compile_layout(prefix, body, glyph_names):
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
    from fontTools.ttLib import TTFont
    font = TTFont()
    font.setGlyphOrder(list(glyph_names))
    addOpenTypeFeaturesFromString(font, document(prefix, body))
    # Serialise/read back GPOS so defaults and counts are canonical.
    if 'GPOS' in font:
        from fontTools.ttLib import newTable
        binary = font['GPOS'].compile(font)
        table = newTable('GPOS')
        table.decompile(binary, font)
        return table.table
    return None


def layout_signatures(table):
    """Lookup graph signatures independent of indices shifted by new lookups."""
    if table is None:
        return [], {}
    if getattr(table, 'FeatureVariations', None):
        raise RuntimeError('Вариационные условия kern пока не поддержаны')
    lookups = table.LookupList.Lookup
    cache = {}

    def lookup(index, seen=()):
        if index in seen:
            raise RuntimeError('Циклические ссылки lookup')
        if index not in cache:
            raw = canonical(lookups[index], seen + (index,))
            cache[index] = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        return cache[index]

    def canonical(value, seen):
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, (list, tuple)):
            return [canonical(x, seen) for x in value]
        fields = value if isinstance(value, dict) else vars(value)
        return {str(k): lookup(v, seen) if k == 'LookupListIndex' else canonical(v, seen)
                for k, v in fields.items() if not str(k).startswith('_')}

    signatures = [lookup(i) for i in range(len(lookups))]
    registrations = {}
    features = table.FeatureList.FeatureRecord
    for script in table.ScriptList.ScriptRecord:
        languages = [('dflt', script.Script.DefaultLangSys)] + [
            (r.LangSysTag, r.LangSys) for r in script.Script.LangSysRecord]
        for language, system in languages:
            if system is None:
                continue
            indices = list(system.FeatureIndex)
            if system.ReqFeatureIndex != 0xFFFF:
                indices.append(system.ReqFeatureIndex)
            for index in indices:
                f = features[index]
                key = (script.ScriptTag, language, f.FeatureTag,
                       index == system.ReqFeatureIndex)
                registrations[key] = [signatures[i] for i in f.Feature.LookupListIndex]
    return signatures, registrations


def merge(prefix, body, glyph_names, proposed):
    names = list(glyph_names)
    owned = coverage(prefix, body, names)
    accepted = {}
    for pair, value in proposed.items():
        a, b = pair.split('|')
        if a not in names or b not in names or not math.isfinite(value):
            raise ValueError('Недопустимая пара или число: ' + pair)
        if value and not owned.has(a, b):
            accepted[pair] = round(value)
    if not accepted:
        return body, {}, owned
    rules = ['  pos \\%s \\%s %d;' % (*k.split('|'), v) for k, v in sorted(accepted.items())]
    return append_rules(prefix, body, names, rules), accepted, owned


def append_rules(prefix, body, names, rules, resolver=lambda code: code, label=None):
    label = label or 'AK9_' + uuid.uuid4().hex[:16]
    generated = ('# Autokerner 9: added missing pairs; author text follows unchanged.\n'
                 'lookup %s {\n  lookupflag 0;\n%s\n} %s;\n' % (label, '\n'.join(rules), label))
    full = wrapped(resolver(body))
    # Native FontLab export needs complete feature blocks. A body supplied by
    # another script is enclosed without rewriting any of its author text.
    merged = ('feature kern {\n' + generated + '\n} kern;\n' + body if full else
              'feature kern {\n' + generated + body + '\n} kern;\n')
    original_signatures, before = layout_signatures(compile_layout(resolver(prefix), resolver(body), names))
    new_signatures, after = layout_signatures(compile_layout(resolver(prefix), resolver(merged), names))
    added = set(new_signatures) - set(original_signatures)
    if len(added) != 1:
        raise RuntimeError('Не удалось изолировать добавленный lookup kern')
    # Add explicit references for authored language systems excluding defaults.
    missing = [key for key, refs in before.items() if key[2] == 'kern'
               and not added.intersection(after.get(key, []))]
    if missing:
        references = ''
        for script, language, _, _ in missing:
            option = '' if language == 'dflt' else ' exclude_dflt'
            references += '\nscript %s;\nlanguage %s%s;\nlookup %s;\n' % (script, language, option, label)
        merged += '\nfeature kern {\n' + references + '\n} kern;\n'
        new_signatures, after = layout_signatures(compile_layout(resolver(prefix), resolver(merged), names))
    if not set(original_signatures).issubset(new_signatures):
        raise RuntimeError('Компиляция изменила авторский lookup; запись отменена')
    for key, references in before.items():
        actual = after.get(key, [])
        if [x for x in actual if x not in added] != references:
            raise RuntimeError('Изменились авторские правила языка %s/%s; запись отменена' % key[:2])
        if key[2] == 'kern' and len([x for x in actual if x in added]) != 1:
            raise RuntimeError('Добавленный kern не зарегистрирован ровно один раз')
    return merged
