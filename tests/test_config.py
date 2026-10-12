import pytest

from pullback_trader.config import AppConfig, load_config, validate


def test_yaml_override(tmp_path, monkeypatch):
    y = tmp_path / "c.yaml"
    y.write_text("mode: day\nrisk:\n  risk_per_trade_pct: 0.5\nuniverse:\n  min_market_cap: 30000000000\n", encoding="utf-8")
    monkeypatch.setenv("KIS_APP_KEY", "k")
    cfg = load_config(str(y))
    assert cfg.mode == "day" and cfg.risk.risk_per_trade_pct == 0.5 and cfg.universe.min_market_cap == 3e10
    assert cfg.broker.kis.app_key == "k"


def test_unknown_key_rejected(tmp_path):
    y = tmp_path / "c.yaml"
    y.write_text("risk:\n  nope: 1\n", encoding="utf-8")
    with pytest.raises(KeyError):
        load_config(str(y))


def test_validate_weights():
    c = AppConfig()
    c.ladder.weights = [1, 2, 3]
    with pytest.raises(ValueError):
        validate(c)
