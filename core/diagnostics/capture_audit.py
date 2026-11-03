"""Offline integrity audit of explicitly supplied diagnostic records, not a root-cause oracle."""
import argparse
import json
from pathlib import Path
from core.diagnostics.contract import validate_event


def audit_events(events):
    report=dict(scope='supplied_records_only',invalid_events=0,duplicate_events=0,
                conflicting_event_ids=[],sequence_gaps=[],unfinished_operations=[],
                terminal_without_begin=[],missing_linked_events=[],loss_markers=[],reused_operations=[],
                missing_linked_operations=[],terminal_before_begin=[],unresolved_attribution=[],diagnostic_policies=[],intentionally_suppressed_begins=[])
    unique={};producers={};begins={};ends={};linked=set();linked_operations=set();operations=set()
    for row in events:
        if validate_event(row):
            report['invalid_events']+=1
            continue
        identifier=row['event_id']
        if identifier in unique:
            if row==unique[identifier]:report['duplicate_events']+=1
            elif identifier not in report['conflicting_event_ids']:report['conflicting_event_ids'].append(identifier)
            continue
        unique[identifier]=row
        if row['event_name']=='diagnostics.policy':
            report['diagnostic_policies'].append(dict(producer_id=row['producer_id'],component=row['component'],
                event_id=identifier,**row['data']))
        if row['data'].get('condition') in ('callback_source_identified','source_registration_known') and row['data'].get('actual') is False:
            report['unresolved_attribution'].append(identifier)
        producers.setdefault(row['producer_id'],set()).add(row['sequence'])
        key=(row['producer_id'],row['operation_id'])
        operations.add(row['operation_id'])
        if row['phase']=='begin':begins.setdefault(key,[]).append(identifier)
        if row['phase']=='end':ends.setdefault(key,[]).append(identifier)
        linked.update(link['event_id'] for link in row['links'] if link['event_id'] is not None)
        linked_operations.update(link['operation_id'] for link in row['links'] if link['operation_id'] is not None)
        if row['event_name'] in ('diagnostics.sink_failed','diagnostics.validation_failed') or (
            row['event_name']=='diagnostics.capture_state' and row['data'].get('state')=='incomplete'):
            report['loss_markers'].append(identifier)
    for producer,sequences in sorted(producers.items()):
        previous=0
        for sequence in sorted(sequences):
            if sequence>previous+1:
                report['sequence_gaps'].append(dict(producer_id=producer,first=previous+1,last=sequence-1))
            previous=sequence
    for (producer,operation),identifiers in begins.items():
        if len(identifiers)>1 or len(ends.get((producer,operation),[]))>1:
            report['reused_operations'].append(dict(producer_id=producer,operation_id=operation))
        if any(unique[end]['sequence']<unique[begin]['sequence'] for begin in identifiers for end in ends.get((producer,operation),[])):
            report['terminal_before_begin'].append(dict(producer_id=producer,operation_id=operation))
        if (producer,operation) not in ends:
            report['unfinished_operations'].extend(dict(producer_id=producer,operation_id=operation,begin_event_id=i) for i in identifiers)
    for (producer,operation),identifiers in ends.items():
        if (producer,operation) not in begins:
            for identifier in identifiers:
                key='intentionally_suppressed_begins' if unique[identifier]['data'].get('begin_suppressed') is True else 'terminal_without_begin'
                report[key].append(dict(producer_id=producer,operation_id=operation,end_event_id=identifier))
    report['missing_linked_events']=sorted(linked-unique.keys())
    report['missing_linked_operations']=sorted(linked_operations-operations)
    report['event_count']=len(unique)
    report['lifecycle_begin_count']=sum(map(len,begins.values()))
    _integrity(report)
    return report


def _integrity(report):
    gaps=any(report.get(key) for key in ('invalid_events','conflicting_event_ids','sequence_gaps',
        'unfinished_operations','terminal_without_begin','missing_linked_events','loss_markers','malformed_lines',
        'reused_operations','external_loss_markers','missing_linked_operations','terminal_before_begin','unclean_captures'))
    report['integrity']='gaps_detected' if gaps else 'no_gaps_detected_in_supplied_records'
    # No finite log prefix establishes that all intended sites were instrumented,
    # or that a process did not die before emitting its first/last record.
    report['coverage']='not_proven'
    if any(p['status']=='applied' and any(level!='trace' for level in p['effective'].values())
           for p in report.get('diagnostic_policies',[])):
        report['coverage']='selectively_disabled_not_proven'


def audit_files(paths):
    paths=list(paths)
    malformed=0;external_loss=0
    def rows():
        nonlocal malformed,external_loss
        for path in paths:
            with Path(path).open(encoding='utf-8') as stream:
                for line in stream:
                    if not line.strip():continue
                    try:row=json.loads(line)
                    except (ValueError,TypeError):malformed+=1;continue
                    if isinstance(row,dict) and row.get('event') in ('phone_debug_overflow','phone_debug_storage_failure'):
                        external_loss+=1
                    elif isinstance(row,dict) and row.get('event')=='diagnostic_event':
                        details=row.get('details')
                        yield details.get('contract') if isinstance(details,dict) else None
                    elif isinstance(row,dict) and 'schema_version' in row:yield row
    report=audit_events(rows());report['malformed_lines']=malformed;report['external_loss_markers']=external_loss
    report['unclean_captures']=0
    report['capture_health_unavailable']=0
    report['retention_rotations']=0
    for path in paths:
        health=Path(path).with_suffix(Path(path).suffix+'.health.json')
        if not health.exists():
            report['capture_health_unavailable']+=1
            continue
        try:
            with health.open(encoding='utf-8') as handle:raw=handle.read(16385)
            if len(raw)>16384:raise ValueError('oversized health')
            value=json.loads(raw)
            counters=('written','rotations','rejected','write_failures')
            if (type(value) is not dict or type(value.get('version')) is not int or value['version']!=1
                    or value.get('state') not in ('active','closed','incomplete')
                    or type(value.get('previous_unclean')) is not bool
                    or any(type(value.get(key)) is not int or value[key]<0 for key in counters)):
                raise ValueError('invalid health')
            report['retention_rotations']+=value['rotations']
            if (value['state']!='closed' or value['previous_unclean']
                    or value['rejected'] or value['write_failures']):report['unclean_captures']+=1
        except (OSError,ValueError,TypeError):report['unclean_captures']+=1
    _integrity(report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs',nargs='+',type=Path)
    args=parser.parse_args()
    print(json.dumps(audit_files(args.logs),indent=2))
