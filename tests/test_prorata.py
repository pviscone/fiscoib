"""Test del pro-rata titoli di Stato white list sugli OICR (ETF/fondi).

Regola: aliquota effettiva = 26% - 13,5% x quota media govies nel periodo di
possesso (art. 2 c. 1-quater D.L. 138/2011). Valori calcolati a mano:

    quota media 2024-07-01 -> 2025-06-30 con {2024: 0.4, 2025: 0.6}:
    giorni 2024 = 184, giorni 2025 = 181, totale 365
    q = (0.4 x 184 + 0.6 x 181) / 365 = 182.2 / 365
    imposta su gain 2000 EUR = 2000 x (0.26 - 0.135 x q)
                             = 520 - 270 x 182.2/365
                             = 520 - 134,77808... = 385,22 EUR
"""

from datetime import date
from decimal import Decimal

import pytest

from fiscoib.config import FiscoConfig
from fiscoib.engines.capital_gains import compute_rt
from fiscoib.engines.income import compute_rm
from fiscoib.engines.lots import build_closures
from fiscoib.parsing.models import Statement
from fiscoib.pipeline import run
from fiscoib.prorata import FundGovQuotas, effective_rate
from helpers import cash_tx, etf, stock, trade


def _cfg(year=2024):
    return FiscoConfig(tax_year=year)


def test_constants_effective_rate():
    assert effective_rate(Decimal("0.26"), Decimal("0")) == Decimal("0.26")
    assert effective_rate(Decimal("0.26"), Decimal("0.5")) == Decimal("0.192500")
    assert effective_rate(Decimal("0.26"), Decimal("1")) == Decimal("0.125000")


def test_from_json_dict_formati():
    q = FundGovQuotas.from_json_dict(
        {"IE00A": 0.575, "IE00B": {"2024": "0.55", "2025": 0.6}}
    )
    assert q.lookup("IE00A")[2024] == Decimal("0.575")  # costante per tutti gli anni
    # Lookup per simbolo/caratteri misti (normalizzazione upper).
    assert q.lookup("ie00b")[2024] == Decimal("0.55")
    assert q.lookup("IE00B")[2025] == Decimal("0.6")
    assert q.lookup("ISIN_ASSENTE") is None


def test_from_json_dict_quota_fuori_range_errore():
    with pytest.raises(ValueError):
        FundGovQuotas.from_json_dict({"IE00A": 1.5})
    with pytest.raises(ValueError):
        FundGovQuotas.from_json_dict({"IE00A": {"2024": -0.1}})
    with pytest.raises(ValueError):
        FundGovQuotas.from_json_dict(["IE00A"])


def test_average_quota_media_pesata_due_anni():
    q = FundGovQuotas.from_json_dict({"IE00A": {"2024": "0.4", "2025": "0.6"}})
    info = q.average_quota(
        ("IE00A",), date(2024, 7, 1), date(2025, 6, 30)
    )
    assert info.missing_years == ()
    assert info.quota == Decimal("182.2") / Decimal("365")


def test_average_quota_ano_mancante_pesa_zero():
    q = FundGovQuotas.from_json_dict({"IE00A": {"2024": "0.5"}})
    info = q.average_quota(("IE00A",), date(2024, 7, 1), date(2025, 6, 30))
    assert info.missing_years == (2025,)
    assert info.quota == Decimal("92") / Decimal("365")


def test_oicr_gain_con_prorata(rates):
    """ETF obbligazionario misto: aliquota effettiva 26% - 13,5% x quota media."""
    inst = etf(isin="IE00A")
    trades = [
        trade(inst, "2024-07-01", "BUY", 100, 80, currency="EUR"),
        trade(inst, "2025-06-30", "SELL", 100, 100, currency="EUR"),
    ]
    closures, _ = build_closures(trades, [])
    fq = FundGovQuotas.from_json_dict({"IE00A": {"2024": "0.4", "2025": "0.6"}})
    rt = compute_rt(closures, rates, _cfg(2025), fund_gov_quotas=fq)

    assert len(rt.oicr_gains) == 1
    g = rt.oicr_gains[0]
    assert g["gain_eur"] == Decimal("2000.00")
    assert g["quota_gov"] == Decimal("182.2") / Decimal("365")
    # 520 - 134,77808... = 385,2219178... -> 385,22.
    assert g["imposta_eur"] == Decimal("385.22")
    assert rt.oicr_imponibile == Decimal("2000.00")
    assert rt.oicr_imposta == Decimal("385.22")


