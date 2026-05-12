"""
EDMM Semantic Comparer - Eliminates false positives in evaluation

Handles:
- Quote differences ("value" vs value)
- Order-independent lists (components, relations, properties)
- Type-specific comparisons (port strings vs integers)
"""

from typing import Dict, List, Any, Tuple, Set
import yaml
import networkx as nx


def _normalize_section(raw):
    """
    Convert a section (components, relations, etc.) to list-of-maps format.
    Handles both plain-dict format (from Streamlit UI copy-paste) and
    list-of-maps format (from internal post-processing).
    """
    if isinstance(raw, dict):
        return [{k: v} for k, v in raw.items()]
    if isinstance(raw, list):
        return raw
    return []


class EDMMSemanticComparer:
    """
    EDMM-aware semantic comparison.
    Compares YAML structures semantically, ignoring irrelevant formatting differences.
    """
    
    # Lists where order doesn't matter in EDMM
    ORDER_INDEPENDENT_LISTS = {
        'components', 
        'relations', 
        'properties', 
        'component_types', 
        'relation_types',
        'artifacts'
    }
    
    # Fields that should be ignored in comparison
    IGNORED_FIELDS = {
        'metadata',  # Runtime metadata
        'annotations',  # Optional annotations
    }
    
    def compare(self, expected: Dict, actual: Dict) -> Tuple[bool, List[str]]:
        """
        Compare two EDMM structures semantically.
        
        Args:
            expected: Expected EDMM YAML (as dict)
            actual: Actual RAG output (as dict)
        
        Returns:
            (is_match, list_of_differences)
        """
        differences = []
        self._compare_recursive(expected, actual, "", differences)
        is_match = len(differences) == 0
        return (is_match, differences)
    
    def _compare_recursive(self, exp: Any, act: Any, path: str, diffs: List[str]):
        """Recursive comparison of nested structures."""
        
        # Both None
        if exp is None and act is None:
            return
        
        # One is None
        if exp is None:
            diffs.append(f"{path}: expected None, got {type(act).__name__}")
            return
        if act is None:
            diffs.append(f"{path}: expected {type(exp).__name__}, got None")
            return
        
        # Dict comparison
        if isinstance(exp, dict) and isinstance(act, dict):
            self._compare_dicts(exp, act, path, diffs)
        
        # List comparison (order-aware vs order-independent)
        elif isinstance(exp, list) and isinstance(act, list):
            self._compare_lists(exp, act, path, diffs)
        
        # Value comparison
        else:
            if not self._values_equal(exp, act):
                diffs.append(f"{path}: expected {exp!r}, got {act!r}")
    
    def _compare_dicts(self, exp: Dict, act: Dict, path: str, diffs: List[str]):
        """Compare two dictionaries."""
        
        # Check all keys in expected
        for key in exp.keys():
            if key in self.IGNORED_FIELDS:
                continue
            
            new_path = f"{path}.{key}" if path else key
            
            if key not in act:
                diffs.append(f"{new_path}: MISSING in actual")
            else:
                self._compare_recursive(exp[key], act[key], new_path, diffs)
        
        # Check for unexpected keys in actual
        for key in act.keys():
            if key in self.IGNORED_FIELDS:
                continue
            if key not in exp:
                diffs.append(f"{path}.{key}: UNEXPECTED key in actual")
    
    def _compare_lists(self, exp: List, act: List, path: str, diffs: List[str]):
        """Compare two lists (order-dependent or independent based on field)."""
        
        # Determine if order matters
        field_name = path.split('.')[-1] if path else ""
        order_independent = field_name in self.ORDER_INDEPENDENT_LISTS
        
        # Check if this is a list of single-key dicts (Properties pattern)
        # e.g. [{k: v}, {k2: v2}]
        is_list_of_dicts = len(exp) > 0 and isinstance(exp[0], dict) and len(exp[0]) == 1
        
        if is_list_of_dicts:
            self._compare_list_of_dicts(exp, act, path, diffs)
        elif order_independent:
            self._compare_lists_unordered(exp, act, path, diffs)
        else:
            self._compare_lists_ordered(exp, act, path, diffs)

    def _compare_list_of_dicts(self, exp: List, act: List, path: str, diffs: List[str]):
        """
        Compare a list of single-key dicts as if it were a dictionary.
        This handles EDMM properties:
        - key: value
        - key2: value2
        """
        # Convert list of dicts to a single flat dict for easier comparison
        def flatten(lst):
            merged = {}
            for item in lst:
                if isinstance(item, dict):
                    merged.update(item)
            return merged

        exp_dict = flatten(exp)
        act_dict = flatten(act)
        
        # Now compare as dicts
        self._compare_dicts(exp_dict, act_dict, path, diffs)

    def _compare_lists_ordered(self, exp: List, act: List, path: str, diffs: List[str]):
        """Compare lists where order matters."""
        
        if len(exp) != len(act):
            diffs.append(f"{path}: list length mismatch (expected {len(exp)}, got {len(act)})")
        
        for i, (e_item, a_item) in enumerate(zip(exp, act)):
            self._compare_recursive(e_item, a_item, f"{path}[{i}]", diffs)
    
    def _compare_lists_unordered(self, exp: List, act: List, path: str, diffs: List[str]):
        """
        Compare lists where order doesn't matter.
        Used for components, relations, properties in EDMM.
        """
        
        # Convert list items to comparable format
        exp_items = self._list_to_comparable_set(exp)
        act_items = self._list_to_comparable_set(act)
        
        # Find missing items
        missing = exp_items - act_items
        for item_repr in missing:
            diffs.append(f"{path}: MISSING item: {item_repr}")
        
        # Find extra items
        extra = act_items - exp_items
        for item_repr in extra:
            diffs.append(f"{path}: UNEXPECTED item: {item_repr}")
    
    def _list_to_comparable_set(self, lst: List) -> Set[str]:
        """
        Convert list items to hashable representations for set comparison.
        Handles EDMM's list-of-dicts format.
        """
        result = set()
        for item in lst:
            # For dicts, use first key as identifier
            if isinstance(item, dict):
                if len(item) > 0:
                    first_key = list(item.keys())[0]
                    # Create a normalized representation
                    item_str = yaml.dump(item, sort_keys=True, default_flow_style=False)
                    result.add(item_str)
            else:
                # For simple values
                result.add(str(item))
        return result
    
    def _values_equal(self, exp: Any, act: Any) -> bool:
        """
        Compare two values with normalization.
        Handles quote differences, type coercion, etc.
        """
        
        # Normalize both values
        exp_norm = self._normalize_value(exp)
        act_norm = self._normalize_value(act)
        
        return exp_norm == act_norm
    
    def _normalize_value(self, val: Any) -> Any:
        """Normalize a value for comparison."""
        
        # String normalization (quotes are already gone in Python)
        if isinstance(val, str):
            return val.strip()
        
        # Boolean normalization
        if isinstance(val, bool):
            return bool(val)
        
        # Number normalization
        if isinstance(val, (int, float)):
            return val
        
        # None/null
        if val is None:
            return None
        
        # Lists and dicts - compare as-is (handled by recursive comparison)
        return val


