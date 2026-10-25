"""Seasonal moments a brand's campaign should plan around, by country.

Fixed dates are exact. Islamic holidays depend on the moon sighting, so they're marked as
expected dates (±1 day); Diwali follows the Hindu lunar calendar and is listed per year.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

MUSLIM_MAJORITY = {"PK", "AE", "SA", "BD", "ID", "MY", "EG", "TR", "QA", "KW", "OM", "BH", "JO", "MA"}
DOUBLE_DAY_SALES = {"PK", "BD", "MY", "SG", "ID", "PH", "TH", "VN", "CN"}  # 11.11 / 12.12 marketplaces
BLACK_FRIDAY = {"US", "GB", "CA", "AU", "NZ", "IE", "DE", "FR", "ES", "IT", "NL", "AE", "SA", "PK", "IN", "ZA", "BR", "MX"}
MOTHERS_DAY_MAY = {"US", "CA", "AU", "NZ", "PK", "IN", "DE", "IT", "NL", "ZA", "JP"}

COUNTRY_NAMES = {
    "PK": "Pakistan", "IN": "India", "AE": "the UAE", "SA": "Saudi Arabia", "BD": "Bangladesh", "GB": "the UK",
    "US": "the US", "CA": "Canada", "AU": "Australia", "NZ": "New Zealand", "IE": "Ireland", "DE": "Germany",
    "FR": "France", "ES": "Spain", "IT": "Italy", "NL": "the Netherlands", "TR": "Turkey", "EG": "Egypt",
    "MY": "Malaysia", "SG": "Singapore", "ID": "Indonesia", "PH": "the Philippines", "ZA": "South Africa",
    "NG": "Nigeria", "KE": "Kenya", "QA": "Qatar", "KW": "Kuwait", "OM": "Oman", "BH": "Bahrain",
}

# (Ramadan begins, Eid al-Fitr, Eid al-Adha), expected dates.
ISLAMIC = {
    2026: (date(2026, 2, 18), date(2026, 3, 20), date(2026, 5, 27)),
    2027: (date(2027, 2, 8), date(2027, 3, 10), date(2027, 5, 17)),
    2028: (date(2028, 1, 28), date(2028, 2, 27), date(2028, 5, 5)),
}
DIWALI = {2026: date(2026, 11, 8), 2027: date(2027, 10, 29), 2028: date(2028, 10, 17)}


@dataclass(frozen=True)
class Moment:
    day: date
    name: str
    kind: str  # sale | holiday | season
    expected: bool = False  # date depends on the moon sighting

    def label(self) -> str:
        when = self.day.strftime("%d %b").lstrip("0")
        return f"{self.name} ({'expected ' if self.expected else ''}{when})"


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def moments_for_year(year: int, country: str) -> list[Moment]:
    c = country.upper()
    m: list[Moment] = [
        Moment(date(year, 1, 1), "New Year", "holiday"),
        Moment(date(year, 2, 14), "Valentine's Day", "holiday"),
        Moment(date(year, 3, 8), "International Women's Day", "holiday"),
        Moment(date(year, 12, 31), "New Year's Eve", "holiday"),
    ]
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    if c in BLACK_FRIDAY or not c:
        m.append(Moment(thanksgiving + timedelta(days=1), "Black Friday" + (" / White Friday" if c == "PK" else ""), "sale"))
    if c in {"US", "GB", "CA", "AU"}:
        m.append(Moment(thanksgiving + timedelta(days=4), "Cyber Monday", "sale"))
    if c in DOUBLE_DAY_SALES:
        m += [Moment(date(year, 11, 11), "11.11 sale", "sale"), Moment(date(year, 12, 12), "12.12 sale", "sale")]
    if c in MOTHERS_DAY_MAY or not c:
        m.append(Moment(_nth_weekday(year, 5, 6, 2), "Mother's Day", "holiday"))
    if c in {"US", "CA", "GB", "PK", "IN", "AU"} or not c:
        m.append(Moment(_nth_weekday(year, 6, 6, 3) if c != "AU" else _nth_weekday(year, 9, 6, 1), "Father's Day", "holiday"))
    if c in {"US", "CA", "GB", "IE", "AU", "NZ", "DE", "FR", "ES", "IT", "NL", "ZA", "IN"} or not c:
        m.append(Moment(date(year, 12, 25), "Christmas", "holiday"))
    if c in {"US", "CA", "GB"}:
        m.append(Moment(date(year, 8, 15), "Back to school", "season"))
    if c == "PK":
        m += [Moment(date(year, 3, 23), "Pakistan Day", "holiday"), Moment(date(year, 8, 14), "Independence Day", "holiday"),
              Moment(date(year, 12, 25), "Quaid-e-Azam Day", "holiday"), Moment(date(year, 11, 15), "Wedding season", "season")]
    if c == "IN":
        m += [Moment(date(year, 8, 15), "Independence Day", "holiday"), Moment(date(year, 1, 26), "Republic Day", "holiday")]
        if year in DIWALI:
            m.append(Moment(DIWALI[year], "Diwali", "holiday"))
    if c == "AE":
        m.append(Moment(date(year, 12, 2), "UAE National Day", "holiday"))
    if c == "SA":
        m.append(Moment(date(year, 9, 23), "Saudi National Day", "holiday"))
    if c in {"PK", "IN"}:
        m += [Moment(date(year, 10, 1), "Winter collection season", "season"), Moment(date(year, 4, 1), "Summer collection season", "season")]
    if (c in MUSLIM_MAJORITY or c == "IN") and year in ISLAMIC:
        ramadan, fitr, adha = ISLAMIC[year]
        m += [Moment(ramadan, "Ramadan begins", "holiday", True), Moment(fitr, "Eid al-Fitr", "holiday", True),
              Moment(adha, "Eid al-Adha", "holiday", True)]
    return m


def ongoing(country: str, start: date, within: int = 60) -> list[Moment]:
    """Seasons that began shortly before the campaign and are still running (e.g. winter collections)."""
    begin = start - timedelta(days=within)
    found = [mo for y in {begin.year, start.year} for mo in moments_for_year(y, country)
             if mo.kind == "season" and begin <= mo.day < start]
    return sorted(set(found), key=lambda mo: mo.day, reverse=True)


def upcoming(country: str, start: date, days: int, lead: int = 10) -> list[Moment]:
    """Moments inside the campaign window, plus ones just after it that posts should build up to."""
    end = start + timedelta(days=days + lead)
    found = [mo for y in {start.year, end.year} for mo in moments_for_year(y, country) if start <= mo.day <= end]
    return sorted(set(found), key=lambda mo: mo.day)
