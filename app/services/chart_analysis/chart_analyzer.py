import json
import logging
from typing import Dict, Any
from sqlalchemy.orm import Session

from app.models import Analysis, AnalysisScreenshot, AnalysisResult, ScenarioPrediction
from app.services.ai.factory import get_ai_provider
from app.services.technical_analysis.technical_analyzer import TechnicalAnalyzer
from app.services.scenario_engine.scenario_engine import ScenarioEngine
from app.services.risk_analysis.risk_analyzer import RiskAnalyzer

logger = logging.getLogger(__name__)

class ChartAnalyzer:
    @staticmethod
    async def run_analysis(analysis_id: int, db: Session, provider_name: str = None) -> AnalysisResult:
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if not analysis:
            raise ValueError(f"Analysis {analysis_id} not found")

        try:
            analysis.status = "analyzing"
            analysis.error_message = None
            db.commit()

            # Retrieve screenshots
            screenshots = db.query(AnalysisScreenshot).filter(AnalysisScreenshot.analysis_id == analysis_id).all()
            image_paths = [s.file_path for s in screenshots]
            timeframes = [s.timeframe for s in screenshots]

            market_info = {
                "market": analysis.market,
                "instrument_type": analysis.instrument_type,
                "symbol": analysis.symbol,
                "expiry": analysis.expiry,
                "strike_price": analysis.strike_price,
                "option_type": analysis.option_type,
                "current_price": analysis.current_price,
                "previous_close": analysis.previous_close,
                "day_high": analysis.day_high,
                "day_low": analysis.day_low,
                "volume": analysis.volume,
                "open_interest": analysis.open_interest,
                "pcr": analysis.pcr,
                "india_vix": analysis.india_vix
            }

            # 1. AI Vision Analysis
            ai_provider = get_ai_provider(provider_name)
            ai_output = await ai_provider.analyze_chart(
                image_paths=image_paths,
                timeframes=timeframes,
                symbol=analysis.symbol,
                market_info=market_info,
                notes=analysis.notes
            )

            # 2. Scenario Normalization Engine
            scenario_data = ScenarioEngine.process_scenarios(ai_output.get("scenarios", []))
            primary_scenario = scenario_data["primary_scenario"]

            # 3. Technical Analysis refinement
            cmp = analysis.current_price or (
                ai_output.get("support_levels", [{}])[0].get("price", 0) + 100
                if ai_output.get("support_levels") else 25000.0
            )
            refined_levels = TechnicalAnalyzer.refine_levels(
                cmp=cmp,
                support_levels=ai_output.get("support_levels", []),
                resistance_levels=ai_output.get("resistance_levels", [])
            )

            # 4. Risk Analysis & Trade Setup verification
            confidence = ai_output.get("confidence_score", 70)
            risk_eval = RiskAnalyzer.evaluate(
                confidence_score=confidence,
                primary_scenario=primary_scenario,
                trade_setup_raw=ai_output.get("trade_setup"),
                market_info=market_info
            )

            # Remove existing results/scenarios if re-running
            db.query(AnalysisResult).filter(AnalysisResult.analysis_id == analysis_id).delete()
            db.query(ScenarioPrediction).filter(ScenarioPrediction.analysis_id == analysis_id).delete()

            # 5. Save Analysis Result
            result = AnalysisResult(
                analysis_id=analysis_id,
                trend=ai_output.get("trend", "Neutral"),
                primary_scenario=primary_scenario,
                confidence_score=confidence,
                market_structure=json.dumps(ai_output.get("market_structure", {})),
                support_levels=json.dumps(ai_output.get("support_levels", [])),
                resistance_levels=json.dumps(ai_output.get("resistance_levels", [])),
                candlestick_analysis=json.dumps(ai_output.get("candlestick_analysis", {})),
                volume_analysis=json.dumps(ai_output.get("volume_analysis", {})),
                oi_analysis=json.dumps(ai_output.get("oi_analysis", {})),
                technical_indicators=json.dumps(ai_output.get("technical_indicators", {})),
                bullish_scenario=json.dumps(scenario_data["bullish_scenario"]),
                bearish_scenario=json.dumps(scenario_data["bearish_scenario"]),
                sideways_scenario=json.dumps(scenario_data["sideways_scenario"]),
                risk_analysis=json.dumps(risk_eval["risk_analysis"]),
                trade_setup=json.dumps(risk_eval["trade_setup"]),
                time_movements=json.dumps(ai_output.get("time_movements", [])),
                multi_timeframe_synthesis=json.dumps(ai_output.get("multi_timeframe_synthesis", {})),
                detected_overlays=json.dumps(ai_output.get("detected_overlays", [])),
                entry_zone=risk_eval["trade_setup"].get("entry_zone"),
                stop_loss_zone=risk_eval["trade_setup"].get("stop_loss"),
                target_zone=f"{risk_eval['trade_setup'].get('target_1')} - {risk_eval['trade_setup'].get('target_2')}",
                confirmation_conditions=json.dumps(ai_output.get("confirmation_conditions", [])),
                invalidating_conditions=json.dumps(ai_output.get("invalidating_conditions", [])),
                time_horizon=ai_output.get("time_horizon", "15-60 Minutes"),
                ai_summary=ai_output.get("ai_summary", "")
            )
            db.add(result)

            # 6. Save Scenario Predictions
            for sc in scenario_data["scenarios"]:
                prediction = ScenarioPrediction(
                    analysis_id=analysis_id,
                    scenario_type=sc["type"],
                    probability=sc["probability"],
                    expected_direction=sc.get("potential_movement"),
                    expected_range=sc.get("expected_range"),
                    timeframe=sc.get("time_horizon"),
                    trigger_condition=sc.get("trigger"),
                    invalidation_condition=sc.get("invalidation")
                )
                db.add(prediction)

            analysis.status = "completed"
            db.commit()
            db.refresh(analysis)
            db.refresh(result)
            return result

        except Exception as e:
            logger.exception(f"Error during analysis {analysis_id}: {e}")
            analysis.status = "failed"
            analysis.error_message = (
                f"Unable to analyze this screenshot: {str(e)}. "
                "The chart information may not be clear enough or the provider encountered an issue. "
                "Please upload a higher-resolution screenshot containing price, timeframe, and indicator information."
            )
            db.commit()
            raise
