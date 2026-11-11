import re

from planner.core import utils as fp

_MULTIPLIERS = {
    "k": 1_000,
    "thousand": 1_000,
    "grand": 1_000,
    "m": 1_000_000,
    "million": 1_000_000,
    "bn": 1_000_000_000,
    "billion": 1_000_000_000,
}

_AMOUNT = re.compile(
    r"^\s*(?P<sign_before>-)?\s*"
    r"(?:(?:£|€|\$|₦|GBP|NGN|USD|EUR)\s*)?"
    r"(?P<sign_after>-)?\s*"
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<multiplier>billion|million|thousand|grand|bn|m|k)?\s*"
    r"(?:(?:pounds?|sterling|naira|dollars?|euros?|GBP|NGN|USD|EUR)\s*)?"
    r"(?:(?:salary|income|pay|profit|dividend|reserves|savings|amount|"
    r"contribution|pension|bonus|job|package|sacrifice|turnover|revenue)\s*){0,2}"
    r"(?P<frequency>a year|per year|annually|annual|yearly|per annum|p\.a\.|pa|"
    r"a month|per month|monthly|a week|per week|weekly|an hour|per hour|hourly|"
    r"a day|per day|daily)?\s*$",
    re.IGNORECASE,
)

_RATE = re.compile(
    r"^\s*(?P<number>\d+(?:\.\d+)?)\s*"
    r"(?P<percent>%|percent|per cent|pct|pc)?\s*$",
    re.IGNORECASE,
)

_YEARS = re.compile(r"^\s*(?P<number>\d+)\s*(?:years?|yrs?|y)?\s*$", re.IGNORECASE)

_NON_ANNUAL = ("month", "week", "hour", "day", "daily")


def parse_amount(raw: str) -> int:
    """
    Parse an amount written by a user.

    Accepts thousands separators, currency symbols or codes, and shorthand multipliers such as `k`, `grand`, `million`, and `billion`. Monthly, weekly, daily and hourly amounts are rejected so they cannot be mistaken for annual figures.

    Args:
        - raw: The amount, for example `45,000`, `£45,000.50`, `45k`, or `12 million naira`.

    Returns:
        The amount at `SCALE`.

    Raises:
        ValueError: If the text is not an annual amount.
    """
    match = _AMOUNT.match(raw)
    if match is None:
        raise ValueError(f"not an amount: {raw!r}")
    frequency = (match["frequency"] or "").lower()
    if any(word in frequency for word in _NON_ANNUAL):
        raise ValueError(f"amount is not annual: {raw!r}")
    number = match["number"].replace(",", "")
    if match["sign_before"] or match["sign_after"]:
        number = "-" + number
    base = fp.parse(number)
    multiplier = _MULTIPLIERS.get((match["multiplier"] or "").lower(), 1)
    return base * multiplier


def parse_rate(raw: str) -> int:
    """
    Parse a rate written as a decimal or a percentage.

    Args:
        - raw: The rate, for example `6%`, `6 percent`, `6`, or `0.06`.

    Returns:
        The rate at `SCALE`.

    Raises:
        ValueError: If the rate is not between 0 and 1.
    """
    match = _RATE.match(raw)
    if match is None:
        raise ValueError(f"not a rate: {raw!r}")
    value = fp.parse(match["number"])
    if match["percent"] or value > fp.SCALE:
        value //= 100
    if not 0 <= value <= fp.SCALE:
        raise ValueError(f"not a rate: {raw!r}")
    return value


def parse_years(raw: str | int) -> int:
    """
    Parse a number of years.

    Args:
        - raw: The number of years, for example `10`, `10 years`, or `10y`.

    Returns:
        The number of years.

    Raises:
        ValueError: If the value is not between 1 and 100.
    """
    if isinstance(raw, int):
        years = raw
    else:
        match = _YEARS.match(raw)
        if match is None:
            raise ValueError(f"not a number of years: {raw!r}")
        years = int(match["number"])
    if not 1 <= years <= 100:
        raise ValueError(f"not a number of years: {raw!r}")
    return years
