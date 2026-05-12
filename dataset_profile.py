from pathlib import Path
from collections import Counter, defaultdict
import json

ROOT = Path("/app/Evaluation/Evaluation")   # dataset root
EVAL_DIRNAME = "Evaluation"

def is_noise(p: Path) -> bool:
    name = p.name.lower()
    s = str(p).lower()

    # ignore areas that cause leakage/noise
    if "/measurements/" in s or "/documentation/" in s:
        return True

    # ignore expected/actual EDMM
    if name.endswith(("_expected.yaml", "_expected.yml", "_actual.yaml", "_actual.yml")):
        return True

    # misc
    if name.startswith("readme") or name in {"license", ".ds_store"}:
        return True
    if p.suffix.lower() in {".sh", ".png", ".jpg", ".jpeg", ".svg", ".pdf"}:
        return True

    # BIG noise: grafana dashboards etc.
    if "grafana" in s and "dashboards" in s:
        return True

    return False

def case_of(p: Path) -> str:
    parts = p.parts
    # .../Evaluation/Evaluation/<CASE>/...
    # 0: /, 1: app, 2: Evaluation, 3: Evaluation, 4: <CASE>
    try:
        i = parts.index("Evaluation")  # first match -> /app/Evaluation
        # if next part is also Evaluation, then case is after that
        if i + 1 < len(parts) and parts[i + 1] == "Evaluation":
            return parts[i + 2]
        return parts[i + 1]
    except Exception:
        return "unknown"

def main():
    if not ROOT.exists():
        raise SystemExit(f"ROOT not found: {ROOT}")

    all_files = [p for p in ROOT.rglob("*") if p.is_file()]
    deploy_files = [p for p in all_files if "deploymentmodel" in str(p).lower()]
    filtered = [p for p in deploy_files if not is_noise(p)]

    by_case = defaultdict(list)
    for p in filtered:
        by_case[case_of(p)].append(p)

    report = {
        "root": str(ROOT),
        "deploy_files_total": len(deploy_files),
        "deploy_files_filtered": len(filtered),
        "cases": {},
        "largest_files": [],
        "ext_distribution_global": {},
    }

    global_exts = Counter([p.suffix.lower() for p in filtered])
    report["ext_distribution_global"] = dict(global_exts)

    for c, files in sorted(by_case.items(), key=lambda x: -len(x[1])):
        exts = Counter([f.suffix.lower() for f in files])
        total_kb = sum(f.stat().st_size for f in files) / 1024
        report["cases"][c] = {
            "file_count": len(files),
            "size_kb": round(total_kb, 2),
            "ext_distribution": dict(exts),
        }

    largest = sorted(filtered, key=lambda p: p.stat().st_size, reverse=True)[:20]
    for p in largest:
        report["largest_files"].append({
            "size_kb": round(p.stat().st_size/1024, 2),
            "path": str(p),
        })

    print("=== DEPLOYMENT STATS (filtered) ===")
    print(f"deploy_files_total     = {len(deploy_files)}")
    print(f"deploy_files_filtered  = {len(filtered)}")

    print("\n=== Counts by case (top) ===")
    for c, info in sorted(report["cases"].items(), key=lambda x: -x[1]["file_count"]):
        print(f"{c:28s} files={info['file_count']:4d} size={info['size_kb']:9.1f}KB exts={info['ext_distribution']}")

    print("\n=== Top 10 largest filtered files ===")
    for item in report["largest_files"][:10]:
        print(f"{item['size_kb']:8.1f}KB  {item['path']}")

    out_path = Path("/app/deployment_stats.json")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved JSON report -> {out_path}")

if __name__ == "__main__":
    main()