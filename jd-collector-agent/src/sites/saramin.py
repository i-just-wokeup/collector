from playwright.sync_api import Page

from sites.base import SiteAdapter, find_by_patterns, text_or_empty


class SaraminAdapter(SiteAdapter):
    site_name = "saramin"

    def build_search_url(self, keyword: str) -> str:
        return (
            "https://www.saramin.co.kr/zf_user/search"
            f"?searchType=search&searchword={self.keyword_query(keyword)}"
        )

    def make_absolute_url(self, href: str) -> str:
        if href.startswith("http"):
            return href
        return f"https://www.saramin.co.kr{href}"

    def collect_job_links(self, page: Page, search_url: str, max_links: int) -> list[str]:
        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)

        for _ in range(8):
            page.mouse.wheel(0, 6000)
            page.wait_for_timeout(900)

        selectors = [
            "a[href*='/zf_user/jobs/relay/view']",
            "a[href*='/zf_user/jobs/view']",
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
            if "/zf_user/jobs/" not in url:
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
            text_or_empty(page, ".tit_job")
            or text_or_empty(page, "h1")
            or text_or_empty(page, "meta[property='og:title']")
        )
        company = (
            text_or_empty(page, ".company_name")
            or text_or_empty(page, "a[href*='/company-info/']")
            or text_or_empty(page, "meta[name='author']")
        )
        body_text = (page.locator("body").inner_text(timeout=2500) or "").strip()

        seniority_text = ""
        seniority_source = "fallback"
        seniority_selectors = [
            ".job_condition dl:has(dt:has-text('경력')) dd",
            ".jv_summary .col:has(.tit:has-text('경력')) .txt",
            "dl:has(dt:has-text('경력')) dd",
            "li:has(span:has-text('경력'))",
        ]
        for selector in seniority_selectors:
            candidate = text_or_empty(page, selector)
            if candidate:
                seniority_text = candidate
                seniority_source = "dom"
                break
        if not seniority_text:
            seniority_text = find_by_patterns(
                body_text,
                ["신입", "경력무관", "경력 무관", "1년", "2년", "3년", "5년", "7년", "10년"],
            )

        employment_type = find_by_patterns(
            body_text,
            ["정규직", "계약직", "인턴", "파견직", "프리랜서"],
        )

        return {
            "posting_title": title,
            "company": company,
            "seniority_text": seniority_text,
            "seniority_text_source": seniority_source,
            "employment_type": employment_type,
        }

    def get_capture_max_pages(self) -> int:
        return 3

    def get_capture_max_scrolls(self) -> int:
        return 10

    def get_capture_end_selectors(self) -> list[str]:
        return [
            "section:has-text('이 공고와 유사한 공고')",
            "section:has-text('함께 보면 좋은 공고')",
            "div:has-text('추천공고 더보기')",
        ]

    def get_noise_hide_script(self) -> str:
        return """
            const anchor = document.querySelector('section.store_recommend_section');
            if (anchor) {
                let el = anchor;
                while (el) {
                    const next = el.nextElementSibling;
                    el.style.display = 'none';
                    el = next;
                }
            }
        """
