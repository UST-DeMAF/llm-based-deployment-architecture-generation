"""
Complete EDMM Annotator covering full EDMM YAML specification.
Validates all fields: version, metadata, properties, relation_types, component_types, components.
"""

import yaml
from typing import Dict, Any, List, Tuple


def annotate_by_objects(actual_data: Dict, expected_data: Dict) -> str:
    """
    Generate HTML showing actual YAML with inline status indicators.
    Also injects MISSING fields from Expected that are absent in Actual.
    Covers complete EDMM specification.
    """
    # Get component-level comparison results
    from component_chunks import compare_component_chunks
    chunk_results = compare_component_chunks(expected_data, actual_data)
    
    # Convert actual to YAML
    actual_yaml = yaml.dump(actual_data, sort_keys=False, default_flow_style=False)
    lines = actual_yaml.split('\n')
    
    # Build comprehensive status map
    status_map = _build_comprehensive_status_map(actual_data, expected_data, chunk_results)
    
    # Get missing items from expected
    missing_items = _find_missing_items(actual_data, expected_data)
    
    # Render with colors and markers
    html_lines = []
    
    for line_num, line in enumerate(lines):
        if not line.strip():
            html_lines.append('<div>&nbsp;</div>')
            continue
        
        status_info = status_map.get(line_num, ('neutral', ''))
        status, message = status_info
        
        # Escape HTML
        escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Color and marker based on status
        if status == 'match':
            html_lines.append(
                f'<div style="background: #d4edda; padding: 2px 5px;">'
                f'{escaped} <span style="color: #155724; font-weight: bold;">✓</span>'
                f'</div>'
            )
        elif status == 'mismatch':
            html_lines.append(
                f'<div style="background: #f8d7da; padding: 2px 5px;">'
                f'{escaped} <span style="color: #721c24; font-weight: bold;">✗</span> '
                f'<span style="color: #721c24; font-size: 0.9em;">{message}</span>'
                f'</div>'
            )
        elif status == 'extra':
            html_lines.append(
                f'<div style="background: #fff3cd; padding: 2px 5px;">'
                f'{escaped} <span style="color: #856404; font-weight: bold;">+</span> '
                f'<span style="color: #856404; font-size: 0.85em;">(Extra)</span>'
                f'</div>'
            )
        elif status == 'missing':
            html_lines.append(
                f'<div style="background: #f8d7da; padding: 2px 5px; border-left: 3px solid red;">'
                f'{escaped} <span style="color: #721c24; font-weight: bold;">- MISSING</span>'
                f'</div>'
            )
        else:
            # Neutral - no specific status
            html_lines.append(f'<div style="padding: 2px 5px; color: #666;">{escaped}</div>')
    
    # Inject missing items at the end
    if missing_items:
        html_lines.append('<div>&nbsp;</div>')
        html_lines.append(
            f'<div style="background: #ffe6e6; padding: 5px; margin-top: 10px; border: 2px solid red; font-weight: bold;">'
            f'⚠️ MISSING FIELDS (Present in Expected, Absent in Actual):'
            f'</div>'
        )
        for missing_line in missing_items:
            escaped_missing = missing_line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_lines.append(
                f'<div style="background: #f8d7da; padding: 2px 5px; border-left: 3px solid red;">'
                f'{escaped_missing} <span style="color: #721c24; font-weight: bold;">- MISSING</span>'
                f'</div>'
            )
    
    return '\n'.join(html_lines)


