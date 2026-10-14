"""Test redditi di capitale RM: dividendi lordo/netto frontiera, interessi."""

from decimal import Decimal

from fiscoib.config import FiscoConfig
from fiscoib.engines.income import compute_rm
from fiscoib.parsing.models import Instrument
from fiscoib.warnings import WarningCollector
from helpers import stock, cfd, cash_tx


def bond(symbol="BTP12345678", isin="IT0000000000", currency="USD"):
    return Instrument(
        conid=symbol,
        symbol=symbol,
        description=symbol,
        asset_category="BOND",
        isin=isin,
        currency=currency,
    )


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


def test_cedola_titolo_stato_125_codice_a(rates):
    b = bond(isin="IT0000000000")
    txs = [cash_tx(b, "2024-11-16", "Bond Interest Received", 100)]
    cfg = FiscoConfig(tax_year=2024)
    rm = compute_rm(txs, rates, cfg, gov_bonds={"IT0000000000"})
    r = rm.interests[0]
    assert r.codice_reddito == "A"
    assert r.aliquota == Decimal("0.125")
    # 100/1.08 = 92.59 → 12,5% = 11.57
    assert r.imposta_eur == Decimal("11.57")


def test_match_gov_per_simbolo_e_non_solo_isin(rates):
    b = bond(symbol="BTP-SYM", isin="IT0000000001")
    txs = [cash_tx(b, "2024-11-16", "Bond Interest Received", 100)]
    cfg = FiscoConfig(tax_year=2024)
    rm = compute_rm(txs, rates, cfg, gov_bonds={"BTP-SYM"})
    assert rm.interests[0].codice_reddito == "A"


def test_cedola_corporate_26_codice_i_e_critical_senza_govbonds(rates):
    b = bond(isin="IT9999999999")
    txs = [
        cash_tx(b, "2024-11-16", "Bond Interest Received", 100),
        cash_tx(b, "2024-06-20", "Bond Interest Received", 50),
    ]
    cfg = FiscoConfig(tax_year=2024)
    warnings = WarningCollector()
    rm = compute_rm(txs, rates, cfg, warnings=warnings, gov_bonds=None)
    # tutte corporate al 26%
    assert all(r.codice_reddito == "I" for r in rm.interests)
    # warning CRITICAL una sola volta per emittente
    critic = [w for w in warnings if w.code == "GOVBONDS_DA_CLASSIFICARE"]
    assert len(critic) == 1
    assert critic[0].level == "CRITICAL"


def test_pil_in_rm_codice_c(rates):
    aapl = stock()
    txs = [cash_tx(aapl, "2024-11-16", "Payment In Lieu Of Dividends", 30)]
    cfg = FiscoConfig(tax_year=2024, pil_treatment="RM")
    rm = compute_rm(txs, rates, cfg)
    assert len(rm.dividends) == 1
    assert rm.dividends[0].codice_reddito == "C"


def test_country_ade_us_069(rates):
    aapl = stock(isin="US0378331005")
    txs = [cash_tx(aapl, "2024-11-16", "Dividends", 10)]
    cfg = FiscoConfig(tax_year=2024)
    rm = compute_rm(txs, rates, cfg)
    assert rm.dividends[0].country == "US"
    assert rm.dividends[0].country_ade == "069"


def test_country_ade_sconosciuto_warning_e_fallback(rates):
    b = bond(isin="XXCHIBA12345")  # prefisso ISIN non mappato in Tabella 10
    txs = [cash_tx(b, "2024-11-16", "Bond Interest Received", 100)]
    cfg = FiscoConfig(tax_year=2024)
    warnings = WarningCollector()
    rm = compute_rm(txs, rates, cfg, warnings=warnings, gov_bonds={"XXCHIBA12345"})
    assert rm.interests[0].country == "XX"
    assert rm.interests[0].country_ade == "XX"  # fallback visibile
    hits = [w for w in warnings if w.code == "PAESE_ADE_SCONOSCIUTO"]
    assert len(hits) == 1


def test_wht_giorno_dopo_match(rates):
    aapl = stock()
    txs = [
        cash_tx(aapl, "2024-11-16", "Dividends", 100),
        cash_tx(aapl, "2024-11-17", "Withholding Tax", -15),  # giorno dopo
    ]
    cfg = FiscoConfig(tax_year=2024)
    warnings = WarningCollector()
    rm = compute_rm(txs, rates, cfg, warnings=warnings)
    d = rm.dividends[0]
    assert d.wht_eur == Decimal("13.89")
    assert not any(w.code == "WHT_SPAIATA" for w in warnings)


def test_wht_reversal_compensato_algebricamente(rates):
    aapl = stock()
    txs = [
        cash_tx(aapl, "2024-11-16", "Dividends", 100),
        cash_tx(aapl, "2024-11-16", "Withholding Tax", -15),
        cash_tx(aapl, "2024-11-16", "Withholding Tax", 3),  # reversal parziale
    ]
    cfg = FiscoConfig(tax_year=2024)
    rm = compute_rm(txs, rates, cfg)
    # Aggregazione algebrica: |-15+3| = 12, NON abs(-15)+abs(3) = 18
    assert rm.dividends[0].wht_ccy == Decimal("12.00")


def test_wht_spaiata_critical(rates):
    aapl = stock()
    altro = stock(symbol="MSFT", isin="US5949181045")
    txs = [
        cash_tx(aapl, "2024-11-16", "Dividends", 100),
        cash_tx(aapl, "2024-11-16", "Withholding Tax", -15),
        # ritenuta su altro titolo senza alcun dividendo compatibile
        cash_tx(altro, "2024-03-15", "Withholding Tax", -10),
    ]
    cfg = FiscoConfig(tax_year=2024)
    warnings = WarningCollector()
    compute_rm(txs, rates, cfg, warnings=warnings)
    hits = [w for w in warnings if w.code == "WHT_SPAIATA"]
    assert len(hits) == 1
    assert "MSFT" in hits[0].message
    assert warnings.has_critical()


def test_totale_imposta_somma_righe_arrotondate(rates):
    s1 = stock(symbol="A", isin="US0000000001")
    s2 = stock(symbol="B", isin="US0000000002")
    # 33.33/1.08 = 30.8611... → imposta riga q2 → totale = somma dei q2
    txs = [
        cash_tx(s1, "2024-11-16", "Dividends", "33.33"),
        cash_tx(s2, "2024-11-16", "Dividends", "33.33"),
    ]
    cfg = FiscoConfig(tax_year=2024)
    rm = compute_rm(txs, rates, cfg)
    expected = sum((d.imposta_eur for d in rm.dividends), Decimal("0"))
    assert rm.tot_imposta_dividendi == expected
    # e non q2(61.72 * 0.26) = 16.05, che differirebbe di 1 cent
    assert rm.tot_imposta_dividendi == Decimal("16.04")
    assert rm.tot_imposta_rm == expected

