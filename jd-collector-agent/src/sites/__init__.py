from sites.base import SiteAdapter
from sites.jobkorea import JobKoreaAdapter
from sites.saramin import SaraminAdapter
from sites.wanted import WantedAdapter


SUPPORTED_SITE_NAMES = ("wanted", "saramin", "jobkorea")


def get_site_adapter(site_name: str) -> SiteAdapter:
    normalized = site_name.strip().lower()
    adapter_map = {
        "wanted": WantedAdapter,
        "saramin": SaraminAdapter,
        "jobkorea": JobKoreaAdapter,
    }
    if normalized not in adapter_map:
        raise ValueError("site_name must be one of: wanted, saramin, jobkorea")
    return adapter_map[normalized]()