def _build_comprehensive_status_map(actual_data: Dict, expected_data: Dict, chunk_results: Dict) -> Dict[int, Tuple[str, str]]:
    """
    Build comprehensive status map covering all EDMM fields.
    """
    status_map = {}
    
    actual_yaml = yaml.dump(actual_data, sort_keys=False, default_flow_style=False)
    lines = actual_yaml.split('\n')
    
    # Context tracking
    context = {
        'section': None,  # Top-level: 'version', 'metadata', 'properties', 'relation_types', 'component_types', 'components'
        'component': None,
        'component_type': None,
        'relation_type': None,
        'subsection': None,  # 'properties', 'operations', 'artifacts', 'relations', 'metadata'
        'indent_level': 0
    }
    
    # Prepare lookup maps
    components_map = _list_to_dict(actual_data.get('components', []))
    expected_components_map = _list_to_dict(expected_data.get('components', []))
    
    types_map = _list_to_dict(actual_data.get('component_types', []))
    expected_types_map = _list_to_dict(expected_data.get('component_types', []))
    
    relation_types_map = _list_to_dict(actual_data.get('relation_types', []))
    expected_relation_types_map = _list_to_dict(expected_data.get('relation_types', []))
    
    for line_num, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        
        indent = len(line) - len(line.lstrip())
        
        # === TOP-LEVEL FIELDS ===
        if indent == 0:
            if stripped == 'version:' or stripped.startswith('version:'):
                context['section'] = 'version'
                val = stripped.split(':', 1)[1].strip() if ':' in stripped and len(stripped.split(':', 1)) > 1 else ''
                exp_val = str(expected_data.get('version', ''))
                status_map[line_num] = _compare_simple(val, exp_val)
                continue
            
            elif stripped == 'description:' or stripped.startswith('description:'):
                context['section'] = 'description'
                val = stripped.split(':', 1)[1].strip() if ':' in stripped and len(stripped.split(':', 1)) > 1 else ''
                exp_val = str(expected_data.get('description', ''))
                status_map[line_num] = _compare_simple(val, exp_val)
                continue
            
            elif stripped == 'metadata:':
                context['section'] = 'metadata'
                context['subsection'] = 'metadata'
                status_map[line_num] = ('neutral', '')
                continue
            
            elif stripped == 'properties:':
                context['section'] = 'properties'
                context['subsection'] = 'properties'
                # Check if inline empty
                if 'properties: []' in line or 'properties:[]' in line:
                    exp_props = expected_data.get('properties', {})
                    if not exp_props or exp_props == [] or exp_props == {}:
                        status_map[line_num] = ('match', '')
                    else:
                        status_map[line_num] = ('mismatch', f'Expected {len(exp_props)} properties')
                else:
                    status_map[line_num] = ('neutral', '')
                continue
            
            elif stripped == 'relation_types:':
                context['section'] = 'relation_types'
                status_map[line_num] = ('neutral', '')
                continue
            
            elif stripped == 'component_types:':
                context['section'] = 'component_types'
                status_map[line_num] = ('neutral', '')
                continue
            
            elif stripped == 'components:':
                context['section'] = 'components'
                status_map[line_num] = ('neutral', '')
                continue
        
        # === RELATION TYPES ===
        if context['section'] == 'relation_types':
            if stripped.startswith('- ') and ':' in stripped:
                rel_type_name = stripped[2:].split(':')[0].strip()
                context['relation_type'] = rel_type_name
                context['subsection'] = None
                
                if rel_type_name not in expected_relation_types_map:
                    status_map[line_num] = ('extra', '')
                else:
                    status_map[line_num] = ('neutral', '')  # Let individual fields show status
                continue
            
            # Fields within relation type
            if context['relation_type']:
                status_map[line_num] = _compare_field_in_dict(
                    stripped, 
                    relation_types_map.get(context['relation_type'], {}),
                    expected_relation_types_map.get(context['relation_type'], {})
                )
                continue
        
        # === COMPONENT TYPES ===
        if context['section'] == 'component_types':
            if stripped.startswith('- ') and ':' in stripped:
                type_name = stripped[2:].split(':')[0].strip()
                context['component_type'] = type_name
                context['subsection'] = None
                
                # Just check if type exists, don't use deep_equal for header
                if type_name not in expected_types_map:
                    status_map[line_num] = ('extra', '')
                else:
                    status_map[line_num] = ('neutral', '')  # Let individual fields show status
                continue
            
            # Subsections - check for empty lists/dicts
            if 'properties:' in stripped:
                context['subsection'] = 'properties'
                # Check if it's an empty dict/list inline
                if stripped.endswith('{}') or stripped.endswith('[]'):
                    exp_props = expected_types_map.get(context['component_type'], {}).get('properties', {})
                    if not exp_props or exp_props == [] or exp_props == {}:
                        status_map[line_num] = ('match', '')
                    else:
                        status_map[line_num] = ('mismatch', f'Expected {len(exp_props)} properties')
                else:
                    status_map[line_num] = ('neutral', '')
                continue
            
            if 'operations:' in stripped:
                context['subsection'] = 'operations'
                # Check if it's an empty list inline
                if stripped.endswith('[]'):
                    exp_ops = expected_types_map.get(context['component_type'], {}).get('operations', [])
                    if not exp_ops or exp_ops == []:
                        status_map[line_num] = ('match', '')
                    else:
                        status_map[line_num] = ('mismatch', f'Expected {len(exp_ops)} operations')
                else:
                    status_map[line_num] = ('neutral', '')
                continue
            
            if 'metadata:' in stripped:
                context['subsection'] = 'metadata'
                if stripped.endswith('{}') or stripped.endswith('[]'):
                    exp_meta = expected_types_map.get(context['component_type'], {}).get('metadata', {})
                    if not exp_meta or exp_meta == {} or exp_meta == []:
                        status_map[line_num] = ('match', '')
                    else:
                        status_map[line_num] = ('mismatch', 'Expected metadata values')
                else:
                    status_map[line_num] = ('neutral', '')
                continue
            
            # Simple fields (description, extends)
            if context['component_type'] and stripped.startswith('description:'):
                actual_val = stripped.split(':', 1)[1].strip() if len(stripped.split(':', 1)) > 1 else ''
                exp_val = str(expected_types_map.get(context['component_type'], {}).get('description', ''))
                status_map[line_num] = _compare_simple(actual_val, exp_val)
                continue
            
            if context['component_type'] and stripped.startswith('extends:'):
                actual_val = stripped.split(':', 1)[1].strip().strip('"')
                exp_val = str(expected_types_map.get(context['component_type'], {}).get('extends', '')).strip('"')
                status_map[line_num] = _compare_simple(actual_val, exp_val)
                continue
            
            # Property definitions (nested structure)
            if context['subsection'] == 'properties' and context['component_type']:
                exp_props = expected_types_map.get(context['component_type'], {}).get('properties', {})
                
                # Property name line (no leading dash, lower indent than property fields)
                if not stripped.startswith('-') and ':' in stripped and indent > 2:
                    prop_name = stripped.split(':')[0].strip()
                    # Check if property name exists in expected
                    if prop_name in exp_props:
                        context['current_property'] = prop_name
                        status_map[line_num] = ('neutral', '')  # Property name itself is neutral
                    else:
                        context['current_property'] = prop_name
                        status_map[line_num] = ('extra', '')
                    continue
                
                # Property definition fields (type, required, default_value, etc.)
                if hasattr(context, 'get') == False:
                    context['current_property'] = context.get('current_property', None)
                
                current_prop = context.get('current_property', None)
                if current_prop and ':' in stripped and indent > 4:
                    field_name = stripped.split(':')[0].strip()
                    field_value = stripped.split(':', 1)[1].strip() if len(stripped.split(':', 1)) > 1 else ''
                    
                    exp_prop_def = exp_props.get(current_prop, {})
                    if isinstance(exp_prop_def, dict) and field_name in exp_prop_def:
                        if str(exp_prop_def[field_name]) == field_value:
                            status_map[line_num] = ('match', '')
                        else:
                            status_map[line_num] = ('mismatch', f'Expected: {exp_prop_def[field_name]}')
                    else:
                        status_map[line_num] = ('extra', '')
                    continue
            
            # Operations items
            if context['subsection'] == 'operations' and stripped.startswith('- '):
                exp_ops = expected_types_map.get(context['component_type'], {}).get('operations', [])
                if _item_in_list(stripped[2:], exp_ops):
                    status_map[line_num] = ('match', '')
                else:
                    status_map[line_num] = ('extra', '')
                continue
        
        # === COMPONENTS ===
        if context['section'] == 'components':
            if stripped.startswith('- ') and ':' in stripped:
                comp_name = stripped[2:].split(':')[0].strip()
                context['component'] = comp_name
                context['subsection'] = None
                
                if comp_name not in expected_components_map:
                    status_map[line_num] = ('extra', 'Not in expected')
                else:
                    status_map[line_num] = ('neutral', '')  # Let individual fields show status
                continue
            
            # Subsections - check for inline empty lists too
            if 'properties:' in stripped:
                context['subsection'] = 'properties'
                # Check if it's an empty list inline
                if stripped.endswith('[]'):
                    exp_props = expected_components_map.get(context['component'], {}).get('properties', {})
                    if not exp_props or exp_props == [] or exp_props == {}:
                        status_map[line_num] = ('match', '')
                    else:
                        status_map[line_num] = ('mismatch', f'Expected {len(exp_props)} properties')
                else:
                    status_map[line_num] = ('neutral', '')
                continue
            
            if 'operations:' in stripped:
                context['subsection'] = 'operations'
                # Check if it's an empty list inline
                if stripped.endswith('[]'):
                    exp_ops = expected_components_map.get(context['component'], {}).get('operations', [])
                    if not exp_ops or exp_ops == []:
                        status_map[line_num] = ('match', '')
                    else:
                        status_map[line_num] = ('mismatch', f'Expected {len(exp_ops)} operations')
                else:
                    status_map[line_num] = ('neutral', '')
                continue
            
            if 'artifacts:' in stripped:
                context['subsection'] = 'artifacts'
                # Check if it's an empty list inline
                if stripped.endswith('[]'):
                    exp_arts = expected_components_map.get(context['component'], {}).get('artifacts', [])
                    if not exp_arts or exp_arts == []:
                        status_map[line_num] = ('match', '')
                    else:
                        status_map[line_num] = ('mismatch', f'Expected {len(exp_arts)} artifacts')
                else:
                    status_map[line_num] = ('neutral', '')
                continue
            
            if 'relations:' in stripped:
                context['subsection'] = 'relations'
                # Check if it's an empty list inline
                if stripped.endswith('[]'):
                    exp_rels = expected_components_map.get(context['component'], {}).get('relations', [])
                    if not exp_rels or exp_rels == []:
                        status_map[line_num] = ('match', '')
                    else:
                        status_map[line_num] = ('mismatch', f'Expected {len(exp_rels)} relations')
                else:
                    status_map[line_num] = ('neutral', '')
                continue
            
            if 'metadata:' in stripped:
                context['subsection'] = 'metadata'
                # Check if it's an empty dict/list inline
                if stripped.endswith('{}') or stripped.endswith('[]'):
                    exp_meta = expected_components_map.get(context['component'], {}).get('metadata', {})
                    if not exp_meta or exp_meta == {} or exp_meta == []:
                        status_map[line_num] = ('match', '')
                    else:
                        status_map[line_num] = ('mismatch', 'Expected metadata values')
                else:
                    status_map[line_num] = ('neutral', '')
                continue
            
            # Type field
            if stripped.startswith('type:') and context['component']:
                actual_type = stripped.split(':', 1)[1].strip().strip('"')
                expected_type = str(expected_components_map.get(context['component'], {}).get('type', '')).strip('"')
                status_map[line_num] = _compare_simple(actual_type, expected_type)
                continue
            
            # Description field
            if stripped.startswith('description:') and context['component']:
                actual_desc = stripped.split(':', 1)[1].strip() if len(stripped.split(':', 1)) > 1 else ''
                expected_desc = str(expected_components_map.get(context['component'], {}).get('description', ''))
                status_map[line_num] = _compare_simple(actual_desc, expected_desc)
                continue
            
            # Properties
            if context['subsection'] == 'properties' and stripped.startswith('- ') and ':' in stripped:
                prop_key = stripped[2:].split(':')[0].strip()
                prop_val = stripped.split(':', 1)[1].strip().strip('"')
                
                exp_props = expected_components_map.get(context['component'], {}).get('properties', {})
                if isinstance(exp_props, list):
                    exp_props = _list_to_dict(exp_props)
                
                if prop_key not in exp_props:
                    status_map[line_num] = ('extra', '')
                elif str(exp_props[prop_key]).strip('"') != prop_val:
                    status_map[line_num] = ('mismatch', f'Expected: {exp_props[prop_key]}')
                else:
                    status_map[line_num] = ('match', '')
                continue
            
            # Operations items
            if context['subsection'] == 'operations' and stripped.startswith('- '):
                exp_ops = expected_components_map.get(context['component'], {}).get('operations', [])
                if _item_in_list(stripped[2:], exp_ops):
                    status_map[line_num] = ('match', '')
                else:
                    status_map[line_num] = ('extra', '')
                continue
            
            # Artifacts items
            if context['subsection'] == 'artifacts' and stripped.startswith('- '):
                exp_list = expected_components_map.get(context['component'], {}).get('artifacts', [])
                if _item_in_list(stripped[2:], exp_list):
                    status_map[line_num] = ('match', '')
                else:
                    status_map[line_num] = ('extra', '')
                continue
            
            # Relations items
            if context['subsection'] == 'relations' and stripped.startswith('- '):
                exp_list = expected_components_map.get(context['component'], {}).get('relations', [])
                if _item_in_list(stripped[2:], exp_list):
                    status_map[line_num] = ('match', '')
                else:
                    status_map[line_num] = ('extra', '')
                continue
            
            # Metadata fields
            if context['subsection'] == 'metadata' and ':' in stripped:
                status_map[line_num] = _compare_field_in_dict(
                    stripped,
                    expected_components_map.get(context['component'], {}).get('metadata', {}),
                    expected_components_map.get(context['component'], {}).get('metadata', {})
                )
                continue
    
    return status_map


