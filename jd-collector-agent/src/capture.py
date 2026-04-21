from pathlib import Path

from playwright.sync_api import BrowserContext
from sites.base import SiteAdapter

STOP_CAPTURE_KEYWORDS = ["자격 요건", "우대 사항", "requirements", "preferred"]

# JobKorea 본문 선택자 우선순위 (iframe fallback 이후)
_JOBKOREA_BODY_SELECTORS = [".artRead", ".detail", "#container"]


def _matched_capture_end_selector(page, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            if page.locator(selector).first.is_visible(timeout=400):
                return selector
        except Exception:
            continue
    return ""


def _detect_body_locator(page, site_name: str) -> tuple[bool, str]:
    selector_candidates = {
        "wanted": ["main", "section", "[data-cy='job-detail']"],
        "saramin": [".wrap_jv_cont", ".jv_cont", "#content", "main"],
        "jobkorea": [".artRead", ".detail", "#container", "main"],
    }.get(site_name, ["main", "body"])

    for selector in selector_candidates:
        try:
            if page.locator(selector).count() > 0:
                return True, selector
        except Exception:
            continue
    return False, ""


def _find_jobkorea_content_iframe(page):
    """GI_Read_Comt_Ifrm URL이 포함된 frame을 반환. 없으면 None."""
    for frame in page.frames:
        try:
            if "GI_Read_Comt_Ifrm" in (frame.url or ""):
                return frame
        except Exception:
            continue
    return None


def _hide_strategy_wrapper_siblings(page) -> bool:
    """StrategyWrapper 요소와 이후 형제 요소를 숨김 처리. 적용되면 True 반환."""
    try:
        applied = page.evaluate("""() => {
            const anchor = document.querySelector('[data-sentry-component="StrategyWrapper"]');
            if (!anchor) return false;
            let el = anchor;
            while (el) {
                el.style.display = 'none';
                el = el.nextElementSibling;
            }
            return true;
        }""")
        return bool(applied)
    except Exception:
        return False


def _jobkorea_locator_capture(page, output_dir: Path) -> dict:
    """
    JobKorea 전용 본문 캡처.
    우선순위: iframe(GI_Read_Comt_Ifrm) → .artRead → .detail → #container → main(노이즈 숨김)
    성공 여부와 방식을 dict로 반환.
    """
    png_path = output_dir / "page_001.png"

    # 1) iframe 우선 (GI_Read_Comt_Ifrm)
    frame = _find_jobkorea_content_iframe(page)
    if frame is not None:
        try:
            iframe_url = frame.url or ""
            loc = frame.locator("body").first
            if loc.is_visible(timeout=2000):
                loc.screenshot(path=str(png_path))
                raw_text = (frame.locator("body").inner_text(timeout=2500) or "").strip()
                print(f"[INFO] jobkorea_capture=iframe iframe_url={iframe_url}")
                return {
                    "used": True,
                    "selector": "iframe:body",
                    "iframe_used": True,
                    "iframe_url": iframe_url,
                    "raw_text": raw_text,
                }
        except Exception as e:
            print(f"[INFO] jobkorea_iframe_capture_failed reason={e}")

    # 2~4) .artRead → .detail → #container
    for selector in _JOBKOREA_BODY_SELECTORS:
        try:
            if page.locator(selector).count() == 0:
                continue
            loc = page.locator(selector).first
            if loc.is_visible(timeout=1500):
                loc.screenshot(path=str(png_path))
                raw_text = (loc.inner_text(timeout=2500) or "").strip()
                print(f"[INFO] jobkorea_capture=locator selector={selector}")
                return {
                    "used": True,
                    "selector": selector,
                    "iframe_used": False,
                    "iframe_url": "",
                    "raw_text": raw_text,
                }
        except Exception:
            continue

    # 5) main — StrategyWrapper 이후 노이즈 섹션 숨김 후 캡처
    try:
        if page.locator("main").count() > 0:
            loc = page.locator("main").first
            if loc.is_visible(timeout=1500):
                noise_hidden = _hide_strategy_wrapper_siblings(page)
                print(f"[INFO] jobkorea_capture=main strategy_wrapper_hidden={str(noise_hidden).lower()}")
                loc.screenshot(path=str(png_path))
                raw_text = (loc.inner_text(timeout=2500) or "").strip()
                return {
                    "used": True,
                    "selector": "main",
                    "iframe_used": False,
                    "iframe_url": "",
                    "raw_text": raw_text,
                }
    except Exception as e:
        print(f"[INFO] jobkorea_main_capture_failed reason={e}")

    return {"used": False, "selector": "", "iframe_used": False, "iframe_url": "", "raw_text": ""}


def capture_job_detail(
    context: BrowserContext,
    detail_url: str,
    output_dir: Path,
    adapter: SiteAdapter,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    page = context.new_page()

    try:
        page.goto(detail_url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(2500)

        site_meta = adapter.extract_detail_meta(page)
        title = site_meta.get("posting_title", "").strip() or page.title().strip() or "untitled"

        viewport = page.viewport_size or {"width": 1400, "height": 1800}
        step = max(int(viewport["height"] * 0.9), 400)

        current = 0
        page_idx = 1
        first_capture_saved = False
        max_pages = min(adapter.get_capture_max_pages(), 4)
        end_selectors = adapter.get_capture_end_selectors()
        max_scroll_attempts = getattr(adapter, "get_capture_max_scrolls", lambda: max_pages * 3)()
        scroll_attempts = 0
        triggered_end_selector = ""
        total_height = page.evaluate("() => document.body.scrollHeight")

        # 캡처 방식 추적 메타
        locator_capture_used = False
        locator_capture_selector = ""
        iframe_capture_used = False
        iframe_url = ""
        raw_text_val = ""

        # ── JobKorea: 전용 우선순위 캡처 ──
        if adapter.site_name == "jobkorea":
            jk_result = _jobkorea_locator_capture(page, output_dir)
            if jk_result["used"]:
                locator_capture_used = True
                locator_capture_selector = jk_result["selector"]
                iframe_capture_used = jk_result["iframe_used"]
                iframe_url = jk_result["iframe_url"]
                raw_text_val = jk_result["raw_text"]
                first_capture_saved = True
                page_idx = 2
            else:
                print("[INFO] jobkorea_locator_capture=all_failed fallback=scroll")

        # ── 비-JobKorea: 기존 locator 단일 캡처 ──
        elif not locator_capture_used:
            body_locator_found, body_locator = _detect_body_locator(page, adapter.site_name)
            print(f"[INFO] body_locator_found={str(body_locator_found).lower()} selector={body_locator}")
            if body_locator_found and body_locator:
                try:
                    loc = page.locator(body_locator).first
                    if loc.is_visible(timeout=2000):
                        png_path = output_dir / "page_001.png"
                        loc.screenshot(path=str(png_path))
                        locator_capture_used = True
                        locator_capture_selector = body_locator
                        raw_text_val = (loc.inner_text(timeout=2500) or "").strip()
                        first_capture_saved = True
                        page_idx = 2
                        print(f"[INFO] locator_capture_used=true selector={body_locator}")
                except Exception as loc_err:
                    print(f"[INFO] locator_capture_fallback reason={loc_err}")

        # ── 스크롤 fallback (locator 캡처 실패한 경우) ──
        if not locator_capture_used:
            while current < total_height and page_idx <= max_pages and scroll_attempts < max_scroll_attempts:
                page.evaluate(f"window.scrollTo(0, {current});")
                page.wait_for_timeout(1200)
                scroll_attempts += 1

                # Do not stop before at least one screenshot is saved.
                if first_capture_saved and end_selectors and (page_idx - 1) >= 2:
                    triggered_end_selector = _matched_capture_end_selector(page, end_selectors)
                    if triggered_end_selector:
                        print(f"[INFO] capture_stop_selector={triggered_end_selector}")
                        break

                png_path = output_dir / f"page_{page_idx:03d}.png"
                page.screenshot(path=str(png_path), full_page=False)
                first_capture_saved = True

                page_idx += 1
                current += step
                total_height = page.evaluate("() => document.body.scrollHeight")

                try:
                    current_text = (page.locator("body").inner_text(timeout=1000) or "").lower()
                except Exception:
                    current_text = ""
                has_stop_keyword = any(keyword.lower() in current_text for keyword in STOP_CAPTURE_KEYWORDS)
                if has_stop_keyword and (page_idx - 1) >= 2:
                    print("[INFO] capture_stop_reason=core_section_detected")
                    break

                if end_selectors:
                    triggered_end_selector = _matched_capture_end_selector(page, end_selectors)
                    if triggered_end_selector and (page_idx - 1) >= 2:
                        print(f"[INFO] capture_stop_selector={triggered_end_selector}")
                        break

        print(f"[INFO] first_capture_saved={str(first_capture_saved).lower()}")
        if not first_capture_saved:
            print("[WARN] first_capture_saved=false no image was captured")

        # raw_text fallback: locator 캡처 실패 시 body 전체
        if not raw_text_val:
            raw_text_val = (page.locator("body").inner_text(timeout=2500) or "").strip()

        return {
            "url": detail_url,
            "title": title,
            "raw_text": raw_text_val,
            "capture_count": page_idx - 1,
            "scroll_attempts": scroll_attempts,
            "first_capture_saved": first_capture_saved,
            "locator_capture_used": locator_capture_used,
            "locator_capture_selector": locator_capture_selector,
            "iframe_capture_used": iframe_capture_used,
            "iframe_url": iframe_url,
            "triggered_end_selector": triggered_end_selector,
            "company": site_meta.get("company", ""),
            "seniority_text": site_meta.get("seniority_text", ""),
            "seniority_text_source": site_meta.get("seniority_text_source", "fallback"),
            "employment_type": site_meta.get("employment_type", ""),
        }
    finally:
        page.close()
