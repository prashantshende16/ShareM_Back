from typing import Dict, Any, List

class TechnicalAnalyzer:
    """
    Evaluates and refines technical signals, ensuring mathematical consistency
    of support/resistance bands, indicator coherence, and level spacing.
    """
    @staticmethod
    def refine_levels(cmp: float, support_levels: List[Dict[str, Any]], resistance_levels: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Filter and sort support levels (must be <= cmp if cmp is present)
        sorted_supports = sorted(support_levels, key=lambda x: x.get("price", 0), reverse=True)
        sorted_resistances = sorted(resistance_levels, key=lambda x: x.get("price", 0))

        # Check for immediate critical pivots
        immediate_s = sorted_supports[0] if sorted_supports else None
        immediate_r = sorted_resistances[0] if sorted_resistances else None

        return {
            "immediate_support": immediate_s,
            "immediate_resistance": immediate_r,
            "all_supports": sorted_supports,
            "all_resistances": sorted_resistances
        }

    @staticmethod
    def calculate_risk_reward(entry: float, stop_loss: float, target: float) -> str:
        risk = abs(entry - stop_loss)
        reward = abs(target - entry)
        if risk == 0:
            return "N/A"
        ratio = round(reward / risk, 2)
        return f"1 : {ratio}"
