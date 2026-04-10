from pathlib import Path

from playwright.sync_api import BrowserContext
from sites.base import SiteAdapter

STOP_CAPTURE_KEYWORDS = ["자격 요건", "우대 사항", "requirements", "preferred"]


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
        body_locator_found, body_locator = _detect_body_locator(page, adapter.site_name)
        print(f"[INFO] body_locator_found={str(body_locator_found).lower()} selector={body_locator}")
        total_height = page.evaluate("() => document.body.scrollHeight")

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

        return {
            "url": detail_url,
            "title": title,
            "raw_text": (page.locator("body").inner_text(timeout=2500) or "").strip(),
            "capture_count": page_idx - 1,
            "scroll_attempts": scroll_attempts,
            "first_capture_saved": first_capture_saved,
            "body_locator_found": body_locator_found,
            "body_locator_selector": body_locator,
            "triggered_end_selector": triggered_end_selector,
            "company": site_meta.get("company", ""),
            "seniority_text": site_meta.get("seniority_text", ""),
            "seniority_text_source": site_meta.get("seniority_text_source", "fallback"),
            "employment_type": site_meta.get("employment_type", ""),
        }
    finally:
        page.close()
