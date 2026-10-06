from typing import Dict, Any, List

class ScenarioEngine:
    """
    Normalizes scenario probabilities (summing to 100%), enforces compliance
    language (no certainty), and formats multi-timeframe alignment.
    """
    @staticmethod
    def process_scenarios(raw_scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not raw_scenarios:
            raw_scenarios = [
                {"type": "bullish", "probability": 34, "trigger": "Above resistance", "invalidation": "Below support"},
                {"type": "bearish", "probability": 33, "trigger": "Below support", "invalidation": "Above resistance"},
                {"type": "sideways", "probability": 33, "trigger": "Inside range", "invalidation": "Range expansion"}
            ]

        # Ensure probabilities sum to 100
        total_prob = sum(s.get("probability", 0) for s in raw_scenarios)
        if total_prob <= 0:
            for s in raw_scenarios:
                s["probability"] = 100 // len(raw_scenarios)
            total_prob = sum(s["probability"] for s in raw_scenarios)

        normalized = []
        running_sum = 0
        for i, s in enumerate(raw_scenarios):
            raw_p = s.get("probability", 0)
            if i == len(raw_scenarios) - 1:
                p = 100 - running_sum
            else:
                p = round((raw_p / total_prob) * 100)
                running_sum += p

            # Scrub any guarantee language
            trigger = s.get("trigger", "").replace("will", "may").replace("guaranteed", "possible")
            invalidation = s.get("invalidation", "")

            normalized.append({
                "type": s.get("type", "sideways").lower(),
                "probability": max(1, p),
                "trigger": trigger,
                "confirmation": s.get("confirmation", "Volume and momentum follow-through"),
                "potential_movement": s.get("potential_movement", s.get("expected_range", "Contained within technical bands")),
                "expected_range": s.get("expected_range", s.get("potential_movement", "N/A")),
                "invalidation": invalidation,
                "time_horizon": s.get("time_horizon", "15-60 Minutes"),
                "risk_level": s.get("risk_level", "Medium")
            })

        # Determine primary scenario by highest probability
        primary_scenario = max(normalized, key=lambda x: x["probability"])["type"]

        # Map to bullish, bearish, sideways dicts for quick query
        bullish = next((s for s in normalized if s["type"] == "bullish"), {})
        bearish = next((s for s in normalized if s["type"] == "bearish"), {})
        sideways = next((s for s in normalized if s["type"] == "sideways"), {})

        return {
            "primary_scenario": primary_scenario,
            "scenarios": normalized,
            "bullish_scenario": bullish,
            "bearish_scenario": bearish,
            "sideways_scenario": sideways
        }
