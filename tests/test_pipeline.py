"""Test di integrazione: parsing del Flex XML + intera pipeline."""

import os
from decimal import Decimal

from fiscoib.config import FiscoConfig
from fiscoib.parsing.flex_parser import load
from fiscoib.pipeline import run

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_flex.xml")


def test_parsing_sample():
    stmt = load([FIXTURE])
    assert stmt.account_id == "U1234567"
    assert len(stmt.trades) == 3
    # Il BASE_SUMMARY del cash report è scartato: resta la sola valuta USD.
    assert len(stmt.cash_report) == 1
    assert stmt.cash_report[0].currency == "USD"
    assert len(stmt.open_positions) == 1


def test_pipeline_completa(rates, tmp_path):
    stmt = load([FIXTURE])
    cfg = FiscoConfig(tax_year=2024, account_country="IE")
    res = run(stmt, cfg, rates)

    # RT: solo AAPL è stato venduto -> una plusvalenza ~ €4043,28.
    assert res.rt.rows[0].plus_minus_eur == Decimal("4043.28")
    assert res.rt.rt27_imposta == Decimal("1051.25")

    # RM: un dividendo AAPL (lordo frontiera) + interessi attivi.
    assert len(res.rm.dividends) == 1
    assert res.rm.dividends[0].base_imponibile_eur == Decimal("92.59")
    assert res.rm.tot_base_interessi > 0

    # RW: righe per MSFT (aperto), AAPL (ceduto) e liquidità USD.
    descr = [r.descrizione for r in res.rw.rows]
    assert any(d.startswith("MSFT") for d in descr)
    assert any("Liquidità" in d for d in descr)
    assert res.rw.tot_ivafe_eur > 0

    # Totale imposte coerente.
    assert res.imposta_totale == (
        res.rt.rt27_imposta + res.rm.tot_imposta_rm + res.rw.tot_ivafe_eur
    )


def test_warning_si_propagano(rates):
    """Regressione: i warning accumulati nei motori devono arrivare a Results
    anche partendo da un collector vuoto (che è 'falsy' per __len__)."""
    stmt = load([FIXTURE])
    cfg = FiscoConfig(tax_year=2024, frontiera="lordo")
    res = run(stmt, cfg, rates)
    codes = {w.code for w in res.warnings}
    # Con dividendi soggetti a ritenuta e frontiera lordo, deve esserci FRONTIERA.
    assert "FRONTIERA" in codes


def test_output_generati(rates, tmp_path):
    from fiscoib.reports import quadri_facsimile, raw_export, excel_report, pdf_summary

    stmt = load([FIXTURE])
    cfg = FiscoConfig(tax_year=2024)
    res = run(stmt, cfg, rates)

    txt = quadri_facsimile.render(res)
    assert "QUADRO RW" in txt and "QUADRO RT" in txt

    raw_export.write_json(res, str(tmp_path / "r.json"))
    raw_export.write_csv(res, str(tmp_path))
    excel_report.build(res, str(tmp_path / "r.xlsx"))
    pdf_summary.build(res, str(tmp_path / "r.pdf"))

    assert (tmp_path / "r.json").exists()
    assert (tmp_path / "rt_plusvalenze.csv").exists()
    assert (tmp_path / "r.xlsx").exists()
    assert (tmp_path / "r.pdf").exists()
