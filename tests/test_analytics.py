import pytest
import pandas as pd
import numpy as np

from analytics.performance import calculate_portfolio_summary
from analytics.diversification import calculate_diversification
from analytics.risk import calculate_risk_metrics
from analytics.literacy import explain_metrics
from analytics import analyze_portfolio


# 1. Performance Engine Tests
def test_performance_empty_holdings():
    empty_df = pd.DataFrame(columns=['symbol', 'quantity', 'avg_buy_price', 'sector'])
    result = calculate_portfolio_summary(empty_df, {})
    assert result['invested'] == 0.0
    assert result['current_value'] == 0.0
    assert result['pnl'] == 0.0
    assert result['return_pct'] == 0.0


def test_performance_calculation_accuracy():
    df = pd.DataFrame({
        'symbol': ['TCS', 'INFY'],
        'quantity': [10, 20],
        'avg_buy_price': [3000.0, 1500.0],
        'sector': ['IT', 'IT']
    })
    # Invested = (10 * 3000) + (20 * 1500) = 30000 + 30000 = 60000
    # Current Value = (10 * 3500) + (20 * 1600) = 35000 + 32000 = 67000
    # PnL = 67000 - 60000 = 7000
    # Return % = (7000 / 60000) * 100 = 11.67%
    prices = {'TCS': 3500.0, 'INFY': 1600.0}
    result = calculate_portfolio_summary(df, prices)
    
    assert result['invested'] == 60000.0
    assert result['current_value'] == 67000.0
    assert result['pnl'] == 7000.0
    assert result['return_pct'] == 11.67


# 2. Diversification Engine Tests
def test_diversification_hhi_and_sectors():
    df = pd.DataFrame({
        'symbol': ['TCS', 'HDFC'],
        'quantity': [10, 10],
        'avg_buy_price': [100.0, 100.0],
        'sector': ['IT', 'Banking']
    })
    prices = {'TCS': 100.0, 'HDFC': 100.0}
    result = calculate_diversification(df, prices)
    
    # Each stock is 50% of the portfolio
    assert result['stock_weights']['TCS'] == 50.0
    assert result['stock_weights']['HDFC'] == 50.0
    assert result['sector_weights']['IT'] == 50.0
    assert result['sector_weights']['Banking'] == 50.0
    # HHI = 50^2 + 50^2 = 2500 + 2500 = 5000
    assert result['hhi'] == 5000.0


# 3. Risk Engine Tests
def test_risk_metrics_structure():
    dates = pd.date_range("2026-01-01", periods=10, freq="B")
    price_df = pd.DataFrame({
        'TCS': [3000, 3050, 3020, 3080, 3100, 3090, 3120, 3150, 3140, 3180],
        'INFY': [1500, 1520, 1510, 1530, 1540, 1535, 1550, 1560, 1555, 1570]
    }, index=dates)
    benchmark_returns = pd.Series(
        [0.005, -0.002, 0.003, 0.001, -0.004, 0.002, 0.006, -0.001, 0.003],
        index=dates[1:]
    )
    
    risk = calculate_risk_metrics(price_df, benchmark_returns)
    
    assert 'volatility_pct' in risk
    assert 'beta' in risk
    assert 'sharpe_ratio' in risk
    assert 'max_drawdown_pct' in risk
    assert 'correlation_matrix' in risk
    assert risk['correlation_matrix']['TCS']['TCS'] == 1.0


# 4. Literacy Engine Tests
def test_literacy_interpretation():
    mock_risk = {'beta': 1.4, 'sharpe_ratio': 1.5}
    hhi = 3000.0
    literacy = explain_metrics(mock_risk, hhi)
    
    assert "High Volatility" in literacy['beta']['title']
    assert "Highly Concentrated" in literacy['diversification']['title']
    assert "Good Risk-Adjusted Return" in literacy['sharpe_ratio']['title']


# 5. Full Pipeline Integration Test
def test_unified_analyze_portfolio():
    df = pd.DataFrame({
        'symbol': ['TCS'],
        'quantity': [5],
        'avg_buy_price': [3200.0],
        'sector': ['IT']
    })
    prices = {'TCS': 3400.0}
    output = analyze_portfolio(df, prices)
    
    assert "summary" in output
    assert "diversification" in output
    assert "risk" in output
    assert "literacy" in output
    assert output["summary"]["invested"] == 16000.0