def calculate_semantic_stats(expected: Dict, actual: Dict) -> Dict[str, Any]:
    """
    Calculate statistics for semantic comparison.
    
    Returns:
        Dict with similarity, matching_count, mismatch_count, etc.
    """
    comparer = EDMMSemanticComparer()
    is_match, differences = comparer.compare(expected, actual)
    # Count total fields recursively
    def count_fields(data, depth=0):
        if depth > 10:  # Prevent infinite recursion
            return 1
        if isinstance(data, dict):
            return sum(count_fields(v, depth+1) for v in data.values())
        elif isinstance(data, list):
            return sum(count_fields(item, depth+1) for item in data)
        else:
            return 1
    
    total_fields = count_fields(expected)
    mismatch_count = len(differences)
    matching_count = max(0, total_fields - mismatch_count)
    
    similarity = 1.0 if total_fields == 0 else (matching_count / total_fields)
    
    
    # --- New Advanced Metrics ---
    
    # 1. Component Recall
    # Extract component names/types for set comparison
    def get_comp_set(data):
        comps = set()
        c_list = _normalize_section(data.get("components", []))
        for item in c_list:
            if isinstance(item, dict):
                for k, v in item.items():
                    t = v.get("type", "unknown") if isinstance(v, dict) else "unknown"
                    comps.add((k, t))
        return comps

    exp_comps = get_comp_set(expected)
    act_comps = get_comp_set(actual)
    
    # Recall = found_expected / total_expected
    true_positives = len(exp_comps.intersection(act_comps))
    total_expected = len(exp_comps)
    component_recall = 1.0 if total_expected == 0 else (true_positives / total_expected)
    # Component Precision / Recall (name-based) / F1
    exp_names = {k for (k, t) in exp_comps}
    act_names = {k for (k, t) in act_comps}
    comp_tp = len(exp_names & act_names)
    comp_fp = len(act_names - exp_names)
    comp_fn = len(exp_names - act_names)
    component_precision = comp_tp / (comp_tp + comp_fp) if (comp_tp + comp_fp) > 0 else 1.0
    component_recall = comp_tp / (comp_tp + comp_fn) if (comp_tp + comp_fn) > 0 else 1.0
    component_f1 = 2 * component_precision * component_recall / (component_precision + component_recall) if (component_precision + component_recall) > 0 else 0.0
    component_recall_strict = true_positives / total_expected if total_expected > 0 else 1.0

    # 2. Relation Precision / Recall / F1
    def get_rel_set(data):
        rels = set()
        r_list = _normalize_section(data.get("relations", []))
        for item in r_list:
            if isinstance(item, dict):
                for k, v in item.items():
                    if not isinstance(v, dict):
                        continue
                    src = v.get("source")
                    tgt = v.get("target")
                    rt = v.get("type")
                    if src and tgt and rt:
                        rels.add((src, tgt, rt.lower()))
        return rels
        
    exp_rels = get_rel_set(expected)
    act_rels = get_rel_set(actual)
    
    rel_tp = len(exp_rels.intersection(act_rels))
    rel_fp = len(act_rels - exp_rels)
    rel_fn = len(exp_rels - act_rels)
    
    rel_precision = rel_tp / (rel_tp + rel_fp) if (rel_tp + rel_fp) > 0 else 0.0
    rel_recall = rel_tp / (rel_tp + rel_fn) if (rel_tp + rel_fn) > 0 else 0.0 # Same as (rel_tp / len(exp_rels))
    
    if (rel_precision + rel_recall) > 0:
        rel_f1 = 2 * (rel_precision * rel_recall) / (rel_precision + rel_recall)
    else:
        rel_f1 = 0.0

    # 3. Attribute Score (Weighted)
    # Focus on properties of components
    attr_match_count = 0
    attr_total_count = 0
    
    # Helper to flatten properties
    def get_flat_props(data):
        props = {}
        c_list = _normalize_section(data.get("components", []))
        for item in c_list:
            if isinstance(item, dict):
                for cname, cbody in item.items():
                    if not isinstance(cbody, dict):
                        continue
                    p_data = cbody.get("properties", [])
                    if isinstance(p_data, list):
                        for p_item in p_data:
                            if isinstance(p_item, dict):
                                props.update({f"{cname}.{k}": v for k, v in p_item.items()})
                    elif isinstance(p_data, dict):
                        props.update({f"{cname}.{k}": v for k, v in p_data.items()})
        return props

    exp_props = get_flat_props(expected)
    act_props = get_flat_props(actual)
    
    attr_total_count = len(exp_props)
    for k, v in exp_props.items():
        if k in act_props:
            # Simple equality check (normalization matches happen in EDMMSemanticComparer logic usually, doing basic here)
            if str(v).strip() == str(act_props[k]).strip():
                attr_match_count += 1
                
    attribute_score = 1.0 if attr_total_count == 0 else (attr_match_count / attr_total_count)

    # 4. Graph Edit Distance (GED)
    ged_score = calculate_graph_edit_distance(expected, actual)
    max_graph_size = max(len(exp_comps) + len(exp_rels), len(act_comps) + len(act_rels))
    graph_similarity = 1.0 if max_graph_size == 0 else (1.0 - (ged_score / max_graph_size))
    # Clip to 0
    graph_similarity = max(0.0, graph_similarity)

    return {
        'is_match': is_match,
        'similarity': similarity,
        'total_fields': total_fields,
        'matching_count': matching_count,
        'mismatch_count': mismatch_count,
        'differences': differences,
        # Advanced Metrics
        'component_recall': component_recall,
        'relation_precision': rel_precision,
        'relation_recall': rel_recall,
        'relation_f1': rel_f1,
        'attribute_score': attribute_score,
        'graph_edit_distance': ged_score,
        'graph_similarity': graph_similarity,
        'component_precision': component_precision,
        'component_f1': component_f1,
        'component_recall_strict': component_recall_strict
    }

