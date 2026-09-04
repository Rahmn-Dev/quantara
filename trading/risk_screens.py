"""
Phase 4 — Audit Risk & Dilution Watch

Syncs audit opinions and corporate actions from IDX, updating Instrument
risk flags (audit_risky, has_recent_dilution). These flags are used by
scanner.py to apply hard VETOs before analysis.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from .idx_bei_adapter import AuditRiskAdapter
from .models import Instrument

log = logging.getLogger("quantara.risk_screens")


def sync_audit_risk() -> dict:
    """
    Fetch company profiles from IDX and update audit_risky / audit_opinion
    fields on all active Instrument records.

    Returns summary dict: {updated, clean, risky, errors}.
    """
    adapter = AuditRiskAdapter()
    log.info("Fetching company profiles for audit risk screening...")
    profiles = adapter.fetch_company_profiles()

    if not profiles:
        log.warning("No company profiles returned from IDX.")
        return {"updated": 0, "clean": 0, "risky": 0, "errors": ["IDX API returned no data"]}

    # Build a lookup map: symbol -> profile
    profile_map: dict[str, dict] = {}
    for p in profiles:
        sym = (p.get("StockCode") or p.get("KodeEmiten") or "").strip().upper()
        if sym:
            profile_map[sym] = p

    updated, clean, risky, errors = 0, 0, 0, []
    now = timezone.now()

    for instrument in Instrument.objects.filter(is_active=True):
        profile = profile_map.get(instrument.symbol)
        if not profile:
            continue
        try:
            is_risky, opinion = adapter.is_audit_risky(profile)
            instrument.audit_risky = is_risky
            instrument.audit_opinion = opinion[:40] if opinion else ""
            instrument.risk_flags_updated_at = now
            instrument.save(update_fields=["audit_risky", "audit_opinion", "risk_flags_updated_at"])
            updated += 1
            if is_risky:
                risky += 1
                log.info("AUDIT RISKY: %s (%s)", instrument.symbol, opinion)
            else:
                clean += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{instrument.symbol}: {exc}")

    log.info("Audit risk sync done: %d updated, %d risky, %d clean, %d errors",
             updated, risky, clean, len(errors))
    return {"updated": updated, "clean": clean, "risky": risky, "errors": errors}


def sync_dilution_watch() -> dict:
    """
    Check recent corporate actions for dilutive events (rights issue, warrants,
    private placements) and update has_recent_dilution on Instrument.

    Returns summary dict: {checked, dilution_flagged, errors}.
    """
    adapter = AuditRiskAdapter()
    checked, dilution_flagged, errors = 0, 0, []
    now = timezone.now()

    for instrument in Instrument.objects.filter(is_active=True):
        try:
            actions = adapter.fetch_corporate_actions(instrument.symbol)
            has_dilution = adapter.has_recent_dilution(actions, lookback_days=180)
            instrument.has_recent_dilution = has_dilution
            instrument.risk_flags_updated_at = now
            instrument.save(update_fields=["has_recent_dilution", "risk_flags_updated_at"])
            checked += 1
            if has_dilution:
                dilution_flagged += 1
                log.info("DILUTION WARNING: %s", instrument.symbol)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{instrument.symbol}: {exc}")

    log.info("Dilution watch done: %d checked, %d flagged, %d errors",
             checked, dilution_flagged, len(errors))
    return {"checked": checked, "dilution_flagged": dilution_flagged, "errors": errors}
