"""Unit tests for pure portfolio financial variation calculations."""

from decimal import Decimal

from portfoliomaster.core.calculations import (
    daily_variation,
    decline_to_target,
    variation_since_analysis,
    ytd_variation,
)


def test_daily_variation():
    result = daily_variation(Decimal("110"), Decimal("100"))
    assert result.daily_variation == Decimal("10.00")
    assert result.daily_variation_valid is True

    result = daily_variation(Decimal("90"), Decimal("100"))
    assert result.daily_variation == Decimal("-10.00")

    assert daily_variation(Decimal("110"), None).daily_variation_valid is False
    assert daily_variation(Decimal("110"), Decimal("0")).daily_variation_valid is False


def test_variation_since_analysis():
    result = variation_since_analysis(Decimal("120"), Decimal("100"))
    assert result.variation_since_analysis == Decimal("20.00")
    assert result.variation_since_analysis_valid is True

    assert variation_since_analysis(Decimal("120"), None).variation_since_analysis_valid is False
    assert variation_since_analysis(Decimal("120"), Decimal("0")).variation_since_analysis_valid is False


def test_ytd_variation():
    result = ytd_variation(Decimal("120"), Decimal("100"))
    assert result.ytd_variation == Decimal("20.00")
    assert result.ytd_variation_valid is True

    result = ytd_variation(Decimal("85"), Decimal("100"))
    assert result.ytd_variation == Decimal("-15.00")
    assert result.ytd_variation_valid is True

    assert ytd_variation(Decimal("120"), None).ytd_variation_valid is False
    assert ytd_variation(Decimal("120"), Decimal("0")).ytd_variation_valid is False
    assert ytd_variation(None, Decimal("100")).ytd_variation_valid is False


def test_decline_to_target():
    result = decline_to_target(Decimal("90"), Decimal("100"))
    assert result.decline_to_target == Decimal("-10.00")
    assert result.decline_to_target_valid is True

    result = decline_to_target(Decimal("110"), Decimal("100"))
    assert result.decline_to_target == Decimal("10.00")

    assert decline_to_target(Decimal("90"), None).decline_to_target_valid is False
    assert decline_to_target(Decimal("90"), Decimal("0")).decline_to_target_valid is False