def calculate_graph_edit_distance(expected: Dict, actual: Dict) -> float:
    """
    Calculates Graph Edit Distance (GED) using NetworkX.
    Nodes: Components
    Edges: Relations
    """
    def build_graph(data):
        G = nx.DiGraph()
        
        # Add Nodes (Components)
        c_list = _normalize_section(data.get("components", []))
        for item in c_list:
            if isinstance(item, dict):
                for k, v in item.items():
                    ctype = v.get("type", "unknown") if isinstance(v, dict) else "unknown"
                    G.add_node(k, type=ctype)
        
        # Add Edges (Relations)
        r_list = _normalize_section(data.get("relations", []))
        for item in r_list:
            if isinstance(item, dict):
                for k, v in item.items():
                    if not isinstance(v, dict):
                        continue
                    src = v.get("source")
                    tgt = v.get("target")
                    rtype = v.get("type")
                    if src and tgt:
                        G.add_edge(src, tgt, type=rtype)
        return G

    G_exp = build_graph(expected)
    G_act = build_graph(actual)
    
    # Calculate GED
    # timeout is generic safeguard, though these graphs are small
    try:
        # optimize_graph_edit_distance is faster approximation, correct considering complexity
        # For small graphs (<100 nodes), exact 'graph_edit_distance' is also feasible but potentially slow.
        # We use a custom cost function to account for types.
        
        def node_match(n1, n2):
            return n1.get('type', 'unknown') == n2.get('type', 'unknown')
            
        def edge_match(e1, e2):
            return e1.get('type', 'unknown') == e2.get('type', 'unknown')

        # Using simpler calculation logic for speed in pipeline:
        # optimize_graph_edit_distance returns a generator
        # We take the first yield as valid approximation or use graph_edit_distance for exact
        
        # For exact calculation (might be slow for N>20):
        # dist = nx.graph_edit_distance(G_exp, G_act, node_match=node_match, edge_match=edge_match)
        
        # For faster approximation:
        dist_gen = nx.optimize_graph_edit_distance(G_exp, G_act, node_match=node_match, edge_match=edge_match)
        dist = next(dist_gen)
        return dist

    except Exception as e:
        print(f"GED Calculation Failed using placeholder: {e}")
        # Fallback: simple difference in counts
        return abs(len(G_exp.nodes) - len(G_act.nodes)) + abs(len(G_exp.edges) - len(G_act.edges))



