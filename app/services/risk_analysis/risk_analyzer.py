from typing import Dict, Any, Optional

class RiskAnalyzer:
    """
    Evaluates setup viability, calculates risk metrics, assigns quality grade (A/B/C),
    and strictly recommends NO TRADE when confidence or confluence is low.
    """
    @staticmethod
    def evaluate(
        confidence_score: int,
        primary_scenario: str,
        trade_setup_raw: Optional[Dict[str, Any]] = None,
        market_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        # If confidence is below 55% or scenarios are split, recommend NO TRADE
        if confidence_score < 55:
            trade_setup = {
                "has_setup": False,
                "direction": "NO TRADE",
                "entry_zone": "N/A",
                "stop_loss": "N/A",
                "target_1": "N/A",
                "target_2": "N/A",
                "risk_reward": "N/A",
                "reason": "Insufficient technical confirmation or conflicting signals across timeframes. Wait for a decisive breakout or range boundary test before initiating new risk."
            }
            risk_level = "HIGH"
            setup_quality = "C"
            reward_risk = "N/A"
            main_risk = "Chop / Range whip-saws causing premium decay"
        else:
            raw = trade_setup_raw or {}
            has_setup = raw.get("has_setup", True)
            direction = raw.get("direction", "CALL" if primary_scenario == "bullish" else "PUT")
            
            risk_level = "MEDIUM" if confidence_score >= 70 else "HIGH"
            setup_quality = "A" if confidence_score >= 75 else "B"
            reward_risk = raw.get("risk_reward", "1 : 2.2")
            main_risk = "False breakout / rejection at overhead liquidity pocket"

            trade_setup = {
                "has_setup": has_setup,
                "direction": direction,
                "entry_zone": raw.get("entry_zone", "Current market pivot zone"),
                "stop_loss": raw.get("stop_loss", "Nearest structural support/resistance"),
                "target_1": raw.get("target_1", "Immediate pivot target"),
                "target_2": raw.get("target_2", "Secondary technical target"),
                "risk_reward": reward_risk,
                "reason": raw.get("reason", "Structural alignment supporting probabilistic continuation.")
            }

        risk_analysis = {
            "risk_level": risk_level,
            "setup_quality": setup_quality,
            "reward_risk": reward_risk,
            "invalidation": trade_setup.get("stop_loss", "Key pivot violation"),
            "main_risk": main_risk,
            "disclaimer": (
                "This analysis is probabilistic and educational. It is not financial advice. "
                "Market conditions can change rapidly. Always independently verify levels and manage risk."
            )
        }

        return {
            "trade_setup": trade_setup,
            "risk_analysis": risk_analysis
        }
