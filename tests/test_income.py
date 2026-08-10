"""Test redditi di capitale RM: dividendi lordo/netto frontiera, interessi."""

from decimal import Decimal

from fiscoib.config import FiscoConfig
from fiscoib.engines.income import compute_rm
from helpers import stock, cfd, cash_tx


def test_dividendo_lordo_frontiera(rates):
    aapl = stock()
    txs = [
        cash_tx(aapl, "2024-11-16", "Dividends", 100),
        cash_tx(aapl, "2024-11-16", "Withholding Tax", -15),
    ]
    cfg = FiscoConfig(tax_year=2024, frontiera="lordo")
    rm = compute_rm(txs, rates, cfg)

    assert len(rm.dividends) == 1
    d = rm.dividends[0]
    # 100/1.08 = 92.59 base lorda
    assert d.base_imponibile_eur == Decimal("92.59")
    assert d.wht_eur == Decimal("13.89")
    assert d.imposta_eur == Decimal("24.07")
    assert d.credito_teorico_eur == Decimal("13.89")


def test_dividendo_netto_frontiera(rates):
    aapl = stock()
    txs = [
        cash_tx(aapl, "2024-11-16", "Dividends", 100),
        cash_tx(aapl, "2024-11-16", "Withholding Tax", -15),
    ]
    cfg = FiscoConfig(tax_year=2024, frontiera="netto")
    rm = compute_rm(txs, rates, cfg)
    d = rm.dividends[0]
    # (100-15)/1.08 = 78.70 base netta
    assert d.base_imponibile_eur == Decimal("78.70")


def test_interessi_passivi_ignorati(rates):
    txs = [
        cash_tx(None, "2024-11-16", "Broker Interest Paid", -50, currency="USD"),
        cash_tx(None, "2024-11-16", "Broker Interest Received", 20, currency="USD"),
    ]
    cfg = FiscoConfig(tax_year=2024)
    rm = compute_rm(txs, rates, cfg)
    assert rm.interessi_passivi_ignorati_eur > 0
    assert rm.tot_base_interessi > 0  # solo gli attivi


def test_cfd_dividend_adjustment_va_in_rt(rates):
    c = cfd()
    txs = [cash_tx(c, "2024-11-16", "Dividends", 30)]
    cfg = FiscoConfig(tax_year=2024, cfd_dividend_adjustment="RT")
    rm = compute_rm(txs, rates, cfg)
    # Nessun dividendo RM, ma un componente c-quater per RT.
    assert len(rm.dividends) == 0
    assert len(rm.cquater_components) == 1
