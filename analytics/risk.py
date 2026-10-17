import numpy as np
import pandas as pd

def calculate_risk_metrics(
    price_history_df: pd.DataFrame, 
    benchmark_returns: pd.Series = None, 
    risk_free_rate: float = 0.065
) -> dict:
    """
    Computes annualized volatility, beta, maximum drawdown, 
    Sharpe ratio, and asset correlation matrix.
    
    price_history_df: DataFrame where rows are trading dates and columns are stock symbols (closing prices).
    benchmark_returns: Daily returns Series for the benchmark index (e.g., Nifty 50).
    risk_free_rate: Annualized risk-free rate (defaults to 6.5% for Indian 10Y G-Sec).
    """
    if price_history_df is None or price_history_df.empty:
        return {
            "volatility_pct": 0.0,
            "beta": 1.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "correlation_matrix": {}
        }

    # 1. Compute daily percentage returns for all assets
    daily_returns = price_history_df.pct_change().dropna()
    if daily_returns.empty:
        return {
            "volatility_pct": 0.0,
            "beta": 1.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "correlation_matrix": {}
        }

    # Equal-weighted aggregate portfolio daily returns
    portfolio_daily_return = daily_returns.mean(axis=1)

    # 2. Annualized Volatility (using 252 Indian market trading days)
    daily_std = portfolio_daily_return.std()
    annualized_volatility = float(daily_std * np.sqrt(252))

    # 3. Portfolio Beta against benchmark
    if benchmark_returns is not None and not benchmark_returns.empty:
        aligned_data = pd.concat([portfolio_daily_return, benchmark_returns], axis=1).dropna()
        if len(aligned_data) > 1:
            cov_matrix = np.cov(aligned_data.iloc[:, 0], aligned_data.iloc[:, 1])
            market_variance = cov_matrix[1, 1]
            portfolio_beta = float(cov_matrix[0, 1] / market_variance) if market_variance != 0 else 1.0
        else:
            portfolio_beta = 1.0
    else:
        portfolio_beta = 1.0

    # 4. Maximum Drawdown (MDD)
    cumulative_growth = (1 + portfolio_daily_return).cumprod()
    peak = cumulative_growth.cummax()
    drawdown = (cumulative_growth - peak) / peak
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0

    # 5. Sharpe Ratio
    mean_daily_return = portfolio_daily_return.mean()
    annualized_return = (1 + mean_daily_return) ** 252 - 1
    sharpe_ratio = (
        float((annualized_return - risk_free_rate) / annualized_volatility)
        if annualized_volatility > 0 else 0.0
    )

    # 6. Correlation Matrix
    corr_matrix = daily_returns.corr().round(2).to_dict()

    return {
        "volatility_pct": round(annualized_volatility * 100, 2),
        "beta": round(portfolio_beta, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "correlation_matrix": corr_matrix
    }