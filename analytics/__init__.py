import pandas as pd
from .performance import calculate_portfolio_summary
from .risk import calculate_risk_metrics
from .diversification import calculate_diversification
from .literacy import explain_metrics

def analyze_portfolio(
    holdings_df: pd.DataFrame, 
    current_prices: dict, 
    price_history_df: pd.DataFrame = None, 
    benchmark_returns: pd.Series = None
) -> dict:
    """
    Unified analytics execution pipeline.
    Combines Performance, Risk, Diversification, and Literacy insights.
    """
    summary = calculate_portfolio_summary(holdings_df, current_prices)
    diversification = calculate_diversification(holdings_df, current_prices)
    risk = calculate_risk_metrics(price_history_df, benchmark_returns)
    literacy = explain_metrics(risk, diversification.get("hhi", 0.0))
    
    return {
        "summary": summary,
        "diversification": diversification,
        "risk": risk,
        "literacy": literacy
    }

__all__ = [
    "calculate_portfolio_summary",
    "calculate_risk_metrics",
    "calculate_diversification",
    "explain_metrics",
    "analyze_portfolio"
]