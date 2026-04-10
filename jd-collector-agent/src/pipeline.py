from pathlib import Path
import shutil

from playwright.sync_api import sync_playwright

from capture import capture_job_detail
from classifier import classify_target_role
from runner import generate_jd_json_from_png_folder
from sites import get_site_adapter
from utils import (
    GeminiQuotaExceededError,
    assess_capture_failed,
    assess_low_quality_job,
    append_seen_url,
    count_json_files,
    is_gemini_quota_error,
    trim_raw_text_noise,
    detect_core_sections,
    ensure_dir,
    ensure_enriched_schema,
    load_seen_urls,
    now_iso,
    now_stamp,
    save_json,
    select_images_for_ocr,
    slugify,
)


def run_pipeline(
    target_role: str,
    site_name: str,
    search_keyword: str,
    target_count: int,
    output_job_folder_name: str,
    jd_research_tool_root: Path,
) -> None:
    base_dir = Path(__file__).resolve().parent.parent
    raw_dir = base_dir / "output" / "raw_captures"
    match_dir = base_dir / "output" / "classified" / "match" / output_job_folder_name
    not_match_dir = base_dir / "output" / "classified" / "not_match" / output_job_folder_name
    unknown_dir = base_dir / "output" / "classified" / "unknown" / output_job_folder_name
    failed_capture_dir = base_dir / "output" / "failed_capture" / output_job_folder_name
    low_quality_dir = base_dir / "output" / "low_quality" / output_job_folder_name
    quota_stop_dir = base_dir / "output" / "quota_stop"
    seen_path = base_dir / "output" / "seen_urls.txt"

    for d in (raw_dir, match_dir, not_match_dir, unknown_dir, failed_capture_dir, low_quality_dir, quota_stop_dir):
        ensure_dir(d)

    adapter = get_site_adapter(site_name)

    seen_urls = load_seen_urls(seen_path)
    match_count = count_json_files(match_dir)

    print(f"[INFO] site_name={adapter.site_name}")
    print(f"[INFO] target_role={target_role}")
    print(f"[INFO] search_keyword={search_keyword}")
    print(f"[INFO] target_count={target_count}")
    print(f"[INFO] current_match_count={match_count}")

    if match_count >= target_count:
        print("[DONE] target_count is already satisfied.")
        return

    processed_count = 0

    def stop_for_quota(error: Exception) -> None:
        print("[ERROR] Gemini quota exceeded. Pipeline stopped.")
        print(f"[ERROR] processed_count={processed_count} match_count={match_count}")
        quota_meta = {
            "stopped_at": now_iso(),
            "reason": "gemini_quota_exceeded",
            "processed_count": processed_count,
            "match_count": match_count,
            "site_name": adapter.site_name,
            "target_role": target_role,
            "search_keyword": search_keyword,
            "output_job_folder_name": output_job_folder_name,
            "error_message": str(error),
        }
        quota_path = quota_stop_dir / f"quota_stop_{now_stamp()}.json"
        save_json(quota_path, quota_meta)
        print(f"[INFO] saved_quota_stop={quota_path}")

    search_url = adapter.build_search_url(search_keyword)
    max_links = max(target_count * 12, 40)

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width": 1400, "height": 1800})
    page = context.new_page()

    try:
        job_links = adapter.collect_job_links(page, search_url, max_links=max_links)
        print(f"[INFO] collected_job_links={len(job_links)}")

        if not job_links:
            print("[WARN] No job links found.")
            return

        for idx, link in enumerate(job_links, start=1):
            if match_count >= target_count:
                print("[DONE] target_count reached. stop pipeline.")
                break

            if link in seen_urls:
                print(f"[SKIP] duplicate url ({idx}): {link}")
                continue

            print(f"[INFO] processing {idx}/{len(job_links)}")
            processed_count += 1

            job_id = f"{now_stamp()}_{idx:03d}"
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
            source_images = [p.name for p in all_source_images]
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
                target_role=target_role,
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

            try:
                label = classify_target_role(target_role=target_role, jd_payload=jd_payload)
            except GeminiQuotaExceededError as err:
                stop_for_quota(err)
                return
            jd_payload["classification_result"] = label
            print(f"[INFO] classification_result={label}")

            base_name = f"jd_{now_stamp()}_{idx:03d}_{slugify(posting_title)[:40]}.json"
            if label == "match":
                out_path = match_dir / base_name
                match_count += 1
            elif label == "not_match":
                out_path = not_match_dir / base_name
            else:
                out_path = unknown_dir / base_name

            save_json(out_path, jd_payload)
            print(f"[INFO] saved_json_path={out_path}")

            append_seen_url(seen_path, link)
            seen_urls.add(link)

            print(f"[INFO] match_count={match_count}/{target_count}")

        if match_count >= target_count:
            print("[DONE] target_count reached. pipeline finished.")
        else:
            print("[DONE] no more links to process. pipeline finished.")
    finally:
        page.close()
        context.close()
        browser.close()
        pw.stop()
