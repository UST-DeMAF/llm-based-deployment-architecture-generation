"""
evaluate_semantic.py
====================
Semantic Evaluation of EDMM YAML outputs.

Unlike evaluate.py which does strict structural comparison, this script
evaluates whether the LLM *understood* the architecture correctly 

Usage:
  python evaluate_semantic.py --results_dir /app/project_folder/Results --case ansible
  python evaluate_semantic.py expected.yaml actual.yaml
"""

import argparse
import sys
import yaml
import re
from pathlib import Path
from typing import Dict, Set, List, Tuple


# Known synonym mappings  (actual_base_name -> canonical_base_name)
# Add more as the LLM shows new naming variants.

KNOWN_SYNONYMS: Dict[str, str] = {
    # OpenTelemetry collector
    "otelcol": "opentelemetry-collector-contrib",
    "opentelemetry-collector": "opentelemetry-collector-contrib",
    # Jaeger
    "jaeger": "all-in-one",
    "all-in-one": "all-in-one",
    # OpenSearch
    "opensearch": "opensearch",
    # Valkey / Redis compat
    "valkey": "valkey",
}

# These nodes are LLM phantoms - they should never appear in valid EDMM
PHANTOM_NODES: Set[str] = {
    "DefaultDockerEngine",
    "defaultdockerengine",
}

# EDMM type category suffixes (we strip these to get the base component name)
TYPE_SUFFIXES = [
    "-SoftwareApplication",
    "-DatabaseSystem",
    "-ContainerPlatform",
    "-DockerEngine",
    "-KubernetesCluster",
    "-MessageBroker",
    "-type",
]


# Helpers


