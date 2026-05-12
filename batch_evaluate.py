"""
batch_evaluate.py - Multiple-run evaluation with mean +/- prediction interval.

Based on the methodology from Blackwell et al. (2024):
  "Towards Reproducible LLM Evaluation: Quantifying Uncertainty in LLM
   Benchmark Scores"

Usage:
    python batch_evaluate.py --results_dir Results --num_runs 3
    python batch_evaluate.py --results_dir ResultsNoRAG --num_runs 3

"""

import argparse
import yaml
import numpy as np
import scipy.stats as stats
from pathlib import Path
from collections import defaultdict

from edmm_semantic_compare import calculate_semantic_stats, calculate_relation_type_breakdown, _normalize_section


CASES = ["kubernetes", "terraform", "ansible", "t2storemodulith", "meitrex", "t2storemicroservices", "boutiqueshop"]

METRICS_TO_TRACK = [
    "component_precision",
    "component_recall",         # name-based
    "component_recall_strict",  # name+type based
    "component_f1",
    "relation_precision",
    "relation_recall",
    "relation_f1",
    "attribute_score",
    "graph_similarity",
    "graph_edit_distance",
]


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def prediction_interval(samples, confidence=0.95):
    """
    95% prediction interval for a future mean over n samples.
    Source: Blackwell et al. (2024), Eq. 3.
    Returns: (lower_bound, upper_bound, margin_of_error)
    """
    if len(samples) < 2:
        return (samples[0] if samples else 0.0, samples[0] if samples else 0.0, 0.0)

    mean = np.mean(samples)
    std_dev = np.std(samples, ddof=1)  # sample standard deviation
    n = len(samples)
    t_crit = stats.t.ppf((1 + confidence) / 2, df=n - 1)
    margin_of_error = t_crit * std_dev * np.sqrt(2 / n)
    return (mean - margin_of_error, mean + margin_of_error, margin_of_error)


def evaluate_case(expected_path, actual_path):
    """Run evaluation for a single (expected, actual) pair and return metric dict."""
    expected = load_yaml(expected_path)
    actual = load_yaml(actual_path)
    return calculate_semantic_stats(expected, actual)


def evaluate_all_runs(results_dir: Path, num_runs: int):
    """
    For each case, for each metric, collect N scores across the N runs.
    Returns: nested dict {case: {metric: [score_run1, score_run2, ...]}}
    """
    per_case_metrics = defaultdict(lambda: defaultdict(list))

    for case in CASES:
        expected_path = results_dir / f"expected_{case}.yaml"
        if not expected_path.exists():
            print(f"[SKIP] expected file not found for case={case}: {expected_path}")
            continue

        for run_idx in range(1, num_runs + 1):
            actual_path = results_dir / f"run{run_idx}" / f"actual_{case}.yaml"
            if not actual_path.exists():
                print(f"[SKIP] actual file not found: {actual_path}")
                continue

            try:
                stats_dict = evaluate_case(expected_path, actual_path)
            except Exception as e:
                print(f"[ERROR] case={case} run={run_idx}: {e}")
                continue

            for metric in METRICS_TO_TRACK:
                val = stats_dict.get(metric)
                if val is not None:
                    per_case_metrics[case][metric].append(val)

    return per_case_metrics


