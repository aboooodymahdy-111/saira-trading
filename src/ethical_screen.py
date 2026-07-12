"""
ethical_screen.py — Mechanical ethical exclusion filter for Abdo's investable
universe (project decision, 2026-07).

WHY THIS MODULE: Abdo does not want to invest in weapons/defense or banks, nor
in any company that supports the Israeli occupation or has a business
relationship with it. Mainstream Islamic-finance screening apps (Zoya,
Islamicly, Musaffa) were tried and rejected as too lenient for his standard,
so this implements his own explicit criteria directly instead of deferring to
a third-party methodology.

TWO DIFFERENT KINDS OF CHECK HERE, DELIBERATELY KEPT SEPARATE:
    1. SECTOR-BASED (mechanical, generalizes to ANY ticker): banks and
       aerospace/defense are identified from yfinance's own sector/industry
       classification — no manual list needed, works on tickers never seen
       before.
    2. NAMED-TICKER EXCLUSION (BDS_EXCLUDED_TICKERS): the "supports the
       occupation" criterion has no equivalent structured field in yfinance,
       so this uses the BDS Movement's own published boycott list
       (bdsmovement.net/get-involved/what-to-boycott, fetched 2026-07) as the
       source of truth, per Abdo's explicit choice of that source over the UN
       OHCHR database or a self-defined list. Only entries with an ACTUAL
       NASDAQ/NYSE-listed ticker are included below — most named brands
       (Siemens, Carrefour, AXA, Reebok) trade on other exchanges or are
       privately held and are simply absent from the scanned universe
       already (full_universe_analysis.py only walks NASDAQ/NYSE folders), so
       no ticker mapping was attempted for those.

       THIS LIST IS A SNAPSHOT, NOT AUTO-UPDATING: BDS Movement updates their
       page periodically. Re-check bdsmovement.net/get-involved/what-to-boycott
       occasionally and update BDS_EXCLUDED_TICKERS by hand — deliberately not
       auto-scraped on every run, so a page change can't silently alter
       Abdo's investable universe unreviewed.
"""

from __future__ import annotations

from dataclasses import dataclass

import yfinance as yf

from yf_retry import call_with_retry

BANK_INDUSTRY_KEYWORDS = (
    "bank",
    "capital markets",
    "credit services",
    "mortgage",
    "savings",
)
# NOTE (2026-07, fixed after "bank",-only keyword let NMR/Nomura and AXP/Amex
# through under industry="Capital Markets"/"Credit Services"): not every
# "Financial Services" sector industry belongs here — insurance, real estate
# services, and specialty finance are financial-adjacent but not banking, so
# they're deliberately left off this list. Re-review this list periodically
# against the "industry" column now saved in runs/full_universe_results.csv.
DEFENSE_INDUSTRY_KEYWORDS = (
    "aerospace",
    "defense",
    "defence",
    "military",
    "weapons",
    "arms",
    "ammunition",
)

