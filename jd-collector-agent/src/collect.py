import copy
import json
import os
from pathlib import Path, PureWindowsPath

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from capture import capture_job_detail
from db import (
    get_db_connection,
    get_posting_count,
    is_seen_url,
    save_job_posting,
    save_job_posting_roles,
    save_job_sections,
)
from runner import generate_jd_json_from_png_folder, generate_jd_json_from_text
from sites import get_site_adapter
from utils import (
    assess_capture_failed,
    assess_low_quality_job,
    append_seen_url,
    clean_job_posting_text,
    clean_role_first_task,
    detect_core_sections,
    ensure_dir,
    ensure_enriched_schema,
    filter_low_value_lines,
    is_aggregate_posting,
    is_gemini_quota_error,
    load_seen_urls,
    now_iso,
    now_stamp,
    prepare_ocr_image,
    save_json,
    select_images_for_ocr,
    slugify,
    trim_raw_text_noise,
)


DEFAULT_DB_PATH = r"C:\dev\jd_data.db"
DEFAULT_JD_RESEARCH_TOOL_PATH = r"C:\dev\jd-research-tool"
DEFAULT_TOP8_FAMILIES_PATH = str(
    (Path(__file__).resolve().parent.parent / "job_families_top8.json")
)
DEFAULT_BROWSER_PROFILE_ROOT = str(
    (Path(__file__).resolve().parent.parent / "output" / "browser_profiles")
)
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


def load_top8_category_codes(
    category_id: str,
    top8_families_path: str = DEFAULT_TOP8_FAMILIES_PATH,
) -> list[int]:
    families_path = resolve_path(top8_families_path)
    with families_path.open("r", encoding="utf-8") as f:
        families = json.load(f)
    for item in families:
        if item.get("id") == category_id:
            return [int(c) for c in item.get("jobkorea_top100_codes", [])]
    raise ValueError(f"category_id '{category_id}' not found in {top8_families_path}")


def build_browser_profile_dir(
    site_name: str,
    browser_profile_root: str = DEFAULT_BROWSER_PROFILE_ROOT,
) -> Path:
    profile_root = resolve_path(browser_profile_root)
    profile_dir = profile_root / slugify(site_name)
    profile_dir.mkdir(parents=True, exist_ok=True)
    return profile_dir


def build_login_entry_url(
    site_name: str,
    category_id: str = "",
    top8_families_path: str = DEFAULT_TOP8_FAMILIES_PATH,
) -> str:
    adapter = get_site_adapter(site_name)

    if site_name == "jobkorea":
        if category_id:
            biz_codes = load_top8_category_codes(category_id, top8_families_path)
            return adapter.build_top100_category_url(biz_codes[0])
        return "https://www.jobkorea.co.kr/Top100/"

    if site_name == "saramin":
        return adapter.build_search_url("신입")

    return adapter.build_search_url("채용")


def open_login_browser(
    site_name: str,
    category_id: str = "",
    top8_families_path: str = DEFAULT_TOP8_FAMILIES_PATH,
    browser_profile_root: str = DEFAULT_BROWSER_PROFILE_ROOT,
) -> None:
    browser_profile_dir = build_browser_profile_dir(site_name, browser_profile_root)
    entry_url = build_login_entry_url(site_name, category_id, top8_families_path)

    print(f"[INFO] login_browser_open=true")
    print(f"[INFO] site_name={site_name}")
    if category_id:
        print(f"[INFO] category_id={category_id}")
    print(f"[INFO] browser_profile_dir={browser_profile_dir}")
    print(f"[INFO] entry_url={entry_url}")
    print("[INFO] complete_login_in_opened_browser_if_needed=true")
    print("[INFO] close_browser_window_when_login_is_done=true")

    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=str(browser_profile_dir),
        headless=True,
        viewport={"width": 1920, "height": 2000},
    )

    try:
        if context.pages:
            page = context.pages[0]
        else:
            page = context.new_page()

        page.goto(entry_url, wait_until="domcontentloaded")

        while True:
            if not context.pages:
                break
            context.pages[0].wait_for_timeout(1000)
    except Exception:
        pass
    finally:
        try:
            context.close()
        except Exception:
            pass
        pw.stop()


