"""
Component-level chunked comparison for EDMM evaluation.

Per official EDMM spec, component structure:
  <component_name>:
    type: <component_type_name>
    description: <component_description>
    metadata: <map_of_string>
    properties:
      <property_assignments>  # Dict format: property_name: property_value
    operations:
      <operation_definitions>
    artifacts:
      - <artifact_assignments>  # List format
    relations:
      - <relation_assignments>  # List format

This module compares components as chunks with 4 sub-sections:
- type (0.25 weight)
- properties (0.25 weight)
- artifacts (0.25 weight)
- relations (0.25 weight)
"""

from typing import Dict, List, Any, Tuple
import yaml


def compare_component_chunks(expected: Dict, actual: Dict) -> Dict[str, Any]:
    """
    Component-level chunked comparison.
    
    Each component is evaluated as a chunk with 4 sub-sections:
    - type (0.25 weight)
    - properties (0.25 weight)
    - artifacts (0.25 weight)
    - relations (0.25 weight)
    
    Args:
        expected: Expected EDMM data
        actual: Actual RAG output
    
    Returns:
        {
            'components': {
                'component_name': {
                    'similarity': float,  # Overall component similarity
                    'status': 'matched' | 'mismatched' | 'missing' | 'unexpected',
                    'sub_sections': {
                        'type': {'similarity': float, 'differences': [...]},
                        'properties': {'similarity': float, 'differences': [...]},
                        'artifacts': {'similarity': float, 'differences': [...]},
                        'relations': {'similarity': float, 'differences': [...]}
                    }
                }
            },
            'total_components': int,
            'matched_count': int,
            'mismatched_count': int,
            'missing_count': int,
            'unexpected_count': int
        }
    """
    from edmm_semantic_compare import EDMMSemanticComparer
    
    exp_components = expected.get('components', [])
    act_components = actual.get('components', [])
    
    # Convert component lists to dicts for easier lookup
    # EDMM format: components is a list of single-key dicts
    def components_to_dict(comp_list):
        result = {}
        if isinstance(comp_list, list):
            for item in comp_list:
                if isinstance(item, dict) and len(item) > 0:
                    comp_name = list(item.keys())[0]
                    result[comp_name] = item[comp_name]
        return result
    
    exp_comps_dict = components_to_dict(exp_components)
    act_comps_dict = components_to_dict(act_components)
    
    component_results = {}
    comparer = EDMMSemanticComparer()
    
    # Get all component names (union of expected and actual)
    all_comp_names = set(exp_comps_dict.keys()) | set(act_comps_dict.keys())
    
    # Counters
    matched_count = 0
    mismatched_count = 0
    missing_count = 0
    unexpected_count = 0
    
    for comp_name in all_comp_names:
        exp_comp = exp_comps_dict.get(comp_name, {})
        act_comp = act_comps_dict.get(comp_name, {})
        
        # If component missing entirely in actual
        if not exp_comp:
            component_results[comp_name] = {
                'similarity': 0.0,
                'status': 'unexpected',
                'message': 'Component not in expected EDMM',
                'sub_sections': {}
            }
            unexpected_count += 1
            continue
        
        # If component missing in actual
        if not act_comp:
            component_results[comp_name] = {
                'similarity': 0.0,
                'status': 'missing',
                'message': 'Component missing in actual output',
                'sub_sections': {}
            }
            missing_count += 1
            continue
        
        # Sub-section comparison (equal weight: 0.25 each)
        sub_sections = {
            'type': {'weight': 0.25},
            'properties': {'weight': 0.25},
            'artifacts': {'weight': 0.25},
            'relations': {'weight': 0.25}
        }
        
        sub_results = {}
        total_sim = 0.0
        has_mismatch = False
        
        for sub_key, config in sub_sections.items():
            # Get sub-section data
            # Per EDMM spec:
            # - type: string
            # - properties: dict (property_name: property_value)
            # - artifacts: list
            # - relations: list
            if sub_key == 'type':
                exp_sub = exp_comp.get(sub_key, None)
                act_sub = act_comp.get(sub_key, None)
            elif sub_key == 'properties':
                exp_sub = exp_comp.get(sub_key, {})  # Dict per EDMM spec
                act_sub = act_comp.get(sub_key, {})
            else:  # artifacts, relations
                exp_sub = exp_comp.get(sub_key, [])  # List per EDMM spec
                act_sub = act_comp.get(sub_key, [])
            
            # Compare sub-section
            is_match, diffs = comparer.compare(exp_sub, act_sub)
            
            # Calculate similarity for this sub-section
            if sub_key == 'type':
                # Type is simple string comparison
                similarity = 1.0 if exp_sub == act_sub else 0.0
            elif sub_key == 'properties':
                # Properties is a dict
                if isinstance(exp_sub, dict):
                    total_props = len(exp_sub)
                    if total_props == 0:
                        similarity = 1.0 if len(act_sub) == 0 else 0.0
                    else:
                        mismatch_count_props = len(diffs)
                        similarity = max(0.0, (total_props - mismatch_count_props) / total_props)
                else:
                    similarity = 1.0 if is_match else 0.0
            else:
                # For lists (artifacts, relations)
                if isinstance(exp_sub, list):
                    total_items = len(exp_sub)
                    if total_items == 0:
                        similarity = 1.0 if len(act_sub) == 0 else 0.0
                    else:
                        mismatch_count_items = len(diffs)
                        similarity = max(0.0, (total_items - mismatch_count_items) / total_items)
                else:
                    similarity = 1.0 if is_match else 0.0
            
            if similarity < 1.0:
                has_mismatch = True
            
            sub_results[sub_key] = {
                'similarity': similarity,
                'is_match': is_match,
                'differences': diffs[:10],  # Limit to 10 diffs per sub-section
                'weight': config['weight']
            }
            
            total_sim += similarity * config['weight']
        
        # Overall component similarity (weighted average of sub-sections)
        status = 'matched' if total_sim == 1.0 else 'mismatched'
        
        if status == 'matched':
            matched_count += 1
        else:
            mismatched_count += 1
        
        component_results[comp_name] = {
            'similarity': total_sim,
            'status': status,
            'sub_sections': sub_results
        }
    
    return {
        'components': component_results,
        'total_components': len(all_comp_names),
        'matched_count': matched_count,
        'mismatched_count': mismatched_count,
        'missing_count': missing_count,
        'unexpected_count': unexpected_count
    }
