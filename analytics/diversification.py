import pandas as pd
import numpy as np

def calculate_diversification(holdings_df: pd.DataFrame, current_prices: dict) -> dict:
    """
    Computes individual stock weights, sector distribution percentages,
    and the Herfindahl-Hirschman Index (HHI) for concentration risk.
    
    holdings_df columns: ['symbol', 'quantity', 'avg_buy_price', 'sector']
    current_prices: dictionary mapping symbols to current prices (e.g., {'TCS': 3500.0})
    """
    if holdings_df is None or holdings_df.empty:
        return {
            "stock_weights": {},
            "sector_weights": {},
            "hhi": 0.0
        }

    df = holdings_df.copy()
    
    # Map current prices; fallback to average purchase price if live price is unavailable
    df['current_price'] = df['symbol'].map(current_prices).fillna(df['avg_buy_price'])
    df['current_value'] = df['quantity'] * df['current_price']
    
    total_value = float(df['current_value'].sum())
    if total_value == 0:
        return {
            "stock_weights": {},
            "sector_weights": {},
            "hhi": 0.0
        }

    # 1. Individual Stock Weights (percentage of total portfolio)
    df['stock_weight'] = (df['current_value'] / total_value) * 100
    stock_weights = (
        df.groupby('symbol')['stock_weight']
        .sum()
        .round(2)
        .to_dict()
    )

    # 2. Sector Allocation Weights
    sector_weights = (
        df.groupby('sector')['stock_weight']
        .sum()
        .round(2)
        .to_dict()
    )

    # 3. Herfindahl-Hirschman Index (HHI)
    # Calculated as the sum of squared percentage weights (ranges from 0 to 10,000)
    hhi = float((df['stock_weight'] ** 2).sum())

    return {
        "stock_weights": stock_weights,
        "sector_weights": sector_weights,
        "hhi": round(hhi, 2)
    }