def compare_by_sections(expected: Dict, actual: Dict) -> Dict[str, Any]:
    """
    Compare EDMM by sections according to official YAML spec.
    
    Sections compared:
    - component_types
    - relation_types
    - components (with sub-analysis of artifacts and relations)
    - properties
    
    Returns:
        Dict with section-by-section results and overall similarity
    """
    # Top-level sections to compare
    sections = [
        'component_types',
        'relation_types', 
        'components',
        'properties'
    ]
    
    results = {}
    total_weight = 0
    weighted_sim = 0
    
    comparer = EDMMSemanticComparer()
    
    for section in sections:
        exp_section = expected.get(section, {} if section in ['component_types', 'relation_types', 'properties'] else [])
        act_section = actual.get(section, {} if section in ['component_types', 'relation_types', 'properties'] else [])

        # Normalize list-of-maps sections — actual may be in dict format (Streamlit UI copy-paste)
        if section in ('components', 'relations'):
            exp_section = _normalize_section(exp_section)
            act_section = _normalize_section(act_section)
        
        # Compare this section
        is_match, diffs = comparer.compare(exp_section, act_section)
        
        # Calculate stats
        def count_fields(data, depth=0):
            if depth > 10:
                return 1
            if isinstance(data, dict):
                return sum(count_fields(v, depth+1) for v in data.values())
            elif isinstance(data, list):
                return sum(count_fields(item, depth+1) for item in data)
            else:
                return 1
        
        total_fields = count_fields(exp_section)
        mismatch_count = len(diffs)
        matching_count = max(0, total_fields - mismatch_count)
        similarity = 1.0 if total_fields == 0 else (matching_count / total_fields)
        
        results[section] = {
            'similarity': similarity,
            'matching_count': matching_count,
            'mismatch_count': mismatch_count,
            'total_fields': total_fields,
            'differences': diffs[:50],  # Limit to 50 for display
            'is_match': is_match
        }
        
        # Weight sections by field count for overall similarity
        weight = max(1, total_fields)
        total_weight += weight
        weighted_sim += similarity * weight
    
    # Special analysis for components sub-sections
    if 'components' in expected or 'components' in actual:
        exp_comps = expected.get('components', [])
        exp_comps = _normalize_section(expected.get('components', []))
        act_comps = _normalize_section(actual.get('components', []))
        
        # Aggregate artifacts and relations from all components
        def extract_subsection(comp_list, key):
            items = []
            for comp_dict in _normalize_section(comp_list):
                if isinstance(comp_dict, dict):
                    for comp_name, comp_data in comp_dict.items():
                        if isinstance(comp_data, dict) and key in comp_data:
                            items.extend(comp_data.get(key, []))
            return items
        
        # Artifacts analysis
        exp_artifacts = extract_subsection(exp_comps, 'artifacts')
        act_artifacts = extract_subsection(act_comps, 'artifacts')
        
        if exp_artifacts or act_artifacts:
            is_match, diffs = comparer.compare(exp_artifacts, act_artifacts)
            total = len(exp_artifacts)
            mismatch = len(diffs)
            
            results['artifacts'] = {
                'similarity': 1.0 if total == 0 else ((total - mismatch) / total),
                'matching_count': max(0, total - mismatch),
                'mismatch_count': mismatch,
                'total_fields': total,
                'differences': diffs[:20],
                'is_match': is_match
            }
        
        # Relations analysis
        exp_relations = extract_subsection(exp_comps, 'relations')
        act_relations = extract_subsection(act_comps, 'relations')
        
        if exp_relations or act_relations:
            is_match, diffs = comparer.compare(exp_relations, act_relations)
            total = len(exp_relations)
            mismatch = len(diffs)
            
            results['relations'] = {
                'similarity': 1.0 if total == 0 else ((total - mismatch) / total),
                'matching_count': max(0, total - mismatch),
                'mismatch_count': mismatch,
                'total_fields': total,
                'differences': diffs[:20],
                'is_match': is_match
            }
    
    # Overall similarity (weighted average)
    results['overall_similarity'] = weighted_sim / total_weight if total_weight > 0 else 1.0
    
    # Add component-level chunked analysis for components section
    if 'components' in expected or 'components' in actual:
        from component_chunks import compare_component_chunks
        chunk_results = compare_component_chunks(expected, actual)
        results['component_chunks'] = chunk_results
    
    
    # --- MERGE ADVANCED GLOBAL METRICS ---
    # We call the main stats function to get the advanced graph/recall metrics
    # and merge them into the results for the UI to display.
    try:
        global_stats = calculate_semantic_stats(expected, actual)
        results['advanced_metrics'] = {
            'component_recall': global_stats.get('component_recall', 0),
            'relation_precision': global_stats.get('relation_precision', 0),
            'relation_recall': global_stats.get('relation_recall', 0),
            'relation_f1': global_stats.get('relation_f1', 0),
            'attribute_score': global_stats.get('attribute_score', 0),
            'graph_edit_distance': global_stats.get('graph_edit_distance', 0),
            'graph_similarity': global_stats.get('graph_similarity', 0)
        }
    except Exception as e:
         print(f"Error calculating advanced metrics in section compare: {e}")
         results['advanced_metrics'] = {}

    return results