def print_results(per_case_metrics):
    """Print mean +/- prediction interval margin for each (case, metric)."""
    print("\n" + "=" * 90)
    print(f"{'Case':<20} {'Metric':<25} {'Mean':>8} {'Std':>8} {'Margin':>8} {'N':>4}")
    print("=" * 90)

    for case, metrics_dict in per_case_metrics.items():
        for metric in METRICS_TO_TRACK:
            samples = metrics_dict.get(metric, [])
            if not samples:
                continue
            mean = np.mean(samples)
            std = np.std(samples, ddof=1) if len(samples) > 1 else 0.0
            _, _, margin = prediction_interval(samples)
            print(f"{case:<20} {metric:<25} {mean:>8.4f} {std:>8.4f} {margin:>8.4f} {len(samples):>4}")
        print("-" * 90)

    print("\n" + "=" * 90)
    print("AGGREGATE (mean across all cases, then mean across runs)")
    print("=" * 90)
    for metric in METRICS_TO_TRACK:
        all_samples = []
        for case in per_case_metrics:
            all_samples.extend(per_case_metrics[case].get(metric, []))
        if not all_samples:
            continue
        mean = np.mean(all_samples)
        std = np.std(all_samples, ddof=1) if len(all_samples) > 1 else 0.0
        _, _, margin = prediction_interval(all_samples)
        print(f"{'ALL':<20} {metric:<25} {mean:>8.4f} {std:>8.4f} {margin:>8.4f} {len(all_samples):>4}")


def print_relation_type_breakdown(results_dir: Path, num_runs: int):

    print("\n" + "=" * 90)
    print("RELATION TYPE BREAKDOWN (mean across runs)")
    print("=" * 90)

    for case in CASES:
        expected_path = results_dir / f"expected_{case}.yaml"
        if not expected_path.exists():
            continue

        type_scores = {}

        for run_idx in range(1, num_runs + 1):
            actual_path = results_dir / f"run{run_idx}" / f"actual_{case}.yaml"
            if not actual_path.exists():
                continue
            try:
                expected = load_yaml(expected_path)
                actual = load_yaml(actual_path)
                breakdown = calculate_relation_type_breakdown(expected, actual)
                for rtype, metrics in breakdown.items():
                    if rtype not in type_scores:
                        type_scores[rtype] = {"expected": [], "found": [], "extra": [], "missing": [], "precision": [], "recall": [], "f1": []}
                    for metric, val in metrics.items():
                        type_scores[rtype][metric].append(val)
            except Exception as e:
                print(f"[ERROR] case={case} run={run_idx}: {e}")
                continue

        if not type_scores:
            continue

        print(f"\n{'='*90}")
        print(f"Case: {case.upper()}")
        print(f"{'='*90}")
        print(f"  {'Type':<14} {'Expected':>9} {'Found':>7} {'Extra':>7} {'Missing':>9} {'P':>7} {'R':>7} {'F1':>7}")
        print(f"  {'-'*14} {'-'*9} {'-'*7} {'-'*7} {'-'*9} {'-'*7} {'-'*7} {'-'*7}")

        for rtype in sorted(type_scores.keys()):
            m = type_scores[rtype]
            exp_mean = np.mean(m["expected"]) if m["expected"] else 0
            found_mean = np.mean(m["found"]) if m["found"] else 0
            extra_mean = np.mean(m["extra"]) if m["extra"] else 0
            missing_mean = np.mean(m["missing"]) if m["missing"] else 0
            p_mean = np.mean(m["precision"]) if m["precision"] else 0
            r_mean = np.mean(m["recall"]) if m["recall"] else 0
            f1_mean = np.mean(m["f1"]) if m["f1"] else 0
            print(f"  {rtype:<14} {exp_mean:>9.1f} {found_mean:>7.1f} {extra_mean:>7.1f} {missing_mean:>9.1f} {p_mean*100:>6.1f}% {r_mean*100:>6.1f}% {f1_mean*100:>6.1f}%")

