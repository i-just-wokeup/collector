from playwright.sync_api import Page

from sites.base import SiteAdapter, find_by_patterns, text_or_empty


class WantedAdapter(SiteAdapter):
    site_name = "wanted"

    def build_search_url(self, keyword: str) -> str:
        return f"https://www.wanted.co.kr/search?query={self.keyword_query(keyword)}&tab=position"

    def make_absolute_url(self, href: str) -> str:
        if href.startswith("http"):
            return href
        return f"https://www.wanted.co.kr{href}"

    def collect_job_links(self, page: Page, search_url: str, max_links: int) -> list[str]:
        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(2000)

        for _ in range(10):
            page.mouse.wheel(0, 7500)
            page.wait_for_timeout(900)

        selectors = [
            "a[href*='/wd/']",
            "[data-cy='position-item'] a[href]",
            "main a[href]",
        ]

        hrefs: list[str] = []
        for selector in selectors:
            try:
                found = page.eval_on_selector_all(
                    selector,
                    "els => els.map(e => e.getAttribute('href')).filter(Boolean)",
                )
                hrefs.extend(found)
            except Exception:
                continue

        links: list[str] = []
        seen = set()
        for href in hrefs:
            url = self.make_absolute_url(href)
            if "/wd/" not in url or "tab=position" in url:
                continue
            if url in seen:
                continue
            seen.add(url)
            links.append(url)
            if len(links) >= max_links:
                break
        return links

    def extract_detail_meta(self, page: Page) -> dict:
        title = (
            text_or_empty(page, "[data-cy='job-title']")
            or text_or_empty(page, "h1")
            or text_or_empty(page, "meta[property='og:title']")
        )
        company = (
            text_or_empty(page, "[data-cy='company-name']")
            or text_or_empty(page, "a[href*='/company/']")
            or text_or_empty(page, "meta[name='author']")
        )
        body_text = (page.locator("body").inner_text(timeout=2500) or "").strip()

        seniority_text = find_by_patterns(
            body_text,
            ["신입", "경력무관", "경력 무관", "3년", "4년", "5년", "7년", "10년"],
        )
        employment_type = find_by_patterns(
            body_text,
            ["정규직", "계약직", "인턴", "프리랜서", "파트타임"],
        )

        return {
            "posting_title": title,
            "company": company,
            "seniority_text": seniority_text,
            "employment_type": employment_type,
        }

    def get_capture_max_pages(self) -> int:
        return 3

    def get_capture_max_scrolls(self) -> int:
        return 10

    def get_capture_end_selectors(self) -> list[str]:
        return [
            "section:has-text('추천')",
            "section:has-text('유사')",
            "section:has-text('이 포지션과 비슷한')",
            "div:has-text('다른 포지션')",
            "section:has-text('광고')",
            "div:has-text('광고')",
            "footer",
        ]
