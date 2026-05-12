import yaml
import sys
import os
import networkx as nx


script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from edmm_semantic_compare import calculate_graph_edit_distance, compare_by_sections

# Change line for cases
RESULTS_DIR   = "/app/project_folder/Results"
EXPECTED_FILE = os.path.join(RESULTS_DIR, "otelshopAnsible_expected.yaml")
ACTUAL_FILE   = os.path.join(RESULTS_DIR, "actual_ansible.yaml")


# Graph builder
def build_graph(data):
    G = nx.DiGraph()
    for item in data.get("components", []):
        if isinstance(item, dict):
            for k, v in item.items():
                ctype = v.get("type", "unknown") if isinstance(v, dict) else "unknown"
                G.add_node(k, type=ctype)
    for item in data.get("relations", []):
        if isinstance(item, dict):
            for k, v in item.items():
                if isinstance(v, dict):
                    src   = v.get("source")
                    tgt   = v.get("target")
                    rtype = v.get("type", "")
                    if src and tgt:
                        G.add_edge(src, tgt, type=rtype)
    return G


# 1) GED + Node/Edge diff
def run_ged_analysis(exp_data, act_data):
    G_exp = build_graph(exp_data)
    G_act = build_graph(act_data)

    exp_nodes = set(G_exp.nodes())
    act_nodes = set(G_act.nodes())
    exp_edges = set((u, v, d["type"]) for u, v, d in G_exp.edges(data=True))
    act_edges = set((u, v, d["type"]) for u, v, d in G_act.edges(data=True))

    print("\n" + "=" * 70)
    print("  GED ANALYSIS - GRAPH STRUCTURE COMPARISON")
    print("=" * 70)

    missing_nodes = exp_nodes - act_nodes
    extra_nodes   = act_nodes - exp_nodes
    missing_edges = exp_edges - act_edges
    extra_edges   = act_edges - exp_edges

    print(f"\n[NODES]  Expected: {len(exp_nodes)}  |  Generated: {len(act_nodes)}")
    print(f"  Missing ({len(missing_nodes)}): " + (", ".join(sorted(missing_nodes)) if missing_nodes else "-"))
    print(f"  Extra   ({len(extra_nodes)}):  " + (", ".join(sorted(extra_nodes))   if extra_nodes   else "-"))

    print(f"\n[EDGES]  Expected: {len(exp_edges)}  |  Generated: {len(act_edges)}")
    if missing_edges:
        print(f"  Missing Edges ({len(missing_edges)}):")
        for u, v, t in sorted(missing_edges):
            print(f"    - {u} --[{t}]--> {v}")
    else:
        print("  Missing Edges: -")

    if extra_edges:
        print(f"  Extra Edges ({len(extra_edges)}):")
        for u, v, t in sorted(extra_edges):
            print(f"    - {u} --[{t}]--> {v}")
    else:
        print("  Extra Edges: -")

    # Type mismatches
    mismatches = [(n, G_exp.nodes[n].get("type", "unknown"), G_act.nodes[n].get("type", "unknown"))
                  for n in exp_nodes & act_nodes
                  if G_exp.nodes[n].get("type", "unknown") != G_act.nodes[n].get("type", "unknown")]
    if mismatches:
        print(f"\n[TYPE MISMATCHES] ({len(mismatches)}):")
        for n, et, at in mismatches:
            print(f"    {n}: expected '{et}', generated '{at}'")
    else:
        print("\n[TYPE MISMATCHES]: -")

    # GED score
    def node_match(n1, n2): return n1.get("type", "unknown") == n2.get("type", "unknown")
    def edge_match(e1, e2): return e1.get("type", "unknown") == e2.get("type", "unknown")

    print("\n[GED CALCULATION] NetworkX optimize_graph_edit_distance ...")
    try:
        dist = next(nx.optimize_graph_edit_distance(G_exp, G_act, node_match=node_match, edge_match=edge_match))
        print(f"  => GED Score: {dist}")
    except Exception as e:
        fallback = len(missing_nodes) + len(extra_nodes) + len(missing_edges) + len(extra_edges)
        print(f"  => Could not calculate GED ({e}), fallback (node+edge diff): {fallback}")

    print(f"\n  Estimated impact (diff count only): "
          f"node diff={len(missing_nodes)+len(extra_nodes)}, "
          f"edge diff={len(missing_edges)+len(extra_edges)}, "
          f"total={len(missing_nodes)+len(extra_nodes)+len(missing_edges)+len(extra_edges)}")


# 2) Section-by-section
def run_section_analysis(exp_data, act_data):
    print("\n" + "=" * 70)
    print("  SECTION-BY-SECTION COMPARISON")
    print("=" * 70)

    results = compare_by_sections(exp_data, act_data)

    sections = ["component_types", "relation_types", "components", "properties", "artifacts", "relations"]
    for sec in sections:
        if sec not in results:
            continue
        s = results[sec]
        sim  = s.get("similarity", 0) * 100
        mm   = s.get("mismatch_count", 0)
        tot  = s.get("total_fields", 0)
        ok   = s.get("matching_count", 0)
        print(f"\n  [{sec.upper()}]  Similarity: {sim:.1f}%  |  Matched: {ok}  |  Mismatched: {mm}  |  Total: {tot}")
        diffs = s.get("differences", [])
        if diffs:
            print(f"    Differences (first 10):")
            for d in diffs[:10]:
                print(f"      {d}")

    adv = results.get("advanced_metrics", {})
    if adv:
        print("\n" + "=" * 70)
        print("  ADVANCED METRICS")
        print("=" * 70)
        print(f"  Component Recall  : {adv.get('component_recall', 0)*100:.1f}%")
        print(f"  Relation Precision: {adv.get('relation_precision', 0)*100:.1f}%")
        print(f"  Relation Recall   : {adv.get('relation_recall', 0)*100:.1f}%")
        print(f"  Relation F1       : {adv.get('relation_f1', 0)*100:.1f}%")
        print(f"  Attribute Score   : {adv.get('attribute_score', 0)*100:.1f}%")
        print(f"  Graph Edit Dist.  : {adv.get('graph_edit_distance', 0)}")
        print(f"  Graph Similarity  : {adv.get('graph_similarity', 0)*100:.1f}%")

    print(f"\n  OVERALL SIMILARITY: {results.get('overall_similarity', 0)*100:.1f}%")


# MAIN
if __name__ == "__main__":
    print(f"Expected file: {EXPECTED_FILE}")
    print(f"Generated file: {ACTUAL_FILE}")

    with open(EXPECTED_FILE, "r", encoding="utf-8") as f:
        exp_data = yaml.safe_load(f)
    with open(ACTUAL_FILE, "r", encoding="utf-8") as f:
        act_data = yaml.safe_load(f)

    run_ged_analysis(exp_data, act_data)
    run_section_analysis(exp_data, act_data)
    print("\n" + "=" * 70)
    print("COMPLETED")
    print("=" * 70)
