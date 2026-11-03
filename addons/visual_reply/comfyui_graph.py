"""Expand saved ComfyUI subgraphs into independent backend node instances."""
from __future__ import annotations

import copy


def ui_links(graph):
    """Accept the list links used by workflows and object links in subgraphs."""
    for link in graph.get('links') or []:
        if isinstance(link, dict):
            yield [link['id'], link['origin_id'], link['origin_slot'],
                   link['target_id'], link['target_slot'], link.get('type', '*')]
        elif isinstance(link, (list, tuple)) and len(link) >= 5:
            yield list(link)


def expand_subgraphs(payload, convert_graph):
    definitions = {str(graph['id']): graph for graph in
                   (payload.get('definitions') or {}).get('subgraphs', [])}

    def expand(graph, prefix='', bindings=None, ancestry=()):
        local = convert_graph({key: value for key, value in graph.items() if key != 'definitions'})
        originals = {str(node['id']): node for node in graph.get('nodes', [])}
        input_id = str((graph.get('inputNode') or {}).get('id', -10))
        output_id = str((graph.get('outputNode') or {}).get('id', -20))
        promoted = list(graph.get('inputs') or [])
        api, instances, expanding = {}, {}, set()

        def instance(identifier):
            if identifier in instances:
                return instances[identifier]
            definition_id = local[identifier]['class_type']
            if definition_id in ancestry or identifier in expanding:
                raise RuntimeError('Recursive ComfyUI subgraph connection: ' + definition_id)
            expanding.add(identifier)
            arguments = {name: resolve(value) for name, value in local[identifier]['inputs'].items()}
            children, outputs = expand(definitions[definition_id], prefix + identifier + ':',
                                       arguments, (*ancestry, definition_id))
            api.update(children)
            instances[identifier] = outputs
            expanding.remove(identifier)
            return outputs

        def resolve(value):
            if not (isinstance(value, (list, tuple)) and len(value) == 2
                    and isinstance(value[0], (str, int)) and isinstance(value[1], int)):
                return copy.deepcopy(value)
            identifier, slot = str(value[0]), value[1]
            if bindings is not None and identifier == input_id:
                if not 0 <= slot < len(promoted) or promoted[slot]['name'] not in bindings:
                    raise RuntimeError('Missing promoted input in ComfyUI subgraph: ' + identifier)
                return copy.deepcopy(bindings[promoted[slot]['name']])
            if identifier in local and local[identifier]['class_type'] in definitions:
                outputs = instance(identifier)
                if slot not in outputs:
                    raise RuntimeError('Disconnected ComfyUI subgraph output: ' + identifier)
                return copy.deepcopy(outputs[slot])
            if identifier not in local:
                source = originals.get(identifier, {})
                if source.get('type') == 'PrimitiveNode':
                    values = source.get('widgets_values') or []
                    return copy.deepcopy(values[0]) if values else None
                raise RuntimeError('Unresolved ComfyUI node connection: ' + identifier)
            return [prefix + identifier, slot]

        for identifier, node in local.items():
            if originals[identifier].get('mode') not in (None, 0):
                raise RuntimeError('ComfyUI workflows with muted or bypassed subgraph nodes require an API-format export.')
            if node['class_type'] in definitions:
                instance(identifier)
            else:
                api[prefix + identifier] = {**node, 'inputs': {
                    name: resolve(value) for name, value in node['inputs'].items()}}
        outputs = {int(link[4]): resolve([str(link[1]), int(link[2])])
                   for link in ui_links(graph) if str(link[3]) == output_id}
        return api, outputs

    return expand(payload)[0]
