import argparse
import sys
import os
import yaml
from pathlib import Path
import networkx as nx

from edmm_semantic_compare import calculate_semantic_stats, compare_by_sections, calculate_hallucination_metrics

def load_yaml(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
             return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        sys.exit(1)

def load_context_dir(dir_path):
    if not os.path.exists(dir_path):
        print(f"Warning: Context directory '{dir_path}' not found. Hallucination metrics will be 0.")
        return ""
    
    text_content = []
    p = Path(dir_path)
    for ext in ["*.yaml", "*.yml", "*.tf", "*.hcl", "*.tfvars"]:
        for f_path in p.rglob(ext):
            if f_path.is_file():
                try:
                    text_content.append(f_path.read_text(encoding="utf-8", errors="ignore"))
                except:
                    pass
    return "\n".join(text_content)

def _normalize_section(raw):
    """
    Normalize a section (components, relations, etc.) to list-of-maps format.
    
    The Streamlit UI reformatting step converts list-of-maps → plain dict:
      {name: {type: ...}, ...}
    But the evaluator expects list-of-maps:
      [{name: {type: ...}}, ...]
    
    This function handles both formats so copy-pasted YAML from the UI
    is evaluated correctly.
    """
    if isinstance(raw, dict):
        return [{k: v} for k, v in raw.items()]
    if isinstance(raw, list):
        return raw
    return []

def build_graph(data):
    G = nx.DiGraph()
    comps = _normalize_section(data.get("components", []))
    for item in comps:
        if isinstance(item, dict):
            for k, v in item.items():
                vtype = v.get("type", "unknown") if isinstance(v, dict) else "unknown"
                G.add_node(k, type=vtype)
    
    rels = _normalize_section(data.get("relations", []))
    for item in rels:
        if isinstance(item, dict):
            for k, v in item.items():
                if not isinstance(v, dict):
                    continue
                src = v.get("source")
                tgt = v.get("target")
                if src and tgt:
                    G.add_edge(src, tgt, type=v.get("type", "unknown"))
    return G


def print_structural_diffs(expected, actual):
    G_exp = build_graph(expected)
    G_act = build_graph(actual)

    missing_nodes = set(G_exp.nodes()) - set(G_act.nodes())
    extra_nodes = set(G_act.nodes()) - set(G_exp.nodes())
    
    missing_edges = set(G_exp.edges()) - set(G_act.edges())
    extra_edges = set(G_act.edges()) - set(G_exp.edges())

    print("\n--- Structural Diagnostics (GED View) ---")
    
    if missing_nodes: 
        print(f"❌ Missing Nodes ({len(missing_nodes)}):")
        for n in sorted(missing_nodes): print(f"    - {n}")
        
    if extra_nodes: 
        print(f"⚠️ Extra Nodes ({len(extra_nodes)}):")
        for n in sorted(extra_nodes): print(f"    - {n}")
        
    if missing_edges: 
        print(f"❌ Missing Edges ({len(missing_edges)}):")
        for e in sorted(missing_edges): print(f"    - {e[0]} -> {e[1]}")
        
    if extra_edges: 
        print(f"⚠️ Extra Edges ({len(extra_edges)}):")
        for e in sorted(extra_edges): print(f"    - {e[0]} -> {e[1]}")
    
    common_nodes = set(G_exp.nodes()).intersection(set(G_act.nodes()))
    type_mismatches = 0
    for n in common_nodes:
        t_exp = G_exp.nodes[n].get('type')
        t_act = G_act.nodes[n].get('type')
        if t_exp != t_act:
            type_mismatches += 1
            print(f"⚠️ Type Mismatch for node '{n}': Expected '{t_exp}', Got '{t_act}'")
    
    if type_mismatches == 0 and not missing_nodes and not extra_nodes and not missing_edges and not extra_edges:
        print("✅ Graph Structures Match Perfectly!")

def run_evaluation(expected_path, actual_path, context_dir=None):
    expected = load_yaml(expected_path)
    actual = load_yaml(actual_path)

    print(f"\nEvaluating:\n  Expected: {expected_path}\n  Actual:   {actual_path}")

    # 1. Structural Diagnostics
    print_structural_diffs(expected, actual)

    # 2. Semantic Stats (Advanced RAG Metrics)
    stats = calculate_semantic_stats(expected, actual)
    
    print("\n--- EDMM Structural Metrics ---")
    print(f"Graph Edit Distance: {stats['graph_edit_distance']}")
    print(f"Graph Similarity:    {stats['graph_similarity']*100:.1f}%")
    print(f"Component Recall:    {stats['component_recall']*100:.1f}%")
    print(f"Relation Precision:  {stats['relation_precision']*100:.1f}%")
    print(f"Relation Recall:     {stats['relation_recall']*100:.1f}%")
    print(f"Relation F1 Score:   {stats['relation_f1']*100:.1f}%")
    print(f"Attribute Score:     {stats['attribute_score']*100:.1f}%")

    # 3. Hallucination Metrics
    if context_dir:
        print("\n--- Hallucination Metrics ---")
        context_text = load_context_dir(context_dir)
        hal_metrics = calculate_hallucination_metrics(actual, context_text)
        
        print(f"Knowledge Precision: {hal_metrics['knowledge_precision']*100:.1f}%  (Overlap of all output with IaC Context)")
        print(f"Rare Precision:      {hal_metrics['rare_precision']*100:.1f}%  (Overlap of specific config values with IaC Context)")
        print(f"Hallucination Rate:  {hal_metrics['hallucination_rate']*100:.1f}%  (Percentage of specific values COMPLETELY INVENTED)")
        print(f"  -> Total Generated Tokens: {hal_metrics.get('total_generated_tokens', 'N/A')}")
        print(f"  -> Specific/Rare Tokens:   {hal_metrics.get('rare_generated_tokens', 'N/A')}")
        print(f"  -> Hallucinated Tokens:    {hal_metrics.get('hallucinated_tokens_count', 'N/A')}")
    else:
         print("\nℹ️ Pass --context_dir to calculate Hallucination Metrics (Knowledge Precision / Rare Precision).")

    # 4. Overall Match
    print("\n--- Overall Summary ---")
    if stats['is_match']:
        print("🌟 PERFECT MATCH! The actual EDMM YAML is semantically identical to the expected.")
    else:
        print(f"❌ MISMATCH: Found {stats['mismatch_count']} differences out of {stats['total_fields']} fields.")
        print("\nTop 10 Differences:")
        print(f"  {'FIELD':<45} {'EXPECTED':<40} {'ACTUAL'}")
        print(f"  {'-'*45} {'-'*40} {'-'*40}")
        import pprint
        import ast

        def _format_val(val_str):
            # Attempt to parse back to python object to pretty-print
            try:
                # safe_eval the string representation
                obj = ast.literal_eval(val_str)
                # Pretty print with 2 space indent
                return pprint.pformat(obj, indent=2, width=80)
            except:
                return str(val_str).strip()

        for d in stats['differences'][:10]:
            # d is a string like "some.field.path: expected <val>, got <val>"
            # or "some.field: UNEXPECTED key in actual"
            # or "some.field: (ENTIRE COMPONENT MISSING) - MISSING"
            if ": expected " in d and ", got " in d:
                path_part, rest = d.split(": expected ", 1)
                if ", got " in rest:
                    exp_part, act_part = rest.split(", got ", 1)
                else:
                    exp_part, act_part = rest, "?"
            elif ": UNEXPECTED key in actual" in d:
                path_part = d.replace(": UNEXPECTED key in actual", "")
                exp_part = "(not expected)"
                act_part = "UNEXPECTED KEY"
            elif "MISSING" in d:
                path_part = d.split(":")[0]
                exp_part = "(should exist)"
                act_part = "MISSING"
            else:
                # Fallback: truncate raw string
                print(f"  {str(d)[:120]}")
                continue
            
            # Format
            exp_formatted = _format_val(exp_part)
            act_formatted = _format_val(act_part)
            
            # If standard short string, print inline
            if "\n" not in exp_formatted and "\n" not in act_formatted and len(exp_formatted) < 40 and len(act_formatted) < 40:
                print(f"  {path_part:<44} {exp_formatted:<39} {act_formatted}")
            else:
                # If complex dict/list, print block-style with line limits
                max_lines = 15
                print(f"  {path_part}:")
                
                print("    EXPECTED:")
                exp_lines = exp_formatted.splitlines()
                for line in exp_lines[:max_lines]:
                    print(f"      {line}")
                if len(exp_lines) > max_lines:
                    print(f"      ... [{len(exp_lines) - max_lines} more lines omitted]")
                    
                print("    ACTUAL:")
                act_lines = act_formatted.splitlines()
                for line in act_lines[:max_lines]:
                    print(f"      {line}")
                if len(act_lines) > max_lines:
                    print(f"      ... [{len(act_lines) - max_lines} more lines omitted]")
                    
                print("  " + "-"*85)
                print("  " + "-"*85)

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate generated EDMM YAML against expected EDMM YAML.",
        epilog=(
            "Usage examples:\n"
            "  # Auto-detect mode for a specific case:\n"
            "  python evaluate.py --results_dir /app/Results --case ansible\n"
            "  # Auto-detect mode (any file matching actual*.yaml):\n"
            "  python evaluate.py --results_dir /app/Results\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("--results_dir", help="Directory containing target files.", default=None)
    parser.add_argument("--case", help="Specific case to match (e.g. 'ansible' finds actual_ansible.yaml)", default=None)
    parser.add_argument("expected_yaml", nargs="?", help="Path to expected YAML.")
    parser.add_argument("actual_yaml", nargs="?", help="Path to actual YAML.")
    parser.add_argument("--context_dir", help="Path to IaC dir for Hallucination Metrics.", default=None)

    args = parser.parse_args()

    if args.results_dir:
        results = Path(args.results_dir)
        if not results.is_dir():
            print(f"❌ Directory not found: {results}")
            sys.exit(1)

        # Match specific case if provided
        act_pattern = f"actual*{args.case}*.yaml" if args.case else "actual*.yaml"
        exp_pattern = f"expected*{args.case}*.yaml" if args.case else "expected*.yaml"
        
        act_cands = sorted(results.glob(act_pattern))
        exp_cands = sorted(results.glob(exp_pattern))

        if not act_cands:
            print(f"❌ No file matching '{act_pattern}' found in: {results}")
            sys.exit(1)
        if not exp_cands:
            print(f"❌ No file matching '{exp_pattern}' found in: {results}")
            sys.exit(1)

        actual_path = act_cands[0]
        expected_path = exp_cands[0]

        if len(act_cands) > 1:
            print(f"⚠️  Multiple actual files found, using: {actual_path.name}")
        if len(exp_cands) > 1:
            print(f"⚠️  Multiple expected files found, using: {expected_path.name}")

    elif args.expected_yaml and args.actual_yaml:
        expected_path = args.expected_yaml
        actual_path = args.actual_yaml
    else:
        parser.print_help()
        sys.exit(1)

    run_evaluation(str(expected_path), str(actual_path), context_dir=args.context_dir)

if __name__ == "__main__":
    main()
