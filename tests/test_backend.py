import os
import json
import io
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.main import app
from app.database import Base, get_db
from app.services.scenario_engine.scenario_engine import ScenarioEngine
from app.services.risk_analysis.risk_analyzer import RiskAnalyzer
from app.services.technical_analysis.technical_analyzer import TechnicalAnalyzer

TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_scenario_engine_probability_sum_100():
    raw_scenarios = [
        {"type": "bullish", "probability": 70, "trigger": "Above 25000"},
        {"type": "bearish", "probability": 20, "trigger": "Below 24800"},
        {"type": "sideways", "probability": 10, "trigger": "Inside range"}
    ]
    processed = ScenarioEngine.process_scenarios(raw_scenarios)
    total_prob = sum(s["probability"] for s in processed["scenarios"])
    assert total_prob == 100
    assert processed["primary_scenario"] == "bullish"
    assert processed["bullish_scenario"]["probability"] == 70

def test_scenario_engine_handles_zero_or_missing_probabilities():
    raw_scenarios = [
        {"type": "bullish", "probability": 0},
        {"type": "bearish", "probability": 0},
        {"type": "sideways", "probability": 0}
    ]
    processed = ScenarioEngine.process_scenarios(raw_scenarios)
    total_prob = sum(s["probability"] for s in processed["scenarios"])
    assert total_prob == 100

def test_risk_analyzer_low_confidence_recommends_no_trade():
    eval_result = RiskAnalyzer.evaluate(
        confidence_score=40,
        primary_scenario="bullish",
        trade_setup_raw={"has_setup": True, "direction": "CALL"}
    )
    assert eval_result["trade_setup"]["direction"] == "NO TRADE"
    assert eval_result["trade_setup"]["has_setup"] is False
    assert "Insufficient" in eval_result["trade_setup"]["reason"]
    assert eval_result["risk_analysis"]["risk_level"] == "HIGH"
    assert "educational" in eval_result["risk_analysis"]["disclaimer"].lower()

def test_risk_analyzer_high_confidence_trade_setup():
    eval_result = RiskAnalyzer.evaluate(
        confidence_score=78,
        primary_scenario="bullish",
        trade_setup_raw={
            "has_setup": True,
            "direction": "CALL",
            "entry_zone": "25000 - 25050",
            "stop_loss": "24920",
            "target_1": "25200",
            "target_2": "25300",
            "risk_reward": "1 : 2.5"
        }
    )
    assert eval_result["trade_setup"]["direction"] == "CALL"
    assert eval_result["trade_setup"]["has_setup"] is True
    assert eval_result["risk_analysis"]["setup_quality"] == "A"

def test_technical_analyzer_refine_levels():
    cmp = 25100.0
    supports = [{"label": "S1", "price": 25000.0}, {"label": "S2", "price": 24800.0}]
    resistances = [{"label": "R1", "price": 25200.0}, {"label": "R2", "price": 25400.0}]
    refined = TechnicalAnalyzer.refine_levels(cmp, supports, resistances)
    assert refined["immediate_support"]["price"] == 25000.0
    assert refined["immediate_resistance"]["price"] == 25200.0
    assert TechnicalAnalyzer.calculate_risk_reward(25100, 25000, 25350) == "1 : 2.5"

def test_create_and_run_analysis_workflow():
    # 1. Create Analysis
    create_payload = {
        "market": "NIFTY",
        "instrument_type": "Index",
        "symbol": "NIFTY 50",
        "current_price": 25050.0,
        "notes": "Testing support bounce near round level 25,000"
    }
    res = client.post("/api/v1/analyses", json=create_payload)
    assert res.status_code == 200
    analysis = res.json()
    analysis_id = analysis["id"]
    assert analysis["status"] == "pending"

    # 2. Upload Screenshot
    fake_png = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    upload_res = client.post(
        f"/api/v1/analyses/{analysis_id}/screenshots",
        files={"file": ("chart_15m.png", fake_png, "image/png")},
        data={"timeframe": "15 Minute"}
    )
    assert upload_res.status_code == 200
    assert upload_res.json()["timeframe"] == "15 Minute"

    # 3. Run Analysis
    run_res = client.post(f"/api/v1/analyses/{analysis_id}/run")
    assert run_res.status_code == 200
    analyzed = run_res.json()
    assert analyzed["status"] == "completed"
    assert analyzed["result"] is not None
    assert analyzed["result"]["confidence_score"] >= 50
    assert len(analyzed["scenarios"]) == 3

    # 4. Fetch Result Directly
    result_res = client.get(f"/api/v1/analyses/{analysis_id}/result")
    assert result_res.status_code == 200
    result_data = result_res.json()
    assert "primary_scenario" in result_data
    assert len(result_data["time_movements"]) > 0

    # 5. Fetch Dashboard Stats
    stats_res = client.get("/api/v1/analyses/stats")
    assert stats_res.status_code == 200
    stats = stats_res.json()
    assert stats["total_analyses"] >= 1

def test_watchlist_and_settings():
    # Watchlist auto-seeding
    w_res = client.get("/api/v1/watchlist")
    assert w_res.status_code == 200
    watchlist = w_res.json()
    assert len(watchlist) >= 6
    symbols = [item["symbol"] for item in watchlist]
    assert "NIFTY 50" in symbols

    # Settings
    s_res = client.get("/api/v1/settings")
    assert s_res.status_code == 200
    settings_data = s_res.json()
    assert settings_data["current_provider"] in ["mock", "openai", "gemini", "claude"]
    assert settings_data["market_data_connected"] is False
    assert "not connected" in settings_data["market_data_status"].lower()
