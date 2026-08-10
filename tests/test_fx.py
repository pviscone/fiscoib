"""Test cache cambi e conversioni."""

from datetime import date
from decimal import Decimal

from fiscoib.fx.rates import RatesProvider, RateNotAvailable


def _counting_fetchers():
    calls = {"daily": 0, "monthly": 0}

    def daily(cur, ref):
        calls["daily"] += 1
        return Decimal("1.10")

    def monthly(cur, y, m):
        calls["monthly"] += 1
        return Decimal("1.05")

    return calls, daily, monthly


def test_cache_evita_seconda_chiamata(tmp_path):
    db = str(tmp_path / "r.sqlite")
    calls, daily, monthly = _counting_fetchers()
    rp = RatesProvider(db_path=db, daily_fetcher=daily, monthly_fetcher=monthly)

    r1 = rp.daily_rate("USD", date(2024, 5, 10))
    r2 = rp.daily_rate("USD", date(2024, 5, 10))
    assert r1 == r2 == Decimal("1.10")
    # La seconda lettura viene dalla cache: una sola chiamata di rete.
    assert calls["daily"] == 1


def test_eur_e_uno(tmp_path):
    rp = RatesProvider(db_path=str(tmp_path / "r.sqlite"), offline=True)
    assert rp.daily_rate("EUR", date(2024, 1, 1)) == Decimal("1")
    assert rp.to_eur_daily(Decimal("100"), "EUR", date(2024, 1, 1)) == Decimal("100")


def test_conversione_usd(tmp_path):
    rp = RatesProvider(db_path=str(tmp_path / "r.sqlite"), offline=True)
    rp.preload("2024-06-20", "USD", "daily", Decimal("1.07"), "test")
    eur = rp.to_eur_daily(Decimal("22000"), "USD", date(2024, 6, 20))
    assert round(eur, 2) == Decimal("20560.75")


def test_override_ade_ha_priorita(tmp_path):
    rp = RatesProvider(
        db_path=str(tmp_path / "r.sqlite"),
        offline=True,
        ade_overrides={("USD", 2024, 12): Decimal("1.0479")},
    )
    assert rp.monthly_rate("USD", 2024, 12) == Decimal("1.0479")


def test_offline_senza_dato_solleva(tmp_path):
    rp = RatesProvider(db_path=str(tmp_path / "r.sqlite"), offline=True)
    try:
        rp.daily_rate("USD", date(2030, 1, 1))
        assert False, "doveva sollevare"
    except RateNotAvailable:
        pass