def run_collection(
    site_name: str,
    search_keyword: str,
    target_count: int,
    jd_research_tool_path: str = DEFAULT_JD_RESEARCH_TOOL_PATH,
    category_id: str = "",
    top8_families_path: str = DEFAULT_TOP8_FAMILIES_PATH,
    browser_profile_root: str = DEFAULT_BROWSER_PROFILE_ROOT,
) -> None:
    use_category_mode = bool(category_id)

    base_dir = Path(__file__).resolve().parent.parent
    raw_dir = base_dir / "output" / "raw_captures"
    browser_profile_dir = build_browser_profile_dir(site_name, browser_profile_root)
    profile_has_state = any(browser_profile_dir.iterdir())

    if use_category_mode:
        slug = slugify(category_id)[:40]
    else:
        slug = slugify(search_keyword)[:40]

    failed_capture_dir = base_dir / "output" / "failed_capture" / f"{site_name}_{slug}"
    low_quality_dir = base_dir / "output" / "low_quality" / f"{site_name}_{slug}"
    quota_stop_dir = base_dir / "output" / "quota_stop"
    seen_path = base_dir / "output" / "seen_urls.txt"
    jd_research_tool_root = resolve_path(jd_research_tool_path)
    db_path = os.getenv("JD_DB_PATH", DEFAULT_DB_PATH)

    for directory in (raw_dir, failed_capture_dir, low_quality_dir, quota_stop_dir):
        ensure_dir(directory)

    adapter = get_site_adapter(site_name)
    output_job_folder_name = f"{adapter.site_name}_{slug}"
    seen_urls = load_seen_urls(seen_path)
    saved_count = 0
    processed_count = 0

    # 수집 진입 URL 결정
    if use_category_mode:
        if site_name != "jobkorea":
            raise ValueError("category_id 기반 수집은 현재 jobkorea만 지원합니다.")
        biz_codes = load_top8_category_codes(category_id, top8_families_path)
        entry_urls = [adapter.build_top100_category_url(code) for code in biz_codes]
    else:
        entry_urls = [build_filtered_search_url(adapter.site_name, search_keyword)]

    conn = get_db_connection(db_path)
    current_posting_count = get_posting_count(conn)

    print(f"[INFO] site_name={adapter.site_name}")
    if use_category_mode:
        print(f"[INFO] category_id={category_id}")
        print(f"[INFO] entry_urls={entry_urls}")
    else:
        print(f"[INFO] search_keyword={search_keyword}")
        print(f"[INFO] entry_urls={entry_urls}")
    print(f"[INFO] target_count={target_count}")
    print(f"[INFO] db_path={db_path}")
    print(f"[INFO] browser_profile_dir={browser_profile_dir}")
    print(f"[INFO] browser_profile_has_state={str(profile_has_state).lower()}")
    if not profile_has_state:
        print("[INFO] first_run_browser_profile_created=true")
        print("[INFO] opened_browser_profile_is_empty=true")
        print("[INFO] login_in_opened_browser_if_needed_and_profile_will_be_reused=true")
    print(f"[INFO] current_posting_count={current_posting_count}")

    def stop_for_quota(error: Exception) -> None:
        print("[ERROR] Gemini quota exceeded. Pipeline stopped.")
        print(f"[ERROR] processed_count={processed_count} saved_count={saved_count}")
        quota_meta = {
            "stopped_at": now_iso(),
            "reason": "gemini_quota_exceeded",
            "processed_count": processed_count,
            "saved_count": saved_count,
            "site_name": adapter.site_name,
            "search_keyword": search_keyword if not use_category_mode else "",
            "category_id": category_id,
            "db_path": db_path,
            "error_message": str(error),
        }
        quota_path = quota_stop_dir / f"quota_stop_{now_stamp()}.json"
        save_json(quota_path, quota_meta)
        print(f"[INFO] saved_quota_stop={quota_path}")

    # Top100 카테고리 페이지는 최대 100건 표시 → 여유 있게 max_links 설정
    # 복수 URL이 있는 카테고리는 URL당 max_links를 수집 후 합산
    max_links_per_url = max(target_count * 6, 120) if use_category_mode else max(target_count * 12, 40)

    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=str(browser_profile_dir),
        headless=True,
        viewport={"width": 1920, "height": 2000},
    )
    if context.pages:
        page = context.pages[0]
    else:
        page = context.new_page()

    try:
        # 모든 진입 URL에서 링크 수집 후 합산 (중복 제거)
        job_links: list[str] = []
        seen_links: set[str] = set()
        for entry_url in entry_urls:
            print(f"[INFO] collecting_links_from={entry_url}")
            links = adapter.collect_job_links(page, entry_url, max_links=max_links_per_url)
            for link in links:
                if link not in seen_links:
                    seen_links.add(link)
                    job_links.append(link)
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
                print(f"[INFO] locator_capture_used={str(meta.get('locator_capture_used', False)).lower()}")
                print(f"[INFO] locator_capture_selector={meta.get('locator_capture_selector', '')}")
                print(f"[INFO] iframe_capture_used={str(meta.get('iframe_capture_used', False)).lower()}")
                print(f"[INFO] iframe_url={meta.get('iframe_url', '')}")
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
                prepare_ocr_image(image_path, ocr_input_dir / image_path.name)
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
                    print(f"[WARN] dom_extraction_failed=true reason={type(err).__name__}: {err}")
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

            structured_jd_payload = copy.deepcopy(jd_payload)
            structured_jd_payload["raw_text"] = trim_raw_text_noise(
                str(structured_jd_payload.get("raw_text", "") or "")
            )
            structured_roles = structured_jd_payload.get("roles", [])
            structured_roles_count = len(structured_roles) if isinstance(structured_roles, list) else 0
            print(f"[INFO] structured_roles_count={structured_roles_count}")

            # posting_title / company 메타 보정
            # capture 단계에서 generic하게 잡힌 경우 LLM 결과로 보완한다
            _GENERIC_TITLES = {"채용공고", "공고", "untitled", "", "채용 공고", "job posting"}
            if posting_title.lower() in _GENERIC_TITLES:
                llm_title = str(jd_payload.get("posting_title", "") or "").strip()
                if llm_title and llm_title.lower() not in _GENERIC_TITLES:
                    print(f"[INFO] posting_title_fallback: '{posting_title}' → '{llm_title}'")
                    posting_title = llm_title
            capture_company = str(meta.get("company", "") or "").strip()
            llm_company = str(jd_payload.get("company", "") or "").strip()
            effective_company = capture_company or llm_company

            is_aggregate, aggregate_reasons = is_aggregate_posting(dom_raw_text, structured_roles_count)
            if is_aggregate:
                print(f"[WARN] aggregate_posting_detected=true reasons={','.join(aggregate_reasons)}")
                jd_payload["aggregate_candidate"] = True
                jd_payload["aggregate_reasons"] = aggregate_reasons
            else:
                jd_payload["aggregate_candidate"] = False

            jd_payload["raw_text"] = trim_raw_text_noise(str(jd_payload.get("raw_text", "") or ""))
            source_images = [path.name for path in all_source_images]
            # raw_text: DB 저장용 원본 (trim_raw_text_noise만 적용)
            # cleaned_raw_text: 판정/분석용 정제본 (UI 노이즈 추가 제거) — DB에는 저장하지 않음
            raw_text = str(jd_payload.get("raw_text", "") or "")
            cleaned_raw_text = clean_job_posting_text(raw_text, adapter.site_name)
            print(f"[INFO] raw_text_len={len(raw_text)} cleaned_raw_text_len={len(cleaned_raw_text)}")
            capture_image_count = len(source_images)
            # 섹션 탐지와 캡처 실패 판정은 cleaned_raw_text 기준으로 수행
            detected_core_sections = detect_core_sections(cleaned_raw_text)
            print(f"[INFO] capture_image_count={capture_image_count}")
            print(f"[INFO] detected_core_sections(cleaned)={detected_core_sections}")

            hard_failed, hard_reasons, soft_warns, detected_core_sections, gate_bypass_reason = (
                assess_capture_failed(
                    raw_text=cleaned_raw_text,
                    capture_image_count=capture_image_count,
                    capture_meta=meta,
                    jd_payload=jd_payload,
                )
            )

            if gate_bypass_reason:
                print(f"[INFO] capture_gate_bypass={gate_bypass_reason}")
            if soft_warns:
                print(f"[INFO] capture_gate_reason=soft_warn:{','.join(soft_warns)}")
            print(f"[INFO] capture_failed={str(hard_failed).lower()}")

            if hard_failed:
                print(f"[WARN] capture_gate_reason=hard_fail:{','.join(hard_reasons)}")
                fail_meta = {
                    "job_id": job_id,
                    "source_url": link,
                    "site_name": adapter.site_name,
                    "reason": hard_reasons[0] if hard_reasons else "capture_failed",
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

            # 저가치 문장 필터링 — normalized payload (shim) 섹션 정제 (raw_text 원본은 별도 보존)
            for section_key in ("main_tasks", "requirements", "preferred"):
                original_lines = jd_payload.get(section_key, [])
                if isinstance(original_lines, list):
                    filtered_lines = filter_low_value_lines(original_lines)
                    removed = len(original_lines) - len(filtered_lines)
                    if removed > 0:
                        print(f"[INFO] filtered_{section_key}_lines={removed}")
                    jd_payload[section_key] = filtered_lines

            # role 텍스트 정제 — low-quality 판정 전에 수행해야 판정과 저장 기준이 일치한다.
            # raw_text 원본은 건드리지 않고 roles[] 내부의 저장용 텍스트만 정제한다.
            if isinstance(structured_jd_payload.get("roles"), list):
                cleaned_roles = []
                for role_item in structured_jd_payload["roles"]:
                    if not isinstance(role_item, dict):
                        cleaned_roles.append(role_item)
                        continue
                    role_name = str(role_item.get("role_name", "") or "").strip()
                    role_copy = dict(role_item)
                    # 1) main_tasks 첫 줄이 role_name 반복이면 제거
                    tasks = role_copy.get("main_tasks", []) or []
                    if isinstance(tasks, list):
                        role_copy["main_tasks"] = clean_role_first_task(role_name, tasks)
                    # 2) requirements/preferred에서 LOW_VALUE_LINE_PATTERNS 적용
                    for sec_key in ("requirements", "preferred"):
                        sec_val = role_copy.get(sec_key, []) or []
                        if isinstance(sec_val, list):
                            role_copy[sec_key] = filter_low_value_lines(sec_val)
                    cleaned_roles.append(role_copy)
                structured_jd_payload["roles"] = cleaned_roles
                # 정제 후 structured_roles 참조를 갱신 — 이하 품질 판정이 정제된 데이터를 기준으로 동작한다
                structured_roles = structured_jd_payload["roles"]

            low_quality_job, low_quality_reasons = assess_low_quality_job(
                jd_payload,
                roles=structured_roles if isinstance(structured_roles, list) else None,
                structured_payload=structured_jd_payload,
            )
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
                "company": effective_company,
                "posting_title": posting_title,
                # extracted_role은 레거시 하위호환용으로만 남긴다 — 분류/분석은 job_posting_roles 기준
                "extracted_role": str(jd_payload.get("role", "") or posting_title),
                "source_site": adapter.site_name,
                "source_url": link,
                "seniority_text": str(meta.get("seniority_text", "") or ""),
                "employment_type": str(meta.get("employment_type", "") or ""),
                "raw_text": raw_text,
                "source_category": category_id,
                "captured_at": str(jd_payload.get("collector_meta", {}).get("captured_at", "") or now_iso()),
                "classification_status": "pending",
                "created_at": now_iso(),
            }

            try:
                save_job_posting(conn, posting)
                save_job_sections(conn, job_id, jd_payload)
                # 역할별 저장은 원본 structured payload를 기준으로 처리한다.
                # 현재 normalized payload는 레거시 단일 role 흐름용이라
                # roles/common_* 필드를 완전히 보존하지 못한다.
                roles_saved = save_job_posting_roles(conn, job_id, structured_jd_payload)
                if roles_saved > 0:
                    print(f"[INFO] saved_roles={roles_saved} job_id={job_id}")
                elif structured_jd_payload.get("roles"):
                    print(f"[INFO] roles_already_complete job_id={job_id}")
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
        pw.stop()
        conn.close()


def prompt_with_default(message: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{message}{suffix}: ").strip()
    return value or default


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--category", default="")
    parser.add_argument("--target-count", type=int, default=0)
    parser.add_argument("--site", default="jobkorea")
    parser.add_argument("--login-only", action="store_true")
    known, _ = parser.parse_known_args()

    if known.login_only:
        if known.site not in SUPPORTED_SITE_NAMES:
            raise ValueError(f"--site must be one of: {', '.join(SUPPORTED_SITE_NAMES)}")
        open_login_browser(
            site_name=known.site,
            category_id=known.category,
        )
        return

    if known.category:
        # 카테고리 모드: 프롬프트 없이 인수로 바로 실행
        if known.site not in SUPPORTED_SITE_NAMES:
            raise ValueError(f"--site must be one of: {', '.join(SUPPORTED_SITE_NAMES)}")
        if known.target_count <= 0:
            raise ValueError("--target-count must be a positive integer")
        run_collection(
            site_name=known.site,
            search_keyword="",
            target_count=known.target_count,
            category_id=known.category,
        )
        return

    # 키워드 모드: 기존 stdin 프롬프트 흐름 (GUI 호환)
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
