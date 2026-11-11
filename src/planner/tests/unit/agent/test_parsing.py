import pytest

from planner.agent.parsing import parse_amount, parse_rate, parse_years


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("45,000", 450_000_000),
        ("£45,000.50", 450_005_000),
        ("45k", 450_000_000),
        ("£45k", 450_000_000),
        ("45 K", 450_000_000),
        ("45 grand", 450_000_000),
        ("£60k", 600_000_000),
        ("12 million naira", 120_000_000_000),
        ("12m naira", 120_000_000_000),
        ("12 million naira per year", 120_000_000_000),
        ("1.2m", 12_000_000_000),
        ("45k a year", 450_000_000),
        ("£60k salary sacrifice", 600_000_000),
        ("£85k job", 850_000_000),
        ("45k salary", 450_000_000),
        ("-£5,000", -50_000_000),
        ("£-5,000", -50_000_000),
    ],
)
def test_parse_amount_accepts_shorthand(raw: str, expected: int) -> None:
    assert parse_amount(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "45kg",
        "3,500 a month",
        "45k per week",
        "45k per hour",
        "45k daily",
        "not an amount",
    ],
)
def test_parse_amount_rejects_non_annual_or_unknown(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_amount(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("6%", 600),
        ("6 percent", 600),
        ("6 per cent", 600),
        ("6pct", 600),
        ("6pc", 600),
        ("0.06", 600),
        ("6", 600),
        ("6.5%", 650),
        ("100%", 10_000),
    ],
)
def test_parse_rate_accepts_percent_words(raw: str, expected: int) -> None:
    assert parse_rate(raw) == expected


@pytest.mark.parametrize("raw", ["150%", "not a rate", "-6%"])
def test_parse_rate_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_rate(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10", 10),
        ("10 years", 10),
        ("10 year", 10),
        ("10y", 10),
        ("10 yrs", 10),
        (10, 10),
    ],
)
def test_parse_years_accepts_suffixes(raw: str | int, expected: int) -> None:
    assert parse_years(raw) == expected


@pytest.mark.parametrize("raw", ["0", "101", "10.5", "ten"])
def test_parse_years_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_years(raw)
