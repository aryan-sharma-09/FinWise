def explain_metrics(risk_metrics: dict, hhi: float) -> dict:
    """
    Transforms mathematical portfolio metrics into beginner-friendly explanations
    for the Financial Literacy dashboard.
    """
    explanations = {}

    # 1. Beta Interpretation
    beta = risk_metrics.get("beta", 1.0)
    if beta < 0.8:
        explanations["beta"] = {
            "title": "Low Sensitivity (Defensive)",
            "message": f"Your portfolio has a Beta of {beta:.2f}. It tends to swing less than the benchmark (Nifty 50), offering greater stability during market sell-offs."
        }
    elif beta <= 1.2:
        explanations["beta"] = {
            "title": "Market-Aligned",
            "message": f"Your portfolio has a Beta of {beta:.2f}. Its movements roughly mirror broader market fluctuations."
        }
    else:
        explanations["beta"] = {
            "title": "High Volatility (Aggressive)",
            "message": f"Your portfolio has a Beta of {beta:.2f}. It is significantly more sensitive to market swings, offering potential upside in rallies but steeper falls during downturns."
        }

    # 2. Diversification / HHI Interpretation
    if hhi < 1500:
        explanations["diversification"] = {
            "title": "Well-Diversified",
            "message": f"With an HHI score of {hhi:.1f}, your capital is well-distributed across assets, lowering the risk of single-stock collapses."
        }
    elif hhi <= 2500:
        explanations["diversification"] = {
            "title": "Moderately Concentrated",
            "message": f"With an HHI score of {hhi:.1f}, a small cluster of stocks drives most of your portfolio value. Consider broadening your exposure."
        }
    else:
        explanations["diversification"] = {
            "title": "Highly Concentrated",
            "message": f"With an HHI score of {hhi:.1f}, your portfolio carries severe concentration risk. Sharp declines in your top 1–2 holdings will disproportionately affect your wealth."
        }

    # 3. Sharpe Ratio Interpretation
    sharpe = risk_metrics.get("sharpe_ratio", 0.0)
    if sharpe < 1.0:
        explanations["sharpe_ratio"] = {
            "title": "Sub-Optimal Risk Compensation",
            "message": f"Sharpe Ratio is {sharpe:.2f}. The returns generated are relatively low given the volatility you are enduring."
        }
    elif sharpe <= 2.0:
        explanations["sharpe_ratio"] = {
            "title": "Good Risk-Adjusted Return",
            "message": f"Sharpe Ratio is {sharpe:.2f}. You are being adequately compensated for the level of risk in your holdings."
        }
    else:
        explanations["sharpe_ratio"] = {
            "title": "Excellent Risk-Adjusted Return",
            "message": f"Sharpe Ratio is {sharpe:.2f}. The portfolio delivers strong excess returns per unit of risk."
        }

    return explanations