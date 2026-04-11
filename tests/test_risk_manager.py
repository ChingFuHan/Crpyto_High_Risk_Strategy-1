from core.risk_manager import RiskManager


def test_on_position_closed_restores_margin_and_profit():
    manager = RiskManager(500.0)

    manager.on_position_opened("BTC/USDT:USDT", "LONG", 100.0, 5)
    manager.on_position_closed("BTC/USDT:USDT", 20.0)

    status = manager.get_status()
    assert status["balance"] == 520.0
    assert status["open_positions"] == 0
    assert status["daily_loss"] == 0.0


def test_on_position_closed_tracks_losses_and_triggers_cooldown():
    manager = RiskManager(500.0)

    for idx in range(3):
        symbol = f"ALT{idx}/USDT:USDT"
        manager.on_position_opened(symbol, "LONG", 50.0, 1)
        manager.on_position_closed(symbol, -10.0)

    status = manager.get_status()
    assert status["balance"] == 470.0
    assert status["daily_loss"] == 30.0
    assert status["cooldown_active"] is True

    allowed, reason = manager.can_open_position("NEW/USDT:USDT", "LONG", 10.0, 1)
    assert allowed is False
    assert "Cooldown active" in reason