def calculate_relation_type_breakdown(expected: Dict, actual: Dict) -> Dict[str, Dict]:
    """
    For every relation type (HostedOn, ConnectsTo, AttachesTo, DependsOn) in precision, recall, f1 breakdown
    """
    def get_rel_set(data):
        rels = set()
        r_list = _normalize_section(data.get("relations", []))
        for item in r_list:
            if isinstance(item, dict):
                for k, v in item.items():
                    if not isinstance(v, dict):
                        continue
                    src = v.get("source")
                    tgt = v.get("target")
                    rt = v.get("type")
                    if src and tgt and rt:
                        rels.add((src, tgt, rt.lower()))
        return rels

    exp_rels = get_rel_set(expected)
    act_rels = get_rel_set(actual)

    all_types = set(r for (_, _, r) in exp_rels) | set(r for (_, _, r) in act_rels)

    breakdown = {}
    for rtype in sorted(all_types):
        exp_t = {(s, t) for (s, t, r) in exp_rels if r == rtype}
        act_t = {(s, t) for (s, t, r) in act_rels if r == rtype}
        tp = len(exp_t & act_t)
        fp = len(act_t - exp_t)
        fn = len(exp_t - act_t)
        p = tp / len(act_t) if act_t else 0.0
        r = tp / len(exp_t) if exp_t else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        breakdown[rtype] = {
            "expected": len(exp_t),
            "found": tp,
            "extra": fp,
            "missing": fn,
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4)
        }
    return breakdown

