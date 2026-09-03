import html
import re

import requests
from django.utils import timezone

from .models import Instrument

KSEI_SHARES_URL = "https://web.ksei.co.id/services/registered-securities/shares?setLocale=id-ID"
ROW_PATTERN = re.compile(
    r'/services/registered-securities/shares/lc/(?P<symbol>[A-Z0-9]+)">[^<]+</a>'
    r"\s*</td>\s*<td>(?P<name>.*?)</td>",
    re.DOTALL,
)


def discover_idx_universe(session=None):
    """Discover share codes from KSEI's public registered-shares catalogue."""
    client = session or requests.Session()
    response = client.get(
        KSEI_SHARES_URL, timeout=45, headers={"User-Agent": "Quantara/0.1 personal research"}
    )
    response.raise_for_status()
    matches = []
    for match in ROW_PATTERN.finditer(response.text):
        symbol = match.group("symbol").strip()
        if re.fullmatch(r"[A-Z]{4}", symbol):
            name = re.sub(r"<[^>]+>", "", match.group("name"))
            matches.append((symbol, html.unescape(name).strip()))
    if len(matches) < 500:
        raise ValueError(f"Universe discovery returned only {len(matches)} share codes")
    return dict(matches)


def sync_idx_universe(session=None):
    discovered = discover_idx_universe(session=session)
    Instrument.objects.update(is_active=False)
    for symbol, name in discovered.items():
        Instrument.objects.update_or_create(
            symbol=symbol, defaults={"name": name, "is_active": True}
        )
    return len(discovered), timezone.now()
