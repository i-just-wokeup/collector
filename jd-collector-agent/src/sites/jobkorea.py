import re

from playwright.sync_api import Page

from sites.base import SiteAdapter, find_by_patterns, text_or_empty

_GI_READ_RE = re.compile(r"/Recruit/GI_Read/(\d+)", re.IGNORECASE)


def normalize_jobkorea_url(url: str) -> str:
    """쿼리스트링을 제거하고 /Recruit/GI_Read/{id} 기준 정규 URL을 반환한다."""
    m = _GI_READ_RE.search(url)
    if m:
        return f"https://www.jobkorea.co.kr/Recruit/GI_Read/{m.group(1)}"
    return url


class JobKoreaAdapter(SiteAdapter):
    site_name = "jobkorea"

    def build_search_url(self, keyword: str) -> str:
        return f"https://www.jobkorea.co.kr/Search/?stext={self.keyword_query(keyword)}"

    def build_top100_category_url(self, biz_code: int) -> str:
        return (
            f"https://www.jobkorea.co.kr/Top100/"
            f"?Main_Career_Type=1&Search_Type=1&BizJobtype_Bctgr_Code={biz_code}"
        )

    def make_absolute_url(self, href: str) -> str:
        if href.startswith("http"):
            return href
        return f"https://www.jobkorea.co.kr{href}"

    def collect_job_links(self, page: Page, search_url: str, max_links: int) -> list[str]:
        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)

        for _ in range(8):
            page.mouse.wheel(0, 6500)
            page.wait_for_timeout(900)

        selectors = [
            "a[href*='/Recruit/GI_Read/']",
            "a[href*='Recruit/GI_Read']",
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
            raw_url = self.make_absolute_url(href)
            if "/Recruit/GI_Read/" not in raw_url:
                continue
            url = normalize_jobkorea_url(raw_url)
            if url in seen:
                continue
            seen.add(url)
            links.append(url)
            if len(links) >= max_links:
                break
        return links

    def extract_detail_meta(self, page: Page) -> dict:
        title = (
            text_or_empty(page, ".hd h1")
            or text_or_empty(page, "h1")
            or text_or_empty(page, "meta[property='og:title']")
        )
        company = (
            text_or_empty(page, ".coName")
            or text_or_empty(page, "a[href*='/Company/']")
            or text_or_empty(page, "meta[name='author']")
        )
        body_text = (page.locator("body").inner_text(timeout=2500) or "").strip()

        seniority_text = find_by_patterns(
            body_text,
            ["신입", "경력무관", "경력 무관", "2년", "3년", "5년", "7년", "10년"],
        )
        employment_type = find_by_patterns(
            body_text,
            ["정규직", "계약직", "인턴", "프리랜서", "파견직"],
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
            "section:has-text('추천채용')",
            "section:has-text('유사공고')",
            "div:has-text('광고')",
            "section:has-text('다른 공고')",
            "div:has-text('배너')",
            "footer",
        ]
