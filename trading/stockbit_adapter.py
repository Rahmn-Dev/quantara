"""
Stockbit Adapter untuk Scraping Broker Summary / Bandarmologi

Membaca JWT Stockbit dari environment (STOCKBIT_TOKEN) dan mengakses 
API internal Stockbit secara langsung untuk mendapatkan Broker Summary.
Lebih cepat dan stabil daripada Playwright, asalkan token masih valid.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from curl_cffi import requests

log = logging.getLogger("quantara.stockbit_adapter")


class StockbitAdapter:
    """Adapter untuk fetching data Bandarmologi/Broker Summary dari Stockbit."""

    BASE_URL = "https://exodus.stockbit.com"

    def __init__(self, token: str | None = None) -> None:
        self.token = token or os.getenv("STOCKBIT_TOKEN")
        if not self.token:
            log.warning("STOCKBIT_TOKEN is not set in environment!")

        self.session = requests.Session(impersonate="chrome")
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Origin": "https://stockbit.com",
            "Referer": "https://stockbit.com/",
        })

    def fetch_broker_summary(self, symbol: str) -> dict | None:
        """Fetch the latest broker summary for a given symbol."""
        if not self.token:
            return None

        url = (
            f"{self.BASE_URL}/marketdetectors/{symbol}"
            "?transaction_type=TRANSACTION_TYPE_NET"
            "&market_board=MARKET_BOARD_REGULER"
            "&investor_type=INVESTOR_TYPE_ALL"
            "&limit=25"
            "&period=BROKER_SUMMARY_PERIOD_LATEST"
        )
        
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data", {}).get("broker_summary")
            elif resp.status_code == 401:
                log.error("Stockbit token expired or invalid (401 Unauthorized).")
            else:
                log.warning("Stockbit API returned %s: %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            log.warning("Failed to fetch Stockbit broksum for %s: %s", symbol, exc)
        return None

    def parse_flow_score(self, symbol: str, raw_data: dict | None) -> dict:
        """
        Parses Stockbit broker summary into Quantara standard format.
        
        Expected raw_data structure:
        {
            "brokers_buy": [
                {"blot": "457313", "bval": "3.075e11", "netbs_broker_code": "YU", "netbs_date": "20260903", ...},
            ],
            "brokers_sell": [
                ...
            ]
        }
        """
        result = {
            "symbol": symbol,
            "date": None,
            "cr1": None, "cr3": None, "cr5": None,
            "net_foreign_value": None,
            "institutional_score": 50.0,
            "top_brokers": [],
            "raw_available": False,
            "source": "stockbit",
        }

        if not raw_data:
            return result
        
        try:
            buy_list = raw_data.get("brokers_buy") or []
            sell_list = raw_data.get("brokers_sell") or []
            
            if not buy_list and not sell_list:
                return result

            # Ambil tanggal dari data pertama
            date_str = None
            if buy_list:
                date_str = buy_list[0].get("netbs_date")
            elif sell_list:
                date_str = sell_list[0].get("netbs_date")
            result["date"] = date_str

            buy_map = {}
            sell_map = {}
            
            # bval = buy value (rupiah)
            for item in buy_list:
                code = item.get("netbs_broker_code", "")
                val = float(item.get("bval", 0))
                buy_map[code] = buy_map.get(code, 0) + val
                
            for item in sell_list:
                code = item.get("netbs_broker_code", "")
                val = float(item.get("sval", 0))  # Assuming sval for sell value
                sell_map[code] = sell_map.get(code, 0) + val

            all_brokers = set(buy_map.keys()) | set(sell_map.keys())
            if not all_brokers:
                return result

            total_buy = sum(buy_map.values()) or 1
            total_activity = sum(buy_map.get(b, 0) + sell_map.get(b, 0) for b in all_brokers) or 1
            
            # Hitung konsentrasi
            sorted_buy = sorted(buy_map.values(), reverse=True)
            cr1 = round(sorted_buy[0] / total_buy * 100, 2) if sorted_buy else 0
            cr3 = round(sum(sorted_buy[:3]) / total_buy * 100, 2) if len(sorted_buy) >= 3 else cr1
            cr5 = round(sum(sorted_buy[:5]) / total_buy * 100, 2) if len(sorted_buy) >= 5 else cr3

            # Format top brokers
            sorted_brokers = sorted(
                all_brokers,
                key=lambda b: buy_map.get(b, 0) + sell_map.get(b, 0),
                reverse=True,
            )
            top_brokers = [
                {
                    "code": b,
                    "buy": round(buy_map.get(b, 0), 0),
                    "sell": round(sell_map.get(b, 0), 0),
                    "net": round(buy_map.get(b, 0) - sell_map.get(b, 0), 0),
                    "share_pct": round((buy_map.get(b, 0) + sell_map.get(b, 0)) / total_activity * 100, 2),
                }
                for b in sorted_brokers[:10]
            ]

            # Skoring Sederhana: Konsentrasi Top 3
            institutional_score = min(95, max(20, 20 + cr3 * 1.5 + cr1 * 0.5))

            result.update({
                "cr1": cr1, "cr3": cr3, "cr5": cr5,
                "institutional_score": round(institutional_score, 2),
                "top_brokers": top_brokers,
                "raw_available": True,
            })
            
        except Exception as exc:
            log.error("Failed parsing Stockbit data for %s: %s", symbol, exc)
            
        return result
