"""
IDX-BEI Adapter — Django integration layer for Indonesia Stock Exchange data.

Wraps the same IDX API endpoints used by nichsedge/idx-bei, adapted to
work directly inside the Quantara Django app without a separate sidecar.

Data sources:
  - Broker flow / Bandarmologi : IDX BrokerSummary API
  - Financial ratios           : IDX DigitalStatistic API
  - Foreign flow               : IDX StockSummary API (bid/foreign fields)
  - Audit risk                 : IDX CompanyProfile API
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

from django.utils import timezone

log = logging.getLogger("quantara.idx_bei")

# ---------------------------------------------------------------------------
# Shared HTTP client (uses curl_cffi for browser impersonation)
# ---------------------------------------------------------------------------

IDX_BASE = "https://www.idx.co.id/primary"

_DEFAULT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "referer": "https://www.idx.co.id/",
    "origin": "https://www.idx.co.id",
}


def _get(endpoint: str, params: dict | None = None, retries: int = 3, delay: float = 1.5) -> dict | None:
    """GET with exponential backoff & browser impersonation via curl_cffi."""
    try:
        from curl_cffi import requests as cffi_requests
        impersonate_arg = {"impersonate": "chrome"}
    except ImportError:
        import requests as cffi_requests
        impersonate_arg = {}

    url = endpoint if endpoint.startswith("http") else f"{IDX_BASE}{endpoint}"
    for attempt in range(retries):
        try:
            resp = cffi_requests.get(
                url,
                params=params,
                headers=_DEFAULT_HEADERS,
                timeout=30,
                **impersonate_arg,
            )
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (429, 503):
                time.sleep(delay * (2 ** attempt))
            else:
                log.warning("IDX API %s returned %s", url, resp.status_code)
                return None
        except Exception as exc:  # noqa: BLE001
            log.warning("IDX request attempt %d failed: %s", attempt + 1, exc)
            if attempt < retries - 1:
                time.sleep(delay * (2 ** attempt))
    return None


# ---------------------------------------------------------------------------
# Phase 1 — Broker Flow / Bandarmologi
# ---------------------------------------------------------------------------

class BrokerFlowAdapter:
    """
    Fetches broker summary from IDX and computes:
      - Top-N broker buy/sell volumes
      - Concentration ratios: CR1, CR3, CR5
      - Institutional score (0-100; higher = stronger bandar accumulation)
    """

    ENDPOINT = "/BrokerSummary/GetBrokerSummary"

    def fetch_raw(self, symbol: str, trading_date: str | None = None) -> dict | None:
        """Fetch raw broker summary for a stock on a given date (YYYYMMDD)."""
        date_str = trading_date or timezone.localdate().strftime("%Y%m%d")
        return _get(self.ENDPOINT, params={"idxCode": symbol, "tradingDate": date_str})

    def compute_flow_score(self, symbol: str, trading_date: str | None = None) -> dict:
        """
        Returns a dict with broker flow metrics ready to store in BrokerFlow model.
        Falls back to neutral 50 score if IDX API unavailable.
        """
        raw = self.fetch_raw(symbol, trading_date)
        result: dict[str, Any] = {
            "symbol": symbol,
            "date": trading_date or timezone.localdate().strftime("%Y%m%d"),
            "cr1": None,
            "cr3": None,
            "cr5": None,
            "net_foreign_value": None,
            "institutional_score": 50.0,
            "top_brokers": [],
            "raw_available": False,
        }

        if not raw:
            return result

        try:
            buy_items = raw.get("BrokerBuy", []) or []
            sell_items = raw.get("BrokerSell", []) or []

            buy_map: dict[str, float] = {}
            sell_map: dict[str, float] = {}

            for entry in buy_items:
                code = entry.get("BrokerCode", "")
                val = float(entry.get("TotalValue", 0) or 0)
                buy_map[code] = buy_map.get(code, 0) + val

            for entry in sell_items:
                code = entry.get("BrokerCode", "")
                val = float(entry.get("TotalValue", 0) or 0)
                sell_map[code] = sell_map.get(code, 0) + val

            all_brokers = set(buy_map) | set(sell_map)
            net_map = {b: buy_map.get(b, 0) - sell_map.get(b, 0) for b in all_brokers}
            total_buy = sum(buy_map.values()) or 1
            total_activity = sum(buy_map.get(b, 0) + sell_map.get(b, 0) for b in all_brokers) or 1

            sorted_buy = sorted(buy_map.values(), reverse=True)
            cr1 = round(sorted_buy[0] / total_buy * 100, 2) if sorted_buy else 0
            cr3 = round(sum(sorted_buy[:3]) / total_buy * 100, 2) if len(sorted_buy) >= 3 else cr1
            cr5 = round(sum(sorted_buy[:5]) / total_buy * 100, 2) if len(sorted_buy) >= 5 else cr3

            sorted_brokers = sorted(all_brokers, key=lambda b: buy_map.get(b, 0) + sell_map.get(b, 0), reverse=True)
            top_brokers = [
                {
                    "code": b,
                    "buy": round(buy_map.get(b, 0), 0),
                    "sell": round(sell_map.get(b, 0), 0),
                    "net": round(net_map.get(b, 0), 0),
                    "share_pct": round((buy_map.get(b, 0) + sell_map.get(b, 0)) / total_activity * 100, 2),
                }
                for b in sorted_brokers[:10]
            ]

            # CR3 is a strong proxy for bandar concentration
            # CR3 > 40% → strong institutional → score 70-95
            # CR3 < 15% → retail-dominated → score 20-45
            institutional_score = min(95, max(20, 20 + cr3 * 1.5 + cr1 * 0.5))

            result.update({
                "cr1": cr1,
                "cr3": cr3,
                "cr5": cr5,
                "institutional_score": round(institutional_score, 2),
                "top_brokers": top_brokers,
                "raw_available": True,
            })

        except Exception as exc:  # noqa: BLE001
            log.warning("BrokerFlowAdapter parse error for %s: %s", symbol, exc)

        return result


# ---------------------------------------------------------------------------
# Phase 2 — Financial Ratios (PER, ROE, DER, EPS)
# ---------------------------------------------------------------------------

class FinancialRatioAdapter:
    """Fetches financial ratio data from IDX DigitalStatistic API."""

    BASE_URL = "https://www.idx.co.id/primary/DigitalStatistic/GetApiDataPaginated"

    def fetch_all_ratios(self, year: int | None = None, quarter: int = 4) -> list[dict]:
        """Fetch paginated financial ratios for all listed companies."""
        if year is None:
            y = timezone.localdate().year
            # Use prior year if we are before Q4 of current year
            year = y - 1 if timezone.localdate().month < 4 else y

        all_records: list[dict] = []
        page = 1
        while True:
            data = _get(
                self.BASE_URL,
                params={
                    "urlName": "LINK_FINANCIAL_DATA_RATIO",
                    "periodQuarter": quarter,
                    "periodYear": year,
                    "type": "yearly",
                    "isPrint": "false",
                    "cumulative": "false",
                    "pageSize": 100,
                    "pageNumber": page,
                    "orderBy": "",
                    "search": "",
                },
            )
            if not data:
                break
            rows = data.get("Results", data.get("Data", []))
            if not rows:
                break
            all_records.extend(rows)
            total = data.get("Total", 0)
            if len(all_records) >= total or not rows:
                break
            page += 1
            time.sleep(0.3)

        return all_records

    @staticmethod
    def parse_ratio(row: dict) -> dict:
        """Extract and normalize ratio fields from a single API row."""
        def _f(val, default=None):
            try:
                return float(val) if val not in (None, "", "-", "N/A") else default
            except (TypeError, ValueError):
                return default

        return {
            "symbol": (row.get("StockCode") or row.get("Ticker") or "").strip().upper(),
            "per": _f(row.get("PriceEarningRatio") or row.get("PER")),
            "pbv": _f(row.get("PriceToBVRatio") or row.get("PBV")),
            "roe": _f(row.get("ReturnOnEquity") or row.get("ROE")),
            "der": _f(row.get("DebtToEquityRatio") or row.get("DER")),
            "eps": _f(row.get("EarningsPerShare") or row.get("EPS")),
            "revenue_growth": _f(row.get("RevenueGrowth")),
        }


# ---------------------------------------------------------------------------
# Phase 3 — Foreign Flow Radar
# ---------------------------------------------------------------------------

class ForeignFlowAdapter:
    """Fetches net foreign buy/sell from IDX StockSummary."""

    ENDPOINT = "/StockData/GetSecuritiesData"

    def fetch_stock_summary(self, trading_date: str | None = None) -> list[dict]:
        """Fetch all-stock summary for a given trading date (YYYYMMDD)."""
        date_str = trading_date or timezone.localdate().strftime("%Y%m%d")
        data = _get(self.ENDPOINT, params={"tradingDate": date_str, "start": 0, "length": 9999})
        if not data:
            return []
        return data.get("data", data.get("Data", []))

    @staticmethod
    def compute_foreign_signal(net_foreign_values: list[float]) -> str:
        """
        Given a list of daily net foreign values (positive = net buy),
        returns: ACCUMULATE / DISTRIBUTE / NEUTRAL.
        """
        if not net_foreign_values:
            return "NEUTRAL"
        recent = net_foreign_values[-5:]
        net = sum(recent)
        pos_days = sum(1 for v in recent if v > 0)
        if net > 0 and pos_days >= 3:
            return "ACCUMULATE"
        if net < 0 and pos_days <= 2:
            return "DISTRIBUTE"
        return "NEUTRAL"


# ---------------------------------------------------------------------------
# Phase 4 — Audit Risk + Dilution Watch
# ---------------------------------------------------------------------------

class AuditRiskAdapter:
    """
    Fetches company profile from IDX to detect non-clean audit opinions.
    Risky flags: WDP (Qualified), TMP (Adverse), TL (Disclaimer).
    """

    ENDPOINT = "/CompanyProfile/GetCompanyProfiles"
    RISKY_OPINIONS = {"WDP", "TMP", "TL", "TIDAK WAJAR", "DISCLAIMER"}
    DILUTION_TYPES = {"HMETD", "PMTHMETD", "WR", "PMTB", "PMTD", "PP", "PRIVATE PLACEMENT"}

    def fetch_company_profiles(self, start: int = 0, length: int = 9999) -> list[dict]:
        data = _get(self.ENDPOINT, params={"start": start, "length": length})
        if not data:
            return []
        return data.get("data", data.get("Data", []))

    def is_audit_risky(self, profile: dict) -> tuple[bool, str]:
        """Returns (is_risky, opinion_text)."""
        opinion = (
            (profile.get("AuditOpinion") or profile.get("OpiniAudit") or "")
            .strip()
            .upper()
        )
        for flag in self.RISKY_OPINIONS:
            if flag in opinion:
                return True, opinion
        return False, opinion

    def fetch_corporate_actions(self, symbol: str) -> list[dict]:
        """Fetch recent corporate actions for a stock."""
        data = _get(
            "/CorporateAction/GetCorporateAction",
            params={"idxCode": symbol, "start": 0, "length": 20},
        )
        if not data:
            return []
        return data.get("data", data.get("Data", []))

    def has_recent_dilution(self, actions: list[dict], lookback_days: int = 180) -> bool:
        """Returns True if there is a recent dilutive corporate action."""
        cutoff = date.today() - timedelta(days=lookback_days)
        for action in actions:
            ca_type = (action.get("CaType") or action.get("EventType") or "").upper()
            if any(dt in ca_type for dt in self.DILUTION_TYPES):
                eff_date_str = action.get("EffectiveDate") or action.get("RecordDate") or ""
                try:
                    from datetime import datetime as _dt
                    eff_date = _dt.strptime(eff_date_str[:10], "%Y-%m-%d").date()
                    if eff_date >= cutoff:
                        return True
                except (ValueError, TypeError):
                    pass
        return False
