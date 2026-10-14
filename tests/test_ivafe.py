"""Test monitoraggio RW e IVAFE."""

from datetime import date
from decimal import Decimal

import pytest

from fiscoib.config import FiscoConfig
from fiscoib.engines.monitoring import compute_rw
from fiscoib.money import q2
from fiscoib.parsing.models import CashReportRow, Statement
from fiscoib.pipeline import run
from fiscoib.reports import quadri_facsimile
from helpers import stock, cfd, open_position, trade


def test_ivafe_portafoglio_intero_anno(rates):
    """50.000 USD al 31/12, cambio medio dic 1.0479 -> IVAFE ~ €95,43."""
    aapl = stock()
    stmt = Statement(from_date=None, to_date=None)
    stmt.open_positions = [open_position(aapl, "2024-12-31", 500, 100)]  # 50.000 USD
    cfg = FiscoConfig(tax_year=2024)
    rw = compute_rw(stmt, rates, cfg)

    assert rw.tot_ivafe_eur == Decimal("95.43")
    # Valore finale ~ 47.714 EUR
    assert rw.rows[0].valore_finale_eur == 47714
    assert rw.rows[0].giorni == 365
    assert rw.rows[0].codice_bene == "20"


def test_ivafe_titolo_multi_lotto(rates):
    """Open Positions a livello Lot: più righe stesso titolo vanno SOMMATE.

    500 azioni totali (200+300) a 100 USD = 50.000 USD al 31/12: deve dare lo
    stesso identico risultato del caso a riga singola, non solo l'ultimo lotto.
    """
    aapl = stock()
    stmt = Statement()
    stmt.open_positions = [
        open_position(aapl, "2024-12-31", 200, 100),  # 20.000 USD
        open_position(aapl, "2024-12-31", 300, 100),  # 30.000 USD
    ]
    cfg = FiscoConfig(tax_year=2024)
    rw = compute_rw(stmt, rates, cfg)

    # Un solo rigo aggregato, con i valori dell'intera posizione da 50.000 USD.
    rows = [r for r in rw.rows if r.descrizione.startswith("AAPL")]
    assert len(rows) == 1
    assert rows[0].valore_finale_eur == 47714
    assert rw.tot_ivafe_eur == Decimal("95.43")


def test_cfd_solo_monitoraggio_default(rates):
    """Di default il CFD è solo monitoraggio: IVAFE = 0."""
    c = cfd()
    stmt = Statement()
    stmt.open_positions = [open_position(c, "2024-12-31", 100, 50)]
    cfg = FiscoConfig(tax_year=2024)
    rw = compute_rw(stmt, rates, cfg)

    row = rw.rows[0]
    assert row.codice_bene == "9"
    assert row.solo_monitoraggio is True
    assert row.ivafe_eur == Decimal("0")


def test_cfd_ivafe_se_abilitata(rates):
    c = cfd()
    stmt = Statement()
    stmt.open_positions = [open_position(c, "2024-12-31", 100, 50)]
    cfg = FiscoConfig(tax_year=2024, ivafe_cfd=True)
    rw = compute_rw(stmt, rates, cfg)
    assert rw.rows[0].ivafe_eur > 0


def test_titolo_comprato_e_venduto_in_anno(rates):
    """Titolo aperto e chiuso in anno: va comunque dichiarato, giorni pro-rata."""
    aapl = stock()
    stmt = Statement()
    stmt.trades = [
        trade(aapl, "2024-01-15", "BUY", 100, 180),
        trade(aapl, "2024-06-20", "SELL", 100, 220),
    ]
    cfg = FiscoConfig(tax_year=2024)
    rw = compute_rw(stmt, rates, cfg)
    # Un rigo per il titolo, giorni = dal 15/1 al 20/6.
    rows = [r for r in rw.rows if r.descrizione.startswith("AAPL")]
    assert len(rows) == 1
    assert 150 < rows[0].giorni < 160


def test_rigo_rw_stato_estero_ade_us(rates):
    """Conto negli USA: il rigo RW riporta il codice AdE 069 (Tabella 10)."""
    aapl = stock()
    stmt = Statement()
    stmt.open_positions = [open_position(aapl, "2024-12-31", 500, 100)]
    cfg = FiscoConfig(tax_year=2024, account_country="US")
    rw = compute_rw(stmt, rates, cfg)

    row = rw.rows[0]
    assert row.stato_estero == "US"
    assert row.stato_estero_ade == "069"


