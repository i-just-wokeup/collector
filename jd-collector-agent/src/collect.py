import os
import shutil
from pathlib import Path, PureWindowsPath

from playwright.sync_api import sync_playwright

from capture import capture_job_detail
from db import (
    get_db_connection,
    get_posting_count,
    is_seen_url,
    save_job_posting,
    save_job_sections,
)
from runner import generate_jd_json_from_png_folder, generate_jd_json_from_text
from sites import get_site_adapter
from utils import (
    assess_capture_failed,
    assess_low_quality_job,
    append_seen_url,
    detect_core_sections,
    ensure_dir,
    ensure_enriched_schema,
    is_gemini_quota_error,
    load_seen_urls,
    now_iso,
    now_stamp,
    save_json,
    select_images_for_ocr,
    slugify,
    trim_raw_text_noise,
)


DEFAULT_DB_PATH = r"C:\dev\jd_data.db"
DEFAULT_JD_RESEARCH_TOOL_PATH = r"C:\dev\jd-research-tool"
SUPPORTED_SITE_NAMES = {"jobkorea", "saramin"}


def resolve_path(raw_path: str) -> Path:
    windows_path = PureWindowsPath(raw_path)
    if windows_path.drive.lower() == "c:":
        if Path("C:/").exists():
            return Path(windows_path)
        return Path("/mnt/c", *windows_path.parts[1:])
    return Path(raw_path)


def build_filtered_search_url(site_name: str, search_keyword: str) -> str:
    adapter = get_site_adapter(site_name)
    base_url = adapter.build_search_url(search_keyword)

    if site_name == "jobkorea":
        return f"{base_url}&cotype=1,4"
    if site_name == "saramin":
        return f"{base_url}&inner_com_type=scale001"

    raise ValueError("site_name must be one of: jobkorea, saramin")