def _compare_simple(actual_val, expected_val):
    """Compare two simple values with normalization."""
    # Normalize values
    actual_normalized = _normalize_value(actual_val)
    expected_normalized = _normalize_value(expected_val)
    
    if actual_normalized == expected_normalized:
        return ('match', '')
    elif expected_normalized == '':
        return ('extra', '')
    else:
        return ('mismatch', f'Expected: {expected_val}')


def _normalize_value(val):
    """Normalize a value for comparison: handle null/None, quotes, whitespace."""
    if val is None or str(val).lower() == 'none' or str(val).lower() == 'null':
        return 'null'
    
    # Convert to string and strip quotes and whitespace
    normalized = str(val).strip().strip('"').strip("'")
    return normalized


def _compare_field_in_dict(line_stripped, actual_dict, expected_dict):
    """Compare a field in a dictionary context."""
    if ':' not in line_stripped:
        return ('neutral', '')
    
    field_name = line_stripped.split(':')[0].strip()
    field_value = line_stripped.split(':', 1)[1].strip() if len(line_stripped.split(':', 1)) > 1 else ''
    
    if field_name in expected_dict:
        actual_normalized = _normalize_value(actual_dict.get(field_name, ''))
        expected_normalized = _normalize_value(expected_dict[field_name])
        
        if actual_normalized == expected_normalized:
            return ('match', '')
        else:
            return ('mismatch', f'Expected: {expected_dict[field_name]}')
    else:
        return ('extra', '')