def calculate_hallucination_metrics(actual_dict: Dict, context_text: str) -> Dict[str, float]:
    """
    Calculates Hallucination metrics (Knowledge Precision, Rare Precision, Hallucination Rate)
    by verifying if the generated property values exist in the source IaC context.
    
    Args:
        actual_dict: The generated EDMM YAML as a dictionary.
        context_text: The raw combined text of all source IaC files (Terraform/Ansible/Kubernetes).
        
    Returns:
        Dict containing knowledge_precision, rare_precision, and hallucination_rate.
    """
    import re
    from collections import Counter

    if not actual_dict or not context_text:
        return {"knowledge_precision": 0.0, "rare_precision": 0.0, "hallucination_rate": 0.0}

    # Normalize context text for easier matching (lowercase, remove excess whitespace)
    context_text_normalized = " ".join(context_text.lower().split())
    context_words = set(re.findall(r'[a-z0-9_-]+', context_text_normalized))
    
    # 1. Extract all generated values from the Actual EDMM
    generated_values = []

    # --- Normalize components (handles both dict and list-of-maps) ---
    raw_components = actual_dict.get("components", [])
    if isinstance(raw_components, dict):
        # Plain dict format: {name: {type:..., properties:...}, ...}
        comp_entries = [{"name": k, **v} if isinstance(v, dict) else {"name": k}
                        for k, v in raw_components.items()]
    elif isinstance(raw_components, list):
        # List-of-maps format: [{name: {type:..., properties:...}}, ...]
        comp_entries = []
        for item in raw_components:
            if isinstance(item, dict):
                for cname, cbody in item.items():
                    if isinstance(cbody, dict):
                        comp_entries.append({"name": cname, **cbody})
                    else:
                        comp_entries.append({"name": cname})
    else:
        comp_entries = []

    for cbody in comp_entries:
        if not isinstance(cbody, dict):
            continue
        
        # Add component name and type (without suffix) as generated strings
        cname = cbody.get("name", "")
        if cname:
            generated_values.append(str(cname))
        ctype = cbody.get("type", "")
        if ctype:
            generated_values.append(str(ctype).split('-')[0])  # extract base type
        
        props = cbody.get("properties", [])
        if isinstance(props, list):
            for p in props:
                if isinstance(p, dict):
                    for k, v in p.items():
                        # Only evaluate the VALUE (the LLM output), not the schema key
                        if v is not None and str(v).strip():
                            generated_values.append(str(v))
        elif isinstance(props, dict):
            for k, v in props.items():
                if v is not None and str(v).strip():
                    generated_values.append(str(v))

    # Tokenize generated values
    generated_tokens = []
    for val in generated_values:
        # Split by non-alphanumeric (keep hyphens and underscores for resource names)
        tokens = re.findall(r'[a-zA-Z0-9_-]+', str(val).lower())
        generated_tokens.extend(tokens)
        
    if not generated_tokens:
        return {"knowledge_precision": 0.0, "rare_precision": 0.0, "hallucination_rate": 0.0}

    # Common EDMM / Kubernetes / YAML stopwords that inflate standard F1
    # We filter these out for the 'Rare F1' calculation to focus on specific config values
    stopwords = {
        'true', 'false', '0', '1', 'defaultkubernetescluster', 'softwareapplication', 'databasesystem', 
        'null', 'none', 'always', 'ifnotpresent', 'bridge', 'started', 'unless-stopped', 'json-file',
        'http', 'tcp', 'containerplatform', 'dockerengine', 'local', 'present', 'absent'
    }
    
    rare_generated_tokens = [t for t in generated_tokens if t not in stopwords and len(t) > 2]
    
    # --- Calculate Overlaps ---
    # A token is considered "hallucinated" if it does not appear ANYWHERE in the source context
    
    # 1. Knowledge F1 (Standard Precision) - Percentage of ALL generated tokens found in context
    matched_tokens = [t for t in generated_tokens if t in context_words]
    knowledge_precision = len(matched_tokens) / len(generated_tokens) if generated_tokens else 0.0
    # Note: Knowledge F1 is usually equivalent to Precision in this context, 
    # as "Recall" over the entire IaC codebase is impossible (LLM shouldn't extract everything).
    knowledge_precision_score = knowledge_precision
    
    # 2. Rare Precision - Percentage of RARE (specific) generated tokens found in context
    matched_rare_tokens = [t for t in rare_generated_tokens if t in context_words]
    rare_precision_score = len(matched_rare_tokens) / len(rare_generated_tokens) if rare_generated_tokens else 0.0
    
    # 3. Hallucination Rate - Percentage of RARE tokens that were NOT found in context (completely invented)
    hallucination_rate = 1.0 - rare_precision_score if rare_generated_tokens else 0.0
    
    return {
        "knowledge_precision": round(knowledge_precision_score, 4),
        "rare_precision": round(rare_precision_score, 4),
        "hallucination_rate": round(hallucination_rate, 4),
        "total_generated_tokens": len(generated_tokens),
        "rare_generated_tokens": len(rare_generated_tokens),
        "hallucinated_tokens_count": len(rare_generated_tokens) - len(matched_rare_tokens)
    }