def test_oicr_gain_senza_file_quota_26_e_warning(rates):
    """Senza --fund-gov-quota: aliquota piena 26% (prudente) + warning una volta."""
    inst = etf(isin="IE00A")
    trades = [
        trade(inst, "2024-01-15", "BUY", 100, 80, currency="EUR"),
        trade(inst, "2024-06-20", "SELL", 100, 100, currency="EUR"),
    ]
    closures, _ = build_closures(trades, [])
    from fiscoib.warnings import WarningCollector

    warnings = WarningCollector()
    rt = compute_rt(closures, rates, _cfg(2024), warnings=warnings)

    assert rt.oicr_gains[0]["imposta_eur"] == Decimal("520.00")  # 2000 x 26%
    assert rt.oicr_gains[0]["quota_gov"] is None
    codes = [(w.code, w.level) for w in warnings]
    assert ("PRORATA_DA_CLASSIFICARE", "WARN") in codes
    assert len([w for w in warnings if w.code == "PRORATA_DA_CLASSIFICARE"]) == 1


def test_oicr_gain_fondo_assente_dal_file(rates):
    """File presente ma ISIN del fondo assente: 26% + warning."""
    inst = etf(isin="IE00A")
    trades = [
        trade(inst, "2024-01-15", "BUY", 100, 80, currency="EUR"),
        trade(inst, "2024-06-20", "SELL", 100, 100, currency="EUR"),
    ]
    closures, _ = build_closures(trades, [])
    from fiscoib.warnings import WarningCollector

    warnings = WarningCollector()
    fq = FundGovQuotas.from_json_dict({"ALTR0FONDO": 0.5})
    rt = compute_rt(closures, rates, _cfg(2024), warnings=warnings,
                    fund_gov_quotas=fq)

    assert rt.oicr_gains[0]["imposta_eur"] == Decimal("520.00")
    assert ("PRORATA_DA_CLASSIFICARE", "WARN") in [(w.code, w.level) for w in warnings]


def test_oicr_gain_anni_parziali_warning(rates):
    """Anni del possesso non coperti dal dato: quota 0 su quella frazione."""
    inst = etf(isin="IE00A")
    trades = [
        trade(inst, "2024-07-01", "BUY", 100, 80, currency="EUR"),
        trade(inst, "2025-06-30", "SELL", 100, 100, currency="EUR"),
    ]
    closures, _ = build_closures(trades, [])
    from fiscoib.warnings import WarningCollector

    warnings = WarningCollector()
    fq = FundGovQuotas.from_json_dict({"IE00A": {"2024": "0.5"}})
    rt = compute_rt(closures, rates, _cfg(2025), warnings=warnings, fund_gov_quotas=fq)

    # q = 0.5 x 184/365; imposta = 520 - 270 x 92/365 = 520 - 68,0548 = 451,95.
    assert rt.oicr_gains[0]["quota_gov"] == Decimal("92") / Decimal("365")
    assert rt.oicr_gains[0]["imposta_eur"] == Decimal("451.95")
    assert ("PRORATA_ANNI_PARZIALI", "WARN") in [(w.code, w.level) for w in warnings]


def test_distibuzione_fondo_con_prorata(rates):
    """Distribuzione di ETF: prorata con la quota media dell'anno di pagamento."""
    inst = etf(isin="IE00A")
    txs = [cash_tx(inst, "2024-03-15", "Dividends", 100, currency="EUR")]
    fq = FundGovQuotas.from_json_dict({"IE00A": 0.5})
    rm = compute_rm(txs, rates, _cfg(2024), fund_gov_quotas=fq)

    assert len(rm.dividends) == 1
    d = rm.dividends[0]
    assert d.aliquota == Decimal("0.192500")
    assert d.quota_gov == Decimal("0.5")
    assert d.base_imponibile_eur == Decimal("100.00")
    assert d.imposta_eur == Decimal("19.25")  # 100 x 19,25%


def test_distibuzione_azione_non_toccata_dal_prorata(rates):
    """Il dividendo azionario resta al 26% anche con file prorata passato."""
    inst = stock()
    txs = [cash_tx(inst, "2024-03-15", "Dividends", 100, currency="USD")]
    fq = FundGovQuotas.from_json_dict({"US0378331005": 0.9})
    rm = compute_rm(txs, rates, _cfg(2024), fund_gov_quotas=fq)

    d = rm.dividends[0]
    assert d.aliquota == Decimal("0.26")
    assert d.quota_gov is None


def test_imposta_totale_include_oicr(rates):
    """Regressione: l'imposta sui gain OICR entra nel totale da versare."""
    inst = etf(isin="IE00A")
    stmt = Statement()
    stmt.trades = [
        trade(inst, "2024-01-15", "BUY", 100, 80, currency="EUR"),
        trade(inst, "2024-06-20", "SELL", 100, 100, currency="EUR"),
    ]
    fq = FundGovQuotas.from_json_dict({"IE00A": 0.5})
    results = run(stmt, _cfg(2024), rates, fund_gov_quotas=fq)

    assert results.rt.oicr_imposta == Decimal("385.00")  # 2000 x 19,25%
    assert results.imposta_totale == (
        results.rt.rt27_imposta
        + results.rm.tot_imposta_rm
        + Decimal("385.00")
        + results.rw.ivafe_da_versare
    )