def _item_in_list(item_str, item_list):
    """Check if item string representation exists in list."""
    for item in item_list:
        if isinstance(item, dict):
            k = list(item.keys())[0]
            v = item[k]
            if f"{k}: {v}" == item_str or f"{k}:" == item_str:
                return True
        elif str(item) == item_str:
            return True
    return False


def _deep_equal(obj1, obj2):
    """Deep equality check."""
    if obj1 is None or obj2 is None:
        return obj1 == obj2
    return yaml.dump(obj1, sort_keys=True) == yaml.dump(obj2, sort_keys=True)


def _list_to_dict(lst):
    """Convert list of single-key dicts to flat dict."""
    result = {}
    for item in lst:
        if isinstance(item, dict):
            key = list(item.keys())[0]
            result[key] = item[key]
    return result


def _find_missing_items(actual_data: Dict, expected_data: Dict) -> List[str]:
    """
    Find items present in expected_data but missing in actual_data.
    Returns a list of YAML-formatted strings representing missing fields.
    """
    missing_lines = []
    
    # Check components
    if 'components' in expected_data:
        exp_comps = _list_to_dict(expected_data.get('components', []))
        act_comps = _list_to_dict(actual_data.get('components', [])) if 'components' in actual_data else {}
        
        for comp_name, comp_data in exp_comps.items():
            if comp_name not in act_comps:
                missing_lines.append(f"components.{comp_name}: (ENTIRE COMPONENT MISSING)")
            else:
                # Check properties within component
                exp_props = comp_data.get('properties', [])
                act_props = act_comps[comp_name].get('properties', [])
                
                if isinstance(exp_props, list) and isinstance(act_props, list):
                    exp_props_dict = _list_to_dict(exp_props) if exp_props else {}
                    act_props_dict = _list_to_dict(act_props) if act_props else {}
                    
                    for prop_key in exp_props_dict:
                        if prop_key not in act_props_dict:
                            missing_lines.append(f"  {comp_name}.properties.{prop_key}: {exp_props_dict[prop_key]}")
                
                # Check operations
                exp_ops = comp_data.get('operations', [])
                act_ops = act_comps[comp_name].get('operations', [])
                if exp_ops and not act_ops:
                    missing_lines.append(f"  {comp_name}.operations: (has {len(exp_ops)} operations)")
                
                # Check artifacts
                exp_arts = comp_data.get('artifacts', [])
                act_arts = act_comps[comp_name].get('artifacts', [])
                if exp_arts and not act_arts:
                    missing_lines.append(f"  {comp_name}.artifacts: (has {len(exp_arts)} artifacts)")
    
    # Check component_types
    if 'component_types' in expected_data:
        exp_types = _list_to_dict(expected_data.get('component_types', []))
        act_types = _list_to_dict(actual_data.get('component_types', [])) if 'component_types' in actual_data else {}
        
        for type_name in exp_types:
            if type_name not in act_types:
                missing_lines.append(f"component_types.{type_name}: (ENTIRE TYPE MISSING)")
    
    # Check relation_types
    if 'relation_types' in expected_data:
        exp_rels = _list_to_dict(expected_data.get('relation_types', []))
        act_rels = _list_to_dict(actual_data.get('relation_types', [])) if 'relation_types' in actual_data else {}
        
        for rel_name in exp_rels:
            if rel_name not in act_rels:
                missing_lines.append(f"relation_types.{rel_name}: (ENTIRE RELATION TYPE MISSING)")
    
    return missing_lines