# BDS Movement boycott list (bdsmovement.net/get-involved/what-to-boycott,
# fetched 2026-07) — NASDAQ/NYSE-listed tickers only. See module docstring for
# what was deliberately left out and why.
BDS_EXCLUDED_TICKERS: dict[str, str] = {
    "CVX": "Chevron — fossil fuel extraction from occupied territories (BDS)",
    "INTC": "Intel — military-technology complicity, settlement facility (BDS)",
    "DELL": "Dell Technologies — servers supplied to Israeli military (BDS)",
    "HPQ": "HP Inc. — technology to Israeli military/government/prisons (BDS)",
    "HPE": "Hewlett Packard Enterprise — same HP complicity listing (BDS)",
    "MSFT": "Microsoft — Azure/AI services to Israeli military (BDS)",
    "DIS": "Walt Disney (Disney+) — propaganda/cultural glorification listing (BDS)",
    "RMAX": "RE/MAX — settlement real estate listings (BDS)",
    "GOOG": "Alphabet/Google — Project Nimbus military AI contract (BDS)",
    "GOOGL": "Alphabet/Google — Project Nimbus military AI contract (BDS)",
    "AMZN": "Amazon — Project Nimbus military AI contract (BDS)",
    "BKNG": "Booking Holdings — settlement tourism, UN database listed (BDS)",
    "ABNB": "Airbnb — settlement tourism listings (BDS)",
    "EXPE": "Expedia — settlement tourism listings (BDS)",
    "TEVA": "Teva Pharmaceutical — genocide support/occupation exploitation (BDS)",
    "MCD": "McDonald's — grassroots boycott, support for Israeli military (BDS)",
    "KO": "Coca-Cola — grassroots boycott, support for Israeli military (BDS)",
    "QSR": "Restaurant Brands Intl (Burger King) — grassroots boycott (BDS)",
    "PZZA": "Papa John's — grassroots boycott (BDS)",
    "YUM": "Yum! Brands (Pizza Hut) — grassroots boycott (BDS)",
    "DPZ": "Domino's Pizza — grassroots boycott (BDS)",
    "PEP": "PepsiCo (SodaStream) — Naqab Bedouin-Palestinian displacement (BDS)",
    "WIX": "Wix.com — grassroots boycott (BDS)",
}


@dataclass
class EthicalScreenResult:
    excluded: bool
    reason: str | None
    sector: str
    industry: str


def get_sector_and_industry(ticker: str) -> tuple[str, str]:
    """
    One yfinance .info call for both fields, so callers don't pay for two
    separate network round-trips (sector alone, then industry alone).
    Deliberately does NOT catch fetch exceptions here — propagating them lets
    screen_ticker distinguish "the lookup itself failed" (network/rate-limit,
    fail closed) from "the lookup succeeded but Yahoo has no sector/industry
    for this ticker" (common for delisted/data-poor tickers, which the price
    history fetch will skip on its own — not an ethical-review case).
    """
    info = call_with_retry(lambda: yf.Ticker(ticker).info)
    return info.get("sector") or "unknown", info.get("industry") or "unknown"


def screen_ticker(ticker: str) -> EthicalScreenResult:
    """
    Checks ticker against Abdo's exclusion criteria (2026-07): weapons/defense,
    banks, and the BDS Movement boycott list. BDS-list membership is checked
    first (free, no network call) before paying for a sector/industry lookup.
    """
    ticker = ticker.upper()
    if ticker in BDS_EXCLUDED_TICKERS:
        return EthicalScreenResult(True, BDS_EXCLUDED_TICKERS[ticker], "unknown", "unknown")

    # Fail CLOSED, not open, but ONLY on an actual fetch failure (network/rate
    # limit) — per Abdo's priority (2026-07), avoiding these categories
    # matters more than not missing a candidate. A ticker that simply has no
    # sector/industry data (typically delisted/data-poor) is NOT flagged here;
    # it isn't excluded by sector, but analyze_ticker's price-history check
    # will skip it anyway once it can't fetch history either.
    try:
        sector, industry = get_sector_and_industry(ticker)
    except Exception as exc:  # noqa: BLE001 - message decides retry vs propagate happens in yf_retry
        print(f"WARNING: sector/industry lookup failed for {ticker}: {exc}")
        return EthicalScreenResult(True, "sector/industry lookup failed — needs manual review", "unknown", "unknown")

    industry_lower = industry.lower()

    if any(kw in industry_lower for kw in BANK_INDUSTRY_KEYWORDS):
        return EthicalScreenResult(True, f"excluded sector: banks (industry={industry})", sector, industry)
    if any(kw in industry_lower for kw in DEFENSE_INDUSTRY_KEYWORDS):
        return EthicalScreenResult(True, f"excluded sector: weapons/defense (industry={industry})", sector, industry)

    return EthicalScreenResult(False, None, sector, industry)
