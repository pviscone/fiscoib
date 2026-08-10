"""Test monitoraggio RW e IVAFE."""

from decimal import Decimal

from fiscoib.config import FiscoConfig
from fiscoib.engines.monitoring import compute_rw
from fiscoib.parsing.models import Statement
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