def test_rigo_rw_stato_ade_ignoto_fallback(rates):
    """Stato non mappato: warning e fallback sul codice ISO originale."""
    aapl = stock()
    stmt = Statement()
    stmt.open_positions = [open_position(aapl, "2024-12-31", 500, 100)]
    cfg = FiscoConfig(tax_year=2024, account_country="ZZ")
    from fiscoib.warnings import WarningCollector
    wc = WarningCollector()
    rw = compute_rw(stmt, rates, cfg, wc)

    assert rw.rows[0].stato_estero_ade == "ZZ"
    assert any(w.code == "ADE_STATO_IGNOTO" for w in wc)


def test_liquidita_codice_valorizzazione_nominale(rates):
    """La liquidità va valorizzata al nominale: codice valorizzazione '3'."""
    stmt = Statement()
    stmt.cash_report = [
        CashReportRow(
            currency="USD",
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
            starting_cash=Decimal("0"),
            ending_cash=Decimal("10000"),
            ending_settled_cash=Decimal("10000"),
        )
    ]
    cfg = FiscoConfig(tax_year=2024)
    rw = compute_rw(stmt, rates, cfg)

    cash = [r for r in rw.rows if r.descrizione.startswith("Liquidità")]
    assert len(cash) == 1
    assert cash[0].codice_valorizzazione == "3"
    assert cash[0].stato_estero_ade == "040"  # conto IE di default


def test_sanzione_potenziale_blacklist(rates):
    """Conto in Paese black list: sanzioni 6%-30% anziché 3%-15%."""
    aapl = stock()
    stmt = Statement()
    stmt.open_positions = [open_position(aapl, "2024-12-31", 500, 100)]
    cfg = FiscoConfig(tax_year=2024, account_is_blacklist=True)
    rw = compute_rw(stmt, rates, cfg)

    smin, smax = rw.sanzione_potenziale()
    base = Decimal("47714")
    assert smin == q2(base * Decimal("0.06"))
    assert smax == q2(base * Decimal("0.30"))


def test_ivafe_sotto_soglia_200_non_dovuta(rates):
    """IVAFE complessiva € 65 (≤ 200€): segnalata come non dovuta e fuori dal dovuto."""
    aapl = stock()
    # 34.100 USD / 1.0479 ≈ € 32.541 → IVAFE ≈ € 65,08
    stmt = Statement()
    stmt.open_positions = [open_position(aapl, "2024-12-31", 341, 100)]
    cfg = FiscoConfig(tax_year=2024)
    results = run(stmt, cfg, rates)
    rw = results.rw

    assert Decimal("64") < rw.tot_ivafe_eur < Decimal("66")
    assert rw.ivafe_non_dovuta is True
    assert rw.ivafe_da_versare == Decimal("0")
    # L'IVAFE non entra nel totale delle imposte da versare.
    assert results.imposta_totale == results.rt.rt27_imposta + results.rm.tot_imposta_rm

    txt = quadri_facsimile.render(results)
    assert "VERSAMENTO NON DOVUTO" in txt
    assert "dichiarare solo RW" in txt


def test_ivafe_sopra_soglia_200_invariata(rates):
    """IVAFE > 200€: sempre dovuta, nessuna variazione rispetto al calcolo teorico."""
    aapl = stock()
    # 105.000 USD / 1.0479 ≈ € 100.201 → IVAFE ≈ € 200,40
    stmt = Statement()
    stmt.open_positions = [open_position(aapl, "2024-12-31", 1050, 100)]
    cfg = FiscoConfig(tax_year=2024)
    results = run(stmt, cfg, rates)
    rw = results.rw

    assert rw.tot_ivafe_eur > Decimal("200")
    assert rw.ivafe_non_dovuta is False
    assert rw.ivafe_da_versare == rw.tot_ivafe_eur
    assert results.imposta_totale == (
        results.rt.rt27_imposta + results.rm.tot_imposta_rm + rw.tot_ivafe_eur
    )
    txt = quadri_facsimile.render(results)
    assert "NON DOVUTO" not in txt


def test_cli_prior_losses_mancante_fatale(tmp_path):
    """--prior-losses con path inesistente: errore fatale (exit ≠ 0), mai ignorato."""
    from fiscoib.cli import main

    rc = main([
        "input.xml", "--anno", "2024", "--out", str(tmp_path),
        "--prior-losses", str(tmp_path / "non_esiste.json"),
    ])
    assert rc != 0


def test_cli_quota_fuori_range_rifiutata(tmp_path):
    """--quota deve essere (0, 100]: 200 va rifiutata da argparse."""
    from fiscoib.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["input.xml", "--anno", "2024", "--out", str(tmp_path), "--quota", "200"])
    assert exc.value.code != 0


def test_cli_stato_non_iso_rifiutato(tmp_path):
    """--stato deve essere un codice ISO alpha-2 (^\\[A-Z]{2}$)."""
    from fiscoib.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["input.xml", "--anno", "2024", "--out", str(tmp_path), "--stato", "USA"])
    assert exc.value.code != 0
