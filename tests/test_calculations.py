from decimal import Decimal
from portfoliomaster.core.calculations import (
    daily_variation,
    variation_since_analysis,
    ytd_variation,
    decline_to_target,
)

def test_daily_variation():
    # latest / prev_close - 1 * 100
    # 110 / 100 - 1 = 0.1 * 100 = 10%
    result = daily_variation(Decimal("110"), Decimal("100"))
    assert result.daily_variation == Decimal("10.00")
    assert result.daily_variation_valid is True

    # 90 / 100 - 1 = -0.1 * 100 = -10%
    result = daily_variation(Decimal("90"), Decimal("100"))
    assert result.daily_variation == Decimal("-10.00")

    # Missing/Zero prev_close
    assert daily_variation(Decimal("110"), None).daily_variation_valid is False
    assert daily_variation(Decimal("110"), Decimal("0")).daily_variation_valid is False

def test_variation_since_analysis():
    # (current / analysis_price - 1) * 100
    # 120 / 100 - 1 = 0.2 * 100 = 20%
    result = variation_since_analysis(Decimal("120"), Decimal("100"))
    assert result.variation_since_analysis == Decimal("20.00")
    assert result.variation_since_analysis_valid is True

    # Missing/Zero analysis_price
    assert variation_since_analysis(Decimal("120"), None).variation_since_analysis_valid is False
    assert variation_since_analysis(Decimal("120"), Decimal("0")).variation_since_analysis_valid is False

def test_ytd_variation():
    # (current / ytd_price - 1) * 100
    # 120 / 100 - 1 = 0.2 * 100 = 20%
    result = ytd_variation(Decimal("120"), Decimal("100"))
    assert result.ytd_variation == Decimal("20.00")
    assert result.ytd_variation_valid is True

    # 85 / 100 - 1 = -0.15 * 100 = -15%
    result = ytd_variation(Decimal("85"), Decimal("100"))
    assert result.ytd_variation == Decimal("-15.00")
    assert result.ytd_variation_valid is True

    # Missing/Zero ytd_price
    assert ytd_variation(Decimal("120"), None).ytd_variation_valid is False
    assert ytd_variation(Decimal("120"), Decimal("0")).ytd_variation_valid is False
    assert ytd_variation(None, Decimal("100")).ytd_variation_valid is False

def test_decline_to_target():
    # ((target_price - latest_price) / latest_price) * 100
    # Target 90, Latest 100. (90-100)/100 = -0.1 * 100 = -10%
    result = decline_to_target(Decimal("90"), Decimal("100"))
    assert result.decline_to_target == Decimal("-10.00")
    assert result.decline_to_target_valid is True

    # Target 110, Latest 100. (110-100)/100 = 0.1 * 100 = 10%
    result = decline_to_target(Decimal("110"), Decimal("100"))
    assert result.decline_to_target == Decimal("10.00")

    # Missing/Zero latest
    assert decline_to_target(Decimal("90"), None).decline_to_target_valid is False
    assert decline_to_target(Decimal("90"), Decimal("0")).decline_to_target_valid is False
