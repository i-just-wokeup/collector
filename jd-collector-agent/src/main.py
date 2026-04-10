from pathlib import Path

from dotenv import load_dotenv

from pipeline import run_pipeline
from sites import SUPPORTED_SITE_NAMES


def prompt_non_empty(label: str) -> str:
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print("[WARN] empty value is not allowed.")


def prompt_positive_int(label: str) -> int:
    while True:
        raw = input(f"{label}: ").strip()
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
        print("[WARN] please enter a positive integer.")


def main() -> None:
    load_dotenv()

    print("=== jd-collector-agent ===")
    target_role = prompt_non_empty("target_role (ex: backend, frontend, marketing, pm, data)")
    site_name = prompt_non_empty("site_name (wanted | saramin | jobkorea)").lower()
    if site_name not in SUPPORTED_SITE_NAMES:
        raise ValueError("site_name must be one of: wanted, saramin, jobkorea")
    search_keyword = prompt_non_empty("search_keyword (ex: 백엔드 신입)")
    target_count = prompt_positive_int("target_count (match JSON count)")
    output_job_folder_name = prompt_non_empty("output_job_folder_name (ex: backend_junior)")

    default_tool_root = (Path(__file__).resolve().parents[2] / "jd-research-tool").resolve()
    jd_tool_root = Path(input(f"jd_research_tool_path [{default_tool_root}]: ").strip() or str(default_tool_root))

    run_pipeline(
        target_role=target_role,
        site_name=site_name,
        search_keyword=search_keyword,
        target_count=target_count,
        output_job_folder_name=output_job_folder_name,
        jd_research_tool_root=jd_tool_root,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[STOP] interrupted by user")
    except Exception as err:
        print(f"[ERROR] {err}")