def print_global_relation_type_aggregate(results_dir: Path, num_runs: int):
    """
    Aggregate relation-type statistics across ALL cases.
    Shows which relation types are globally easier/harder to reconstruct.
    """

    print("\n" + "=" * 90)
    print("GLOBAL RELATION-TYPE AGGREGATE")
    print("=" * 90)

    global_scores = {}

    for case in CASES:
        expected_path = results_dir / f"expected_{case}.yaml"

        if not expected_path.exists():
            continue

        for run_idx in range(1, num_runs + 1):

            actual_path = results_dir / f"run{run_idx}" / f"actual_{case}.yaml"

            if not actual_path.exists():
                continue

            try:
                expected = load_yaml(expected_path)
                actual = load_yaml(actual_path)

                breakdown = calculate_relation_type_breakdown(expected, actual)

                for rtype, metrics in breakdown.items():

                    if rtype not in global_scores:
                        global_scores[rtype] = {
                            "precision": [],
                            "recall": [],
                            "f1": [],
                            "expected": [],
                            "found": [],
                            "extra": [],
                            "missing": []
                        }

                    for metric, val in metrics.items():
                        global_scores[rtype][metric].append(val)

            except Exception as e:
                print(f"[ERROR] case={case} run={run_idx}: {e}")

    print(f"\n{'Type':<14} {'Expected':>9} {'Found':>7} {'Extra':>7} {'Missing':>9} {'P':>7} {'R':>7} {'F1':>7}")
    print(f"{'-'*14} {'-'*9} {'-'*7} {'-'*7} {'-'*9} {'-'*7} {'-'*7} {'-'*7}")

    for rtype in sorted(global_scores.keys()):

        m = global_scores[rtype]

        exp_mean = np.mean(m["expected"]) if m["expected"] else 0
        found_mean = np.mean(m["found"]) if m["found"] else 0
        extra_mean = np.mean(m["extra"]) if m["extra"] else 0
        missing_mean = np.mean(m["missing"]) if m["missing"] else 0

        p_mean = np.mean(m["precision"]) if m["precision"] else 0
        r_mean = np.mean(m["recall"]) if m["recall"] else 0
        f1_mean = np.mean(m["f1"]) if m["f1"] else 0

        print(
            f"{rtype:<14} "
            f"{exp_mean:>9.1f} "
            f"{found_mean:>7.1f} "
            f"{extra_mean:>7.1f} "
            f"{missing_mean:>9.1f} "
            f"{p_mean*100:>6.1f}% "
            f"{r_mean*100:>6.1f}% "
            f"{f1_mean*100:>6.1f}%"
        )


def get_rel_set(data):
    """Extract relation set as (source, target, type) tuples."""
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

def get_comp_name_set(data):
    """Extract component names as a set."""
    comps = set()
    c_list = _normalize_section(data.get("components", []))
    for item in c_list:
        if isinstance(item, dict):
            for k, v in item.items():
                comps.add(k)
    return comps


def find_systematic_missing_components(results_dir: Path, num_runs: int):
    """
    For each case, identify components that are missing across runs.
    Systematic missing = missing in all runs.
    Occasional missing = missing in num_runs - 1 runs.
    """
    print("\n" + "=" * 90)
    print("SYSTEMATIC MISSING COMPONENT ANALYSIS")
    print("=" * 90)

    for case in CASES:
        expected_path = results_dir / f"expected_{case}.yaml"
        if not expected_path.exists():
            continue

        expected = load_yaml(expected_path)
        exp_comps = get_comp_name_set(expected)

        if not exp_comps:
            continue

        missing_per_run = []

        for run_idx in range(1, num_runs + 1):
            actual_path = results_dir / f"run{run_idx}" / f"actual_{case}.yaml"
            if not actual_path.exists():
                continue

            actual = load_yaml(actual_path)
            act_comps = get_comp_name_set(actual)
            missing = exp_comps - act_comps
            missing_per_run.append(missing)

        if not missing_per_run:
            continue

        systematic = missing_per_run[0].copy()
        for s in missing_per_run[1:]:
            systematic &= s

        all_missing = set()
        for s in missing_per_run:
            all_missing |= s

        occasional = set()
        for comp in all_missing:
            count = sum(1 for s in missing_per_run if comp in s)
            if count == num_runs - 1:
                occasional.add(comp)

        print(f"\nCase: {case.upper()}")
        print(f"  Systematic missing components ({len(missing_per_run)}/{num_runs} runs):")
        if systematic:
            for comp in sorted(systematic):
                print(f"    x {comp}")
        else:
            print("    (none)")

        if occasional:
            print(f"  Occasional missing components ({num_runs - 1}/{num_runs} runs):")
            for comp in sorted(occasional):
                print(f"    ~ {comp}")


