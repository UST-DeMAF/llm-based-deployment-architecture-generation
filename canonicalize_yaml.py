import yaml, sys
from pathlib import Path
def sort_dict(obj):
    if isinstance(obj, dict):
        return {k: sort_dict(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [sort_dict(item) for item in obj]
    return obj
def canonicalize(in_path, out_path):
    data = yaml.safe_load(Path(in_path).read_text(encoding="utf-8"))
    sorted_data = sort_dict(data)
    yaml.safe_dump(
        sorted_data,
        Path(out_path).open("w", encoding="utf-8"),
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python canonicalize_yaml.py <input.yaml> <output_sorted.yaml>")
        sys.exit(1)
    canonicalize(sys.argv[1], sys.argv[2])
