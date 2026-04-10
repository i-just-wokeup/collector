import json
import sys
from pathlib import Path


def generate_jd_json_from_png_folder(
    png_folder: Path,
    output_json_path: Path,
    jd_research_tool_root: Path,
) -> dict:
    tool_src = jd_research_tool_root / "src"
    if not tool_src.exists():
        raise FileNotFoundError(f"jd-research-tool src not found: {tool_src}")

    if str(tool_src) not in sys.path:
        sys.path.insert(0, str(tool_src))

    from vision_structure_jd import structure_jd_images  # noqa: WPS433

    png_files = sorted(png_folder.glob("*.png"))
    if not png_files:
        raise FileNotFoundError(f"No PNG files found: {png_folder}")

    image_paths = [str(p) for p in png_files]
    structured = structure_jd_images(image_paths)
    if not isinstance(structured, dict):
        raise ValueError("Invalid structured JD result")

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    with output_json_path.open("w", encoding="utf-8") as f:
        json.dump(structured, f, ensure_ascii=False, indent=2)

    return structured


def generate_jd_json_from_text(
    raw_text: str,
    output_json_path: Path,
    jd_research_tool_root: Path,
) -> dict:
    tool_src = jd_research_tool_root / "src"
    if not tool_src.exists():
        raise FileNotFoundError(f"jd-research-tool src not found: {tool_src}")

    if str(tool_src) not in sys.path:
        sys.path.insert(0, str(tool_src))

    from structure_jd import structure_jd_text  # noqa: WPS433

    structured = structure_jd_text(raw_text)
    if not isinstance(structured, dict):
        raise ValueError("Invalid structured JD result")

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    with output_json_path.open("w", encoding="utf-8") as f:
        json.dump(structured, f, ensure_ascii=False, indent=2)

    return structured
