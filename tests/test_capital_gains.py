"""Test plusvalenze RT con conversione cambi (esempio Apple della ricerca)."""

from decimal import Decimal

from datetime import date

from fiscoib.config import FiscoConfig
from fiscoib.engines.capital_gains import compute_rt
from fiscoib.engines.lots import build_closures
from helpers import etf, stock, trade


def test_plusvalenza_apple_con_cambio(rates):
    aapl = stock()
    trades = [
        trade(aapl, "2024-01-15", "BUY", 100, 180, commission=-2),
        trade(aapl, "2024-06-20", "SELL", 100, 220, commission=-2),
    ]
    closures, _ = build_closures(trades, [])
    cfg = FiscoConfig(tax_year=2024)
    rt = compute_rt(closures, rates, cfg)

    # Plus attesa ~ €4043,28 (18000/1.09 costo, 22000/1.07 corrispettivo, comm dedotte).
    assert len(rt.rows) == 1
    assert rt.rows[0].plus_minus_eur == Decimal("4043.28")
    assert rt.rt23_differenza == Decimal("4043.28")
    # Imposta sostitutiva 26%.
    assert rt.rt27_imposta == Decimal("1051.25")


def test_minusvalenza_riportata(rates):
    """Se il saldo è negativo, la minusvalenza va a riporto e imposta = 0."""
    aapl = stock()
    trades = [
        trade(aapl, "2024-01-15", "BUY", 100, 220),
        trade(aapl, "2024-06-20", "SELL", 100, 180),
    ]
    closures, _ = build_closures(trades, [])
    cfg = FiscoConfig(tax_year=2024)
    rt = compute_rt(closures, rates, cfg)

    assert rt.rt27_imposta == Decimal("0")
    assert rt.minus_anno > 0
    assert 2024 in rt.minus_da_riportare


def test_compensazione_minus_pregresse(rates):
    """Le minusvalenze pregresse riducono l'imponibile (le più vecchie prima)."""
    aapl = stock()
    trades = [
        trade(aapl, "2024-01-15", "BUY", 100, 180),
        trade(aapl, "2024-06-20", "SELL", 100, 220),
    ]
    closures, _ = build_closures(trades, [])
    cfg = FiscoConfig(tax_year=2024)
    rt = compute_rt(closures, rates, cfg, prior_losses={2021: Decimal("1000")})

    assert rt.minus_pregresse_usate == Decimal("1000")
    # Imponibile ridotto di 1000 rispetto alla differenza lorda.
    assert rt.rt26_imponibile == rt.rt23_differenza - Decimal("1000")


def test_minus_scaduta_non_usata(rates):
    """Minusvalenza oltre i 4 anni non è più utilizzabile."""
    aapl = stock()
    trades = [
        trade(aapl, "2024-01-15", "BUY", 100, 180),
        trade(aapl, "2024-06-20", "SELL", 100, 220),
    ]
    closures, _ = build_closures(trades, [])
    cfg = FiscoConfig(tax_year=2024)
    # 2019 è oltre i 4 anni precedenti al 2024 -> scaduta.
    rt = compute_rt(closures, rates, cfg, prior_losses={2019: Decimal("1000")})
    assert rt.minus_pregresse_usate == Decimal("0")


def test_oicr_gain_non_compensa_minus_azionaria(rates):
    """Gain su ETF = reddito di capitale (art. 44 c.1 lett. g TUIR): NON entra
    in RT e NON compensa la minusvalenza azionaria, che resta da riportare."""
    iwda = etf()  # isin IE00B4L5Y983 -> country IE
    aapl = stock()
    trades = [
        # ETF in EUR: +2000 di guadagno (reddito di capitale).
        trade(iwda, "2024-01-15", "BUY", 100, 80, currency="EUR"),
        trade(iwda, "2024-06-20", "SELL", 100, 100, currency="EUR"),
        # Azione USA in perdita (stessa operazione di test_minusvalenza_riportata).
        trade(aapl, "2024-01-15", "BUY", 100, 220),
        trade(aapl, "2024-06-20", "SELL", 100, 180),
    ]
    closures, _ = build_closures(trades, [])
    cfg = FiscoConfig(tax_year=2024)
    rt = compute_rt(closures, rates, cfg)

    # Il gain OICR NON è nel saldo RT ma in oicr_gains.
    assert len(rt.oicr_gains) == 1
    g = rt.oicr_gains[0]
    assert g["symbol"] == "IWDA"
    assert g["gain_eur"] == Decimal("2000.00")
    assert g["qty"] == Decimal("100")
    assert g["data_chiusura"] == date(2024, 6, 20)
    assert g["aliquota"] == "0.26"
    assert g["lettera"] == "H"
    assert g["country"] == "IE"

    # Il saldo RT contiene SOLO la minus azionaria: nessuna compensazione.
    assert rt.saldo_netto < 0
    assert rt.rt23_differenza == Decimal("0")
    assert rt.minus_anno > 0
    assert rt.rt27_imposta == Decimal("0")
    # Nessuna riga RT per l'ETF in gain.
    assert not [r for r in rt.rows if r.symbol == "IWDA"]


def test_oicr_minus_resta_in_rt(rates):
    """Perdita su ETF = reddito diverso: minus normale compensabile in RT."""
    iwda = etf()
    trades = [
        trade(iwda, "2024-01-15", "BUY", 100, 100, currency="EUR"),
        trade(iwda, "2024-06-20", "SELL", 100, 80, currency="EUR"),
    ]
    closures, _ = build_closures(trades, [])
    cfg = FiscoConfig(tax_year=2024)
    rt = compute_rt(closures, rates, cfg)

    assert rt.oicr_gains == []
    assert rt.minus_anno == Decimal("2000.00")
    # La minus OICR compare fra le righe RT ed è da riportare.
    assert any(r.symbol == "IWDA" for r in rt.rows)
    assert rt.minus_da_riportare.get(2024) == Decimal("2000.00")
