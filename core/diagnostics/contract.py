"""Validation for the pinned NC event-v1 schema; no addon/runtime imports."""
import json
import math
import re
from datetime import datetime
from pathlib import Path

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / 'diagnostics/contracts/event-v1.schema.json').read_text(encoding='utf-8'))
_PRIVATE = re.compile(r'Bearer\s|(?:password|token|secret|authorization|code|api_key)\s*[=:]|[A-Za-z]:[\\/]|file://', re.I)

def _walk(value, schema, path, issues):
    def bad(rule):
        if len(issues) < 32: issues.append({'path': path, 'rule': rule})
    if 'anyOf' in schema:
        for choice in schema['anyOf']:
            attempt = []; _walk(value, choice, path, attempt)
            if not attempt: break
        else: bad('anyOf'); return
    kind = schema.get('type')
    matches = {'object': type(value) is dict, 'array': type(value) is list,
               'string': type(value) is str, 'null': value is None, 'boolean': type(value) is bool,
               'number': type(value) in (int, float) and math.isfinite(value),
               'integer': type(value) in (int, float) and math.isfinite(value) and int(value) == value}
    if kind and not matches[kind]: bad('type'); return
    if 'const' in schema and value != schema['const']: bad('const')
    if 'enum' in schema and value not in schema['enum']: bad('enum')
    if type(value) in (int,float):
        if value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf): bad('range')
    if type(value) is str:
        if len(value) < schema.get('minLength',0) or len(value) > schema.get('maxLength',100000): bad('length')
        if 'pattern' in schema and not re.search(schema['pattern'], value): bad('pattern')
        if schema.get('format') == 'date-time':
            try: datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%fZ')
            except ValueError: bad('format')
    if type(value) is dict:
        for key in schema.get('required',[]):
            if key not in value: bad('required.'+key)
        properties = schema.get('properties',{})
        for key, child in value.items():
            if key in properties: _walk(child, properties[key], path+'.'+key, issues)
            elif schema.get('additionalProperties') is False: bad('unknown_field')
    if type(value) is list:
        if len(value) < schema.get('minItems',0) or len(value) > schema.get('maxItems',100000): bad('items')
        for i, child in enumerate(value):
            if 'items' in schema: _walk(child,schema['items'],path+f'[{i}]',issues)
    for constraint in schema.get('allOf',[]): _walk(value,constraint,path,issues)
    if 'if' in schema:
        attempt=[]; _walk(value,schema['if'],path,attempt)
        if not attempt: _walk(value,schema['then'],path,issues)

def validate_event(value: object) -> list[dict[str, str]]:
    """Return safe field/rule errors, never rejected values or exception text."""
    try:
        encoded=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        if len(encoded.encode('utf-8')) > 16384: return [{'path':'$', 'rule':'size'}]
        def inspect(node,depth=0):
            if depth>12: raise ValueError()
            if type(node) is str and (node.startswith('/') or _PRIVATE.search(node) or any(ord(c)<32 for c in node)): raise ValueError()
            if type(node) is dict:
                for child in node.values(): inspect(child,depth+1)
            if type(node) is list:
                for child in node: inspect(child,depth+1)
        inspect(value)
        issues=[]; _walk(value,SCHEMA,'$',issues)
        if not issues:
            if value['event_id'] != f"{value['producer_id']}:{int(value['sequence'])}": issues.append({'path':'$.event_id','rule':'identity'})
            data=value['data']
            if value['phase']=='wait' and data['deadline_ms']<data['wait_started_ms']: issues.append({'path':'$.data.deadline_ms','rule':'deadline'})
            if any(link['event_id'] is None and link['operation_id'] is None for link in value['links']): issues.append({'path':'$.links','rule':'target'})
        return issues
    except (ValueError,TypeError,OverflowError,RecursionError): return [{'path':'$', 'rule':'unsafe_or_non_json'}]