def load_yaml(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _normalize_section(raw) -> List[Dict]:
    """Accept both list-of-maps and plain-dict formats for components/relations."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return [{k: v} for k, v in raw.items()]
    return []


def _strip_type_suffix(type_str: str) -> str:
    """Remove EDMM category suffix: 'jaeger-SoftwareApplication' → 'jaeger'"""
    for suf in TYPE_SUFFIXES:
        if type_str.endswith(suf):
            return type_str[: -len(suf)]
    return type_str


def _canonical(name: str) -> str:
    """Resolve a component base name to its canonical form.
    
    Applies two levels of normalization:
    1. KNOWN_SYNONYMS: explicit alias mappings (otelcol → opentelemetry-collector-contrib)
    2. Kebab → CamelCase collapse: strips dashes so 'ad-service' == 'adservice'
    """
    low = name.lower().strip()
    # Check explicit synonym map first (highest priority)
    if low in KNOWN_SYNONYMS:
        return KNOWN_SYNONYMS[low]
    # Kebab-case normalization: treat 'ad-service' and 'adservice' as identical
    # This handles IaC tools (Terraform, Ansible) that use kebab-case naming
    # while expected YAML may use camelCase or vice versa.
    nodash = low.replace("-", "")
    # If the no-dash form is in the synonym map, use that
    if nodash in KNOWN_SYNONYMS:
        return KNOWN_SYNONYMS[nodash]
    return nodash


def _is_phantom(name: str) -> bool:
    return name.lower() in {p.lower() for p in PHANTOM_NODES}


def _is_self_loop(src: str, tgt: str) -> bool:
    return src.lower() == tgt.lower()


# Component extraction

def get_component_map(data: Dict) -> Dict[str, str]:
    """
    Returns {component_name: component_type} for all components.
    Filters out phantom nodes.
    """
    result = {}
    c_list = _normalize_section(data.get("components", []))
    for item in c_list:
        if isinstance(item, dict):
            for k, v in item.items():
                if _is_phantom(k):
                    continue
                ctype = v.get("type", "unknown") if isinstance(v, dict) else "unknown"
                result[k] = ctype
    return result


def get_semantic_comp_set(comp_map: Dict[str, str]) -> Set[Tuple[str, str]]:
    """
    Returns a set of (canonical_name, canonical_type_base) tuples.
    Used for semantic comparison.
    """
    result = set()
    for name, ctype in comp_map.items():
        base_type = _strip_type_suffix(ctype)
        can_name = _canonical(name)
        can_type = _canonical(base_type)
        result.add((can_name, can_type))
    return result


# Relation extraction


def get_relation_set(data: Dict, normalize_docker: bool = True) -> Set:
    """
    Returns a set of (src, tgt, rel_type) tuples (normalized).

    Applies:
    - DefaultDockerEngine HostedOn → localhost normalization
    - Phantom node filtering
    - Kebab-case canonical normalization (ad-service == adservice)
    """
    rels: Set[Tuple[str, str, str]] = set()

    r_list = _normalize_section(data.get("relations", []))
    for item in r_list:
        if isinstance(item, dict):
            for k, v in item.items():
                if not isinstance(v, dict):
                    continue
                src = v.get("source", "")
                tgt = v.get("target", "")
                rt = v.get("type", "")

                if not (src and tgt and rt):
                    continue

                # Skip self-loops (source == target)
                if _is_self_loop(src, tgt):
                    continue

                # Normalize DefaultDockerEngine HostedOn → localhost
                if normalize_docker and tgt in PHANTOM_NODES and rt.lower() == "hostedon":
                    tgt = "localhost"

                # Skip edges from/to phantom nodes
                if _is_phantom(src) or _is_phantom(tgt):
                    continue

                # Apply canonical (kebab-stripped) normalization
                rels.add((_canonical(src), _canonical(tgt), rt.lower()))

    return rels


# Main evaluation

def run_semantic_evaluation(expected_path: str, actual_path: str):
    expected = load_yaml(expected_path)
    actual = load_yaml(actual_path)

    print(f"\nSemantic Evaluation:")
    print(f"  Expected: {expected_path}")
    print(f"  Actual:   {actual_path}")
    print("=" * 70)

    # --- 1. Component Semantic Analysis ---
    exp_comps = get_component_map(expected)
    act_comps = get_component_map(actual)

    exp_sem  = get_semantic_comp_set(exp_comps)
    act_sem  = get_semantic_comp_set(act_comps)

    # Exact name matches (case-insensitive)
    exp_names = {k.lower() for k in exp_comps}
    act_names = {k.lower() for k in act_comps}
    exact_name_matches = exp_names & act_names

    # Semantic matches (canonical name + type)
    sem_matches = exp_sem & act_sem
    
    # Naming variants: same canonical name but different type category
    exp_by_name = {can_name: can_type for (can_name, can_type) in exp_sem}
    act_by_name = {can_name: can_type for (can_name, can_type) in act_sem}
    
    naming_variants = []
    for can_name in set(exp_by_name) & set(act_by_name):
        if exp_by_name[can_name] != act_by_name[can_name]:
            naming_variants.append(
                f"  '{can_name}': expected type '{exp_by_name[can_name]}', got '{act_by_name[can_name]}'"
            )

    # Entirely missing components (semantic)
    missing_sem = exp_sem - act_sem
    extra_sem = act_sem - exp_sem

    # Component recall
    tp_exact = len(exact_name_matches)
    comp_recall = tp_exact / len(exp_names) if exp_names else 1.0
    sem_recall  = (len(exp_sem) - len(missing_sem)) / len(exp_sem) if exp_sem else 1.0

    print("\n--- Component Analysis ---")
    print(f"  Expected Components:     {len(exp_comps)}")
    print(f"  Actual Components:       {len(act_comps)}")
    print(f"  Exact Name Matches:      {tp_exact}  ({comp_recall*100:.1f}% recall)")
    print(f"  Semantic Type Matches:   {len(sem_matches)}  ({sem_recall*100:.1f}% semantic recall)")

    if naming_variants:
        print(f"\n  ⚠️  Naming Variants ({len(naming_variants)}) — same component, different type label:")
        for nv in naming_variants:
            print(nv)

    if missing_sem:
        truly_missing = [
            f"  '{cn}' (type: {ct})"
            for (cn, ct) in missing_sem
            if cn not in act_by_name  # Not even a naming variant
        ]
        if truly_missing:
            print(f"\n  ❌ Truly Missing Components ({len(truly_missing)}):")
            for tm in truly_missing:
                print(tm)

    phantom_comps = [c for c in act_comps if _is_phantom(c)]
    if phantom_comps:
        print(f"\n  🔴 Phantom Nodes in Actual ({len(phantom_comps)}):")
        for p in phantom_comps:
            print(f"     - {p}")

    # --- 2. Relation Semantic Analysis ---
    exp_rels = get_relation_set(expected, normalize_docker=False)
    act_rels = get_relation_set(actual, normalize_docker=True)

    rel_tp = exp_rels & act_rels
    rel_missing = exp_rels - act_rels
    rel_extra = act_rels - exp_rels

    precision = len(rel_tp) / len(act_rels) if act_rels else 1.0
    recall    = len(rel_tp) / len(exp_rels) if exp_rels else 1.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    print("\n--- Relation Analysis (Semantic, DefaultDockerEngine normalized) ---")
    print(f"  Expected Relations:      {len(exp_rels)}")
    print(f"  Actual Relations:        {len(act_rels)}")
    print(f"  Semantic Precision:      {precision*100:.1f}%")
    print(f"  Semantic Recall:         {recall*100:.1f}%")
    print(f"  Semantic F1:             {f1*100:.1f}%")

    if rel_missing:
        print(f"\n  ❌ Missing Relations ({len(rel_missing)}) — expected but not generated:")
        for (s, t, r) in sorted(rel_missing)[:15]:
            print(f"     {s} → {r} → {t}")
        if len(rel_missing) > 15:
            print(f"     ... [{len(rel_missing)-15} more omitted]")

    if rel_extra:
        print(f"\n  ⚠️  Extra Relations ({len(rel_extra)}) — generated but not expected:")
        for (s, t, r) in sorted(rel_extra)[:15]:
            print(f"     {s} → {r} → {t}")
        if len(rel_extra) > 15:
            print(f"     ... [{len(rel_extra)-15} more omitted]")

    # --- 3. Summary ---
    # Note: Hallucination metrics (Knowledge F1, Rare F1) are computed by
    # evaluate.py with --context_dir, which compares against actual source files.
    print("\n" + "=" * 70)
    print("SEMANTIC EVALUATION SUMMARY")
    print("=" * 70)
    print(f"  Component Recall (exact names):   {comp_recall*100:.1f}%")
    print(f"  Component Recall (semantic):      {sem_recall*100:.1f}%")
    print(f"  Relation Precision (semantic):    {precision*100:.1f}%")
    print(f"  Relation Recall (semantic):       {recall*100:.1f}%")
    print(f"  Relation F1 (semantic):           {f1*100:.1f}%")
    print(f"  Naming Variants (not errors):     {len(naming_variants)}")
    print("=" * 70)


# CLI

def main():
    parser = argparse.ArgumentParser(
        description="Semantic evaluation of generated EDMM YAML vs expected.",
        epilog=(
            "Usage examples:\n"
            "  python evaluate_semantic.py --results_dir /app/Results --case ansible\n"
            "  python evaluate_semantic.py expected.yaml actual.yaml\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--results_dir", default=None, help="Directory containing result files.")
    parser.add_argument("--case", default=None, help="Case name to match (e.g. 'ansible').")
    parser.add_argument("expected_yaml", nargs="?", help="Path to expected YAML.")
    parser.add_argument("actual_yaml", nargs="?", help="Path to actual YAML.")

    args = parser.parse_args()

    if args.results_dir:
        results = Path(args.results_dir)
        act_pattern = f"actual*{args.case}*.yaml" if args.case else "actual*.yaml"
        exp_pattern = f"expected*{args.case}*.yaml" if args.case else "expected*.yaml"

        act_cands = sorted(results.glob(act_pattern))
        exp_cands = sorted(results.glob(exp_pattern))

        if not act_cands:
            print(f"❌ No file matching '{act_pattern}' in: {results}")
            sys.exit(1)
        if not exp_cands:
            print(f"❌ No file matching '{exp_pattern}' in: {results}")
            sys.exit(1)

        actual_path   = str(act_cands[0])
        expected_path = str(exp_cands[0])

    elif args.expected_yaml and args.actual_yaml:
        expected_path = args.expected_yaml
        actual_path   = args.actual_yaml
    else:
        parser.print_help()
        sys.exit(1)

    run_semantic_evaluation(expected_path, actual_path)


if __name__ == "__main__":
    main()
