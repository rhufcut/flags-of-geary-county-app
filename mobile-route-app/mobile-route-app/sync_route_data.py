import shutil
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
DEFAULT_LOCAL_OUTPUTS_DIR = Path(r"C:\Users\rhufc\OneDrive\JCMS\Flags of Geary County\outputs")
TARGET_OUTPUTS_DIR = APP_DIR / "data" / "outputs"


def latest_matching_file(directory: Path, patterns: list[str]) -> Path | None:
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(directory.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def copy_required_file(label: str, source: Path | None, target_name: str) -> None:
    if source is None:
        raise FileNotFoundError(f"Could not find the latest {label} in {DEFAULT_LOCAL_OUTPUTS_DIR}")
    target_path = TARGET_OUTPUTS_DIR / target_name
    shutil.copy2(source, target_path)
    print(f"{label}: {source.name} -> {target_path}")


def main() -> None:
    if not DEFAULT_LOCAL_OUTPUTS_DIR.is_dir():
        raise FileNotFoundError(f"Local outputs folder not found: {DEFAULT_LOCAL_OUTPUTS_DIR}")

    TARGET_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    manifest = latest_matching_file(
        DEFAULT_LOCAL_OUTPUTS_DIR,
        ["flags_route_manifest*.json", "flags_route_manifest.json"],
    )
    links_csv = latest_matching_file(
        DEFAULT_LOCAL_OUTPUTS_DIR,
        ["flags_google_maps_links_*.csv", "flags_google_maps_links.csv"],
    )

    copy_required_file("manifest", manifest, "flags_route_manifest.json")
    copy_required_file("links CSV", links_csv, "flags_google_maps_links.csv")
    print(f"Render-ready route data refreshed in {TARGET_OUTPUTS_DIR}")


if __name__ == "__main__":
    main()
