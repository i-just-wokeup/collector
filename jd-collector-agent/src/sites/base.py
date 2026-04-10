from abc import ABC, abstractmethod
from urllib.parse import quote

from playwright.sync_api import Page


class SiteAdapter(ABC):
    site_name: str

    @abstractmethod
    def build_search_url(self, keyword: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def collect_job_links(self, page: Page, search_url: str, max_links: int) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def extract_detail_meta(self, page: Page) -> dict:
        raise NotImplementedError

    def get_capture_max_pages(self) -> int:
        return 6

    def get_capture_end_selectors(self) -> list[str]:
        return []

    def make_absolute_url(self, href: str) -> str:
        return href

    @staticmethod
    def keyword_query(keyword: str) -> str:
        return quote(keyword)


def text_or_empty(page: Page, selector: str) -> str:
    try:
        value = page.locator(selector).first.text_content(timeout=1500)
        return (value or "").strip()
    except Exception:
        return ""


def find_by_patterns(text: str, patterns: list[str]) -> str:
    if not text:
        return ""
    for pattern in patterns:
        if pattern in text:
            return pattern
    return ""
