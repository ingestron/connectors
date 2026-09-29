"""ODCS v3.1 library quality rules evaluated on staged Parquet before commit (PB-063).

Mirrors @ingestron/core rule identities: explicit rules keep their `id`, otherwise
`table[.column].metric`; `primaryKey: true` implies `table.column.key-not-null` and
`table.key-unique` unless the contract states its own rule. Only counts are reported:
no row values leave this module. sql, custom and text rules are not evaluated here.
"""
import re

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

METRICS = ('nullValues', 'missingValues', 'invalidValues', 'duplicateValues', 'rowCount')
OPERATORS = ('mustBe', 'mustNotBe', 'mustBeGreaterThan', 'mustBeGreaterOrEqualTo',
             'mustBeLessThan', 'mustBeLessOrEqualTo', 'mustBeBetween', 'mustNotBeBetween')


class QualityFailed(ValueError):
    def __init__(self, results):
        self.results = results
        super().__init__('Quality rules failed; nothing was committed')


def _rule(rule, table, column=None):
    if not isinstance(rule, dict) or rule.get('type', 'library') != 'library':
        return None
    metric = rule.get('metric')
    if metric not in METRICS:
        raise ValueError('Unsupported library quality metric')
    present = [o for o in OPERATORS if o in rule]
    if len(present) != 1:
        raise ValueError('A library quality rule needs exactly one comparison')
    where = table + ('.' + column if column else '')
    return {'id': str(rule.get('id') or f'{where}.{metric}'), 'table': table,
            **({'column': column} if column else {}), 'metric': metric,
            'operator': present[0], 'threshold': rule[present[0]],
            'arguments': rule.get('arguments') or {}, 'unit': rule.get('unit', 'rows'),
            'outcome': 'fail' if str(rule.get('severity', '')).lower() == 'error' else 'warn',
            'source': 'contract'}


def contract_rules(contract):
    rules = [r for r in (_rule(q, '*') for q in contract.get('quality') or []) if r]
    for obj in contract.get('schema') or []:
        table = str(obj.get('name', 'table'))
        rules += [r for r in (_rule(q, table) for q in obj.get('quality') or []) if r]
        keys = []
        for prop in obj.get('properties') or []:
            column = str(prop.get('name'))
            rules += [r for r in (_rule(q, table, column) for q in prop.get('quality') or []) if r]
            if prop.get('primaryKey') is True:
                keys.append(column)
        for column in keys:
            if not any(r['table'] == table and r.get('column') == column and r['metric'] == 'nullValues' for r in rules):
                rules.append({'id': f'{table}.{column}.key-not-null', 'table': table, 'column': column,
                              'metric': 'nullValues', 'operator': 'mustBe', 'threshold': 0,
                              'arguments': {}, 'unit': 'rows', 'outcome': 'fail', 'source': 'primary-key'})
        if keys and not any(r['table'] == table and 'column' not in r and r['metric'] == 'duplicateValues' for r in rules):
            rules.append({'id': f'{table}.key-unique', 'table': table, 'metric': 'duplicateValues',
                          'operator': 'mustBe', 'threshold': 0, 'arguments': {'properties': keys},
                          'unit': 'rows', 'outcome': 'fail', 'source': 'primary-key'})
    return rules


def _compare(operator, value, threshold):
    if operator in ('mustBeBetween', 'mustNotBeBetween'):
        if not (isinstance(threshold, list) and len(threshold) == 2):
            raise ValueError('Between comparisons need two bounds')
        inside = threshold[0] <= value <= threshold[1]
        return inside if operator == 'mustBeBetween' else not inside
    return {'mustBe': value == threshold, 'mustNotBe': value != threshold,
            'mustBeGreaterThan': value > threshold, 'mustBeGreaterOrEqualTo': value >= threshold,
            'mustBeLessThan': value < threshold, 'mustBeLessOrEqualTo': value <= threshold}[operator]


def _measure(rule, data):
    rows = data.num_rows
    metric, args = rule['metric'], rule['arguments']
    if metric == 'rowCount':
        return rows
    if metric == 'duplicateValues':
        columns = [rule['column']] if 'column' in rule else list(args.get('properties') or [])
        if not columns:
            raise ValueError('Table duplicateValues needs arguments.properties')
        subset = data.select(columns)
        if 'column' in rule:
            subset = subset.filter(pc.is_valid(subset.column(0)))
        return subset.num_rows - subset.group_by(columns).aggregate([]).num_rows
    column = data.column(rule['column'])
    if metric == 'nullValues':
        return column.null_count
    if metric == 'missingValues':
        missing = [v for v in args.get('missingValues', [None, '']) if v is not None]
        extra = pc.sum(pc.is_in(column, value_set=_values(column, missing))).as_py() if missing else 0
        return column.null_count + (extra or 0)
    valid = column.filter(pc.is_valid(column))
    if 'validValues' in args:
        return len(valid) - (pc.sum(pc.is_in(valid, value_set=_values(valid, args['validValues']))).as_py() or 0)
    pattern = re.compile(str(args['pattern']))
    return sum(1 for v in valid.to_pylist() if not pattern.fullmatch(str(v)))


def _values(column, values):
    # A listed value that cannot take the column type can never match a row.
    kept = []
    for value in values:
        try:
            pa.array([value], type=column.type)
        except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, ValueError, OverflowError):
            continue
        kept.append(value)
    return pa.array(kept, type=column.type)


def evaluate(contract, path, table_name):
    """Evaluate one contract's library rules against a staged Parquet file."""
    rules = contract_rules(contract)
    if not rules:
        return []
    data = pq.read_table(path)
    results = []
    for rule in rules:
        if rule['table'] not in ('*', table_name):
            continue
        value = _measure(rule, data)
        if rule['unit'] == 'percent' and rule['metric'] != 'rowCount':
            value = round(100 * value / data.num_rows, 4) if data.num_rows else 0
        results.append({'id': rule['id'], 'metric': rule['metric'], 'outcome': rule['outcome'],
                        'source': rule['source'], 'value': value,
                        'passed': _compare(rule['operator'], value, rule['threshold'])})
    return results
