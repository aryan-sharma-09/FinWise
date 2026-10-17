import pandas as pd
import numpy as np

def calculate_portfolio_summary(holdings_df: pd.DataFrame, current_prices: dict) -> dict:
    """
    Computes total invested amount, current valuation, absolute P&L, 
    and overall return percentage.
    
    holdings_df columns expected: ['symbol', 'quantity', 'avg_buy_price', 'sector']
    current_prices: dictionary mapping symbols to current prices (e.g., {'TCS': 3500.0})
    """
    if holdings_df is None or holdings_df.empty:
        return {
            "invested": 0.0,
            "current_value": 0.0,
            "pnl": 0.0,
            "return_pct": 0.0
        }

    df = holdings_df.copy()
    
    # Map current prices; fallback to average purchase price if live price is unavailable
    df['current_price'] = df['symbol'].map(current_prices).fillna(df['avg_buy_price'])
    
    # Value computations
    df['invested_value'] = df['quantity'] * df['avg_buy_price']
    df['current_value'] = df['quantity'] * df['current_price']
    
    total_invested = float(df['invested_value'].sum())
    total_current = float(df['current_value'].sum())
    pnl = total_current - total_invested
    
    # Prevent division by zero
    return_pct = (pnl / total_invested * 100) if total_invested > 0 else 0.0

    return {
        "invested": round(total_invested, 2),
        "current_value": round(total_current, 2),
        "pnl": round(pnl, 2),
        "return_pct": round(return_pct, 2)
    }