def run_collection(
    site_name: str,
    search_keyword: str,
    target_count: int,
    jd_research_tool_path: str = DEFAULT_JD_RESEARCH_TOOL_PATH,
) -> None:
    base_dir = Path(__file__).resolve().parent.parent
    raw_dir = base_dir / "output" / "raw_captures"
    failed_capture_dir = base_dir / "output" / "failed_capture" / f"{site_name}_{slugify(search_keyword)[:40]}"
    low_quality_dir = base_dir / "output" / "low_quality" / f"{site_name}_{slugify(search_keyword)[:40]}"
    quota_stop_dir = base_dir / "output" / "quota_stop"
    seen_path = base_dir / "output" / "seen_urls.txt"
    jd_research_tool_root = resolve_path(jd_research_tool_path)
    db_path = os.getenv("JD_DB_PATH", DEFAULT_DB_PATH)

    for directory in (raw_dir, failed_capture_dir, low_quality_dir, quota_stop_dir):
        ensure_dir(directory)

    adapter = get_site_adapter(site_name)
    search_url = build_filtered_search_url(adapter.site_name, search_keyword)
    output_job_folder_name = f"{adapter.site_name}_{slugify(search_keyword)[:40]}"
    seen_urls = load_seen_urls(seen_path)
    saved_count = 0
    processed_count = 0

    conn = get_db_connection(db_path)
    current_posting_count = get_posting_count(conn)

    print(f"[INFO] site_name={adapter.site_name}")
    print(f"[INFO] search_keyword={search_keyword}")
    print(f"[INFO] target_count={target_count}")
    print(f"[INFO] db_path={db_path}")
    print(f"[INFO] current_posting_count={current_posting_count}")
    print(f"[INFO] search_url={search_url}")

    def stop_for_quota(error: Exception) -> None:
        print("[ERROR] Gemini quota exceeded. Pipeline stopped.")
        print(f"[ERROR] processed_count={processed_count} saved_count={saved_count}")
        quota_meta = {
            "stopped_at": now_iso(),
            "reason": "gemini_quota_exceeded",
            "processed_count": processed_count,
            "saved_count": saved_count,
            "site_name": adapter.site_name,
            "search_keyword": search_keyword,
            "db_path": db_path,
            "error_message": str(error),
        }
        quota_path = quota_stop_dir / f"quota_stop_{now_stamp()}.json"
        save_json(quota_path, quota_meta)
        print(f"[INFO] saved_quota_stop={quota_path}")

    max_links = max(target_count * 12, 40)

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width": 1600, "height": 2000})
    page = context.new_page()

    try:
        job_links = adapter.collect_job_links(page, search_url, max_links=max_links)
        print(f"[INFO] collected_job_links={len(job_links)}")

        if not job_links:
            print("[WARN] No job links found.")
            return

        for idx, link in enumerate(job_links, start=1):
            if saved_count >= target_count:
                print("[DONE] target_count reached. stop collection.")
                break

            if link in seen_urls:
                print(f"[SKIP] duplicate url from seen_urls ({idx}): {link}")
                continue

            if is_seen_url(conn, link):
                print(f"[SKIP] duplicate url from db ({idx}): {link}")
                append_seen_url(seen_path, link)
                seen_urls.add(link)
                continue

            print(f"[INFO] processing {idx}/{len(job_links)}")
            processed_count += 1

            job_id = f"{adapter.site_name}_{now_stamp()}_{idx:03d}"
            job_capture_dir = raw_dir / job_id

            try:
                meta = capture_job_detail(
                    context=context,
                    detail_url=link,
                    output_dir=job_capture_dir,
                    adapter=adapter,
                )
                posting_title = str(meta.get("title", "")).strip() or "untitled"
                print(f"[INFO] title={posting_title}")
                print(f"[INFO] url={link}")
                print(f"[INFO] capture_images={meta.get('capture_count', 0)}")
                print(f"[INFO] first_capture_saved={str(meta.get('first_capture_saved', False)).lower()}")
                print(f"[INFO] body_locator_found={str(meta.get('body_locator_found', False)).lower()}")
                print(f"[INFO] company={meta.get('company', '')}")
                print(f"[INFO] seniority_text={meta.get('seniority_text', '')}")
                print(f"[INFO] seniority_text_source={meta.get('seniority_text_source', 'fallback')}")
                print(f"[INFO] employment_type={meta.get('employment_type', '')}")
            except Exception as err:
                print(f"[WARN] capture failed: {err}")
                append_seen_url(seen_path, link)
                seen_urls.add(link)
                continue

            if int(meta.get("capture_count", 0)) <= 0:
                fail_meta = {
                    "job_id": job_id,
                    "source_url": link,
                    "site_name": adapter.site_name,
                    "reason": "no_images_captured",
                    "capture_image_count": int(meta.get("capture_count", 0)),
                    "detected_keywords": [],
                    "saved_at": now_iso(),
                }
                fail_path = failed_capture_dir / f"failed_{now_stamp()}_{idx:03d}.json"
                save_json(fail_path, fail_meta)
                print("[WARN] capture_failed=true reason=no_images_captured")
                print(f"[INFO] saved_failed_capture={fail_path}")
                append_seen_url(seen_path, link)
                seen_urls.add(link)
                continue

            all_source_images = sorted(job_capture_dir.glob("*.png"))
            ocr_images = select_images_for_ocr(all_source_images, max_images=3)
            ocr_input_dir = raw_dir / job_id / "ocr_input"
            ensure_dir(ocr_input_dir)
            for image_path in ocr_images:
                shutil.copy2(image_path, ocr_input_dir / image_path.name)
            print(f"[INFO] capture_images_count={len(all_source_images)}")
            print(f"[INFO] ocr_used_images_count={len(ocr_images)}")

            temp_json_path = raw_dir / job_id / "jd_result.json"
            dom_raw_text = trim_raw_text_noise(str(meta.get("raw_text", "") or ""))
            dom_keywords = ("자격요건", "주요업무", "담당업무", "우대사항")
            should_use_dom_extraction = len(dom_raw_text) >= 1500 and any(
                keyword in dom_raw_text for keyword in dom_keywords
            )
            dom_extraction_used = False

            if should_use_dom_extraction:
                try:
                    jd_payload = generate_jd_json_from_text(
                        raw_text=dom_raw_text,
                        output_json_path=temp_json_path,
                        jd_research_tool_root=jd_research_tool_root,
                    )
                    dom_extraction_used = True
                    print("[INFO] JSON generation success")
                except Exception as err:
                    if is_gemini_quota_error(err):
                        stop_for_quota(err)
                        return
                    dom_extraction_used = False

            print(f"[INFO] dom_extraction_used={str(dom_extraction_used).lower()}")

            if not dom_extraction_used:
                try:
                    jd_payload = generate_jd_json_from_png_folder(
                        png_folder=ocr_input_dir,
                        output_json_path=temp_json_path,
                        jd_research_tool_root=jd_research_tool_root,
                    )
                    print("[INFO] JSON generation success")
                except Exception as err:
                    if is_gemini_quota_error(err):
                        stop_for_quota(err)
                        return
                    print(f"[WARN] JSON generation failed: {err}")
                    append_seen_url(seen_path, link)
                    seen_urls.add(link)
                    continue

            jd_payload["raw_text"] = trim_raw_text_noise(str(jd_payload.get("raw_text", "") or ""))
            source_images = [path.name for path in all_source_images]
            raw_text = str(jd_payload.get("raw_text", "") or "")
            capture_image_count = len(source_images)
            detected_core_sections = detect_core_sections(raw_text)
            print(f"[INFO] capture_image_count={capture_image_count}")
            print(f"[INFO] detected_core_sections={detected_core_sections}")

            capture_failed, capture_fail_reasons, detected_core_sections = assess_capture_failed(
                raw_text=raw_text,
                capture_image_count=capture_image_count,
            )
            print(f"[INFO] capture_failed={str(capture_failed).lower()}")
            if capture_failed:
                print(f"[WARN] capture_failed=true reason={','.join(capture_fail_reasons)}")
                fail_meta = {
                    "job_id": job_id,
                    "source_url": link,
                    "site_name": adapter.site_name,
                    "reason": capture_fail_reasons[0] if capture_fail_reasons else "capture_failed",
                    "capture_image_count": capture_image_count,
                    "detected_keywords": detected_core_sections,
                    "saved_at": now_iso(),
                }
                fail_path = failed_capture_dir / f"failed_{now_stamp()}_{idx:03d}.json"
                save_json(fail_path, fail_meta)
                print(f"[INFO] saved_failed_capture={fail_path}")
                append_seen_url(seen_path, link)
                seen_urls.add(link)
                continue

            jd_payload = ensure_enriched_schema(
                jd_payload,
                company=str(meta.get("company", "")),
                posting_title=posting_title,
                source_site=adapter.site_name,
                source_url=link,
                seniority_text=str(meta.get("seniority_text", "")),
                employment_type=str(meta.get("employment_type", "")),
                target_role="",
                classification_result="",
                source_images=source_images,
                captured_at=now_iso(),
                search_keyword=search_keyword,
                output_job_folder_name=output_job_folder_name,
                site_name=adapter.site_name,
                job_id=job_id,
            )

            low_quality_job, low_quality_reasons = assess_low_quality_job(jd_payload)
            print(f"[INFO] low_quality_job={str(low_quality_job).lower()}")
            if low_quality_job:
                print(f"[WARN] low_quality_job=true reasons={','.join(low_quality_reasons)}")
                jd_payload["low_quality_meta"] = {
                    "job_id": job_id,
                    "source_url": link,
                    "site_name": adapter.site_name,
                    "reason": low_quality_reasons,
                    "saved_at": now_iso(),
                }
                low_quality_path = low_quality_dir / f"lowq_{now_stamp()}_{idx:03d}_{slugify(posting_title)[:40]}.json"
                save_json(low_quality_path, jd_payload)
                print(f"[INFO] saved_low_quality={low_quality_path}")
                append_seen_url(seen_path, link)
                seen_urls.add(link)
                continue

            posting = {
                "id": job_id,
                "company": str(meta.get("company", "") or ""),
                "posting_title": posting_title,
                "extracted_role": str(jd_payload.get("role", "") or posting_title),
                "source_site": adapter.site_name,
                "source_url": link,
                "seniority_text": str(meta.get("seniority_text", "") or ""),
                "employment_type": str(meta.get("employment_type", "") or ""),
                "raw_text": raw_text,
                "captured_at": str(jd_payload.get("collector_meta", {}).get("captured_at", "") or now_iso()),
                "classification_status": "pending",
                "created_at": now_iso(),
            }

            try:
                save_job_posting(conn, posting)
                save_job_sections(conn, job_id, jd_payload)
                conn.commit()
            except Exception as err:
                conn.rollback()
                print(f"[WARN] DB save failed: {err}")
                append_seen_url(seen_path, link)
                seen_urls.add(link)
                continue

            append_seen_url(seen_path, link)
            seen_urls.add(link)
            saved_count += 1

            total_postings = get_posting_count(conn)
            print(f"[INFO] saved_to_db=true job_id={job_id}")
            print(f"[INFO] posting_count={total_postings}")
            print(f"[INFO] saved_count={saved_count}/{target_count}")

        if saved_count >= target_count:
            print("[DONE] target_count reached. collection finished.")
        else:
            print("[DONE] no more links to process. collection finished.")
    finally:
        page.close()
        context.close()
        browser.close()
        pw.stop()
        conn.close()


def prompt_with_default(message: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{message}{suffix}: ").strip()
    return value or default


def main() -> None:
    site_name = prompt_with_default("site_name (jobkorea|saramin)").lower()
    if site_name not in SUPPORTED_SITE_NAMES:
        raise ValueError("site_name must be one of: jobkorea, saramin")

    search_keyword = prompt_with_default("search_keyword")
    if not search_keyword:
        raise ValueError("search_keyword is required")

    target_count_text = prompt_with_default("target_count")
    if not target_count_text.isdigit() or int(target_count_text) <= 0:
        raise ValueError("target_count must be a positive integer")
    target_count = int(target_count_text)

    jd_research_tool_path = prompt_with_default(
        "jd_research_tool_path",
        DEFAULT_JD_RESEARCH_TOOL_PATH,
    )

    run_collection(
        site_name=site_name,
        search_keyword=search_keyword,
        target_count=target_count,
        jd_research_tool_path=jd_research_tool_path,
    )


if __name__ == "__main__":
    main()