def find_systematic_missing(results_dir: Path, num_runs: int):
    
    print("\n" + "=" * 90)
    print("SYSTEMATIC MISSING ANALYSIS")
    print("=" * 90)

    for case in CASES:
        expected_path = results_dir / f"expected_{case}.yaml"
        if not expected_path.exists():
            continue

        expected = load_yaml(expected_path)
        exp_rels = get_rel_set(expected)

        if not exp_rels:
            continue

        missing_per_run = []

        for run_idx in range(1, num_runs + 1):
            actual_path = results_dir / f"run{run_idx}" / f"actual_{case}.yaml"
            if not actual_path.exists():
                continue
            actual = load_yaml(actual_path)
            act_rels = get_rel_set(actual)
            missing = exp_rels - act_rels
            missing_per_run.append(missing)

        if not missing_per_run:
            continue

        systematic = missing_per_run[0].copy()
        for s in missing_per_run[1:]:
            systematic = systematic & s

        all_missing = set()
        for s in missing_per_run:
            all_missing |= s

        occasional = set()
        for rel in all_missing:
            count = sum(1 for s in missing_per_run if rel in s)
            if count == num_runs - 1:
                occasional.add(rel)

        print(f"\nCase: {case.upper()}")
        print(f"  Systematic missing ({len(missing_per_run)}/{num_runs} runs):")
        if systematic:
            for src, tgt, rt in sorted(systematic):
                print(f"    x {src} --[{rt}]--> {tgt}")
        else:
            print(f"    (none)")

        if occasional:
            print(f"  Occasional missing ({num_runs - 1}/{num_runs} runs):")
            for src, tgt, rt in sorted(occasional):
                print(f"    ~ {src} --[{rt}]--> {tgt}")


def print_latex_table(per_case_metrics):
    """Print a LaTeX-ready table for thesis use."""
    print("\n\n% ===== LaTeX table for thesis =====")
    print("\\begin{tabular}{l" + "c" * len(METRICS_TO_TRACK) + "}")
    print("\\toprule")
    header = "Case & " + " & ".join(m.replace("_", "\\_") for m in METRICS_TO_TRACK) + " \\\\"
    print(header)
    print("\\midrule")

    for case, metrics_dict in per_case_metrics.items():
        row = [case]
        for metric in METRICS_TO_TRACK:
            samples = metrics_dict.get(metric, [])
            if not samples:
                row.append("--")
                continue
            mean = np.mean(samples)
            _, _, margin = prediction_interval(samples)
            row.append(f"{mean:.3f} $\\pm$ {margin:.3f}")
        print(" & ".join(row) + " \\\\")

    print("\\bottomrule")
    print("\\end{tabular}")


def main():
    parser = argparse.ArgumentParser(description="Multi-run evaluation with uncertainty quantification")
    parser.add_argument("--results_dir", required=True,
                        help="Directory containing run1/, run2/, ..., and expected_*.yaml files")
    parser.add_argument("--num_runs", type=int, default=3,
                        help="Number of runs (default: 3)")
    parser.add_argument("--latex", action="store_true", help="Also print LaTeX table")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.is_dir():
        print(f"Directory not found: {results_dir}")
        return

    print(f"Evaluating {args.num_runs} runs in {results_dir}")
    per_case_metrics = evaluate_all_runs(results_dir, args.num_runs)
    print_results(per_case_metrics)
    print_relation_type_breakdown(results_dir, args.num_runs)
    print_global_relation_type_aggregate(results_dir, args.num_runs)
    find_systematic_missing_components(results_dir, args.num_runs)
    find_systematic_missing(results_dir, args.num_runs)
    if args.latex:
        print_latex_table(per_case_metrics)


if __name__ == "__main__":
    main()