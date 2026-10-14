"""Test di integrazione: parsing del Flex XML + intera pipeline."""

import os
from decimal import Decimal

import pytest

from fiscoib.config import FiscoConfig
from fiscoib.parsing.flex_parser import FlexParseError, load
from fiscoib.pipeline import run
from fiscoib.warnings import WarningCollector

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

    # IVAFE calcolata ma ≤ 200€ -> non dovuta (resta il monitoraggio RW).
    assert res.rw.ivafe_da_versare == Decimal("0")

    # Totale imposte coerente: RT + RM + IVAFE effettivamente dovuta.
    assert res.imposta_totale == (
        res.rt.rt27_imposta + res.rm.tot_imposta_rm + res.rw.ivafe_da_versare
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


# --------------------------------------------------------------------------- #
# Robustezza del parsing: dedup, colonne obbligatorie, cancellazioni, date
# --------------------------------------------------------------------------- #

def _write_xml(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<FlexQueryResponse queryName="T" type="AF"><FlexStatements count="1">'
        '<FlexStatement accountId="U1" fromDate="20240101" toDate="20241231">'
        f"{body}"
        "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )
    return str(p)


_TRADE = (
    '<Trade currency="USD" assetCategory="STK" symbol="{sym}" conid="265598" '
    "{ids}tradeDate=\"20240115\" buySell=\"{bs}\" "
    'quantity="10" tradePrice="100" proceeds="-1000" ibCommission="-1" '
    'taxes="0" {extra}/>'
)


def _trade(sym="AAPL", tid="T1", bs="BUY", extra=""):
    ids = f'transactionID="{tid}" tradeID="{tid}" ' if tid else ""
    return _TRADE.format(sym=sym, ids=ids, bs=bs, extra=extra)


_POSITION = (
    '<OpenPosition currency="USD" assetCategory="STK" symbol="MSFT" '
    'conid="272093" reportDate="20241231" levelOfDetail="SUMMARY" '
    'position="50" markPrice="370" positionValue="18500" '
    'costBasisMoney="15001.50" side="Long"/>'
)

_CASH = (
    '<CashTransaction currency="USD" {ids}type="Dividends" '
    'dateTime="20241116;200000" amount="100" description="DIV" '
    'symbol="AAPL" conid="265598"/>'
)

_CA = (
    '<CorporateAction currency="USD" {ids}type="FS" '
    'dateTime="20240115;100000" symbol="AAPL" conid="265598" '
    'description="SPLIT" quantity="100" value="0"/>'
)


def _stmt_trades(*trades):
    rows = "".join(trades)
    return f"<Trades>{rows}</Trades>"


def test_a_dedup_stesso_id_due_file(tmp_path):
    """(a) Un trade con lo stesso ID in due file conta una sola volta."""
    f1 = _write_xml(tmp_path, "f1.xml", _stmt_trades(_trade()))
    f2 = _write_xml(tmp_path, "f2.xml", _stmt_trades(_trade(), _trade(tid="T2")))
    w = WarningCollector()
    stmt = load([f1, f2], warnings=w)
    assert len(stmt.trades) == 2
    assert {t.transaction_id for t in stmt.trades} == {"T1", "T2"}


def test_b_id_assenti_warning_e_hash_dedup(tmp_path):
    """(b) ID assenti -> warning IDS_MANCANTI + dedup per hash dei contenuti."""
    body = _stmt_trades(_trade(tid="")) + (
        f"<CashTransactions>{_CASH.format(ids='')}</CashTransactions>"
        f"<CorporateActions>{_CA.format(ids='')}</CorporateActions>"
    )
    f1 = _write_xml(tmp_path, "f1.xml", body)
    f2 = _write_xml(tmp_path, "f2.xml", body)
    w = WarningCollector()
    stmt = load([f1, f2], warnings=w)
    # Hash dedup: righe identiche nei due file contano una volta sola.
    assert len(stmt.trades) == 1
    assert len(stmt.cash_transactions) == 1
    assert len(stmt.corporate_actions) == 1
    codes = [(x.code, x.level) for x in w]
    assert ("IDS_MANCANTI", "CRITICAL") in codes


def test_c_open_position_identica_due_file(tmp_path):
    """(c) La stessa OpenPosition (e riga cash report) in due file conta una volta."""
    body = (
        f"<OpenPositions>{_POSITION}</OpenPositions>"
        '<CashReport><CashReportCurrency currency="USD" fromDate="20240101" '
        'toDate="20241231" startingCash="10000" endingCash="7014.50" '
        'endingSettledCash="7014.50"/></CashReport>'
    )
    f1 = _write_xml(tmp_path, "f1.xml", body)
    f2 = _write_xml(tmp_path, "f2.xml", body)
    stmt = load([f1, f2])
    assert len(stmt.open_positions) == 1
    assert len(stmt.cash_report) == 1


def test_d_trade_cancelled_warning_e_fuori_flusso(tmp_path):
    """(d) '(Ca.)' e transactionType Cancel: warning TRADE_CANCELLED, fuori LIFO."""
    body = _stmt_trades(
        _trade(tid="T1"),
        _trade(tid="T2", bs="SELL (Ca.)"),
        _trade(tid="T3", bs="SELL", extra='transactionType="TradeCancel" '),
    )
    f1 = _write_xml(tmp_path, "f1.xml", body)
    w = WarningCollector()
    stmt = load([f1], warnings=w)
    assert [t.transaction_id for t in stmt.trades] == ["T1"]
    cancelled = [x for x in w if x.code == "TRADE_CANCELLED"]
    assert len(cancelled) == 2
    assert all(x.level == "CRITICAL" for x in cancelled)
    assert any("20240115" in x.message for x in cancelled)


def test_e_data_invalida_warning(tmp_path):
    """(e) Data non vuota ma imparsabile -> warning DATA_IMPVERSABILE."""
    body = "<Trades>" + _TRADE.format(
        sym="AAPL", ids='transactionID="T1" ', bs="BUY", extra=""
    ).replace('tradeDate="20240115"', 'tradeDate="13/45/9999"') + "</Trades>"
    f1 = _write_xml(tmp_path, "f1.xml", body)
    w = WarningCollector()
    stmt = load([f1], warnings=w)
    assert len(stmt.trades) == 1
    assert stmt.trades[0].trade_date is None
    data_warnings = [x for x in w if x.code == "DATA_IMPVERSABILE"]
    assert len(data_warnings) == 1
    assert "13/45/9999" in data_warnings[0].message


def test_f_colonna_obbligatoria_mancante_errore(tmp_path):
    """(f) Sezione presente ma colonna chiave assente -> errore esplicito."""
    body = "<Trades>" + _trade().replace('ibCommission="-1" ', "") + "</Trades>"
    f1 = _write_xml(tmp_path, "f1.xml", body)
    with pytest.raises(FlexParseError) as exc:
        load([f1])
    msg = str(exc.value)
    assert "ibCommission" in msg
    assert "Flex Query" in msg


def test_buysell_suffisso_parentetico_accettato(tmp_path):
    """'SELL (Short)' è una vendita valida; valori ignoti -> CRITICAL."""
    body = _stmt_trades(
        _trade(tid="T1", bs="SELL (Short)"),
        _trade(tid="T2", bs="XYZ"),
    )
    f1 = _write_xml(tmp_path, "f1.xml", body)
    w = WarningCollector()
    stmt = load([f1], warnings=w)
    assert len(stmt.trades) == 1
    assert stmt.trades[0].buy_sell == "SELL"
    assert not stmt.trades[0].is_buy
    unknown = [x for x in w if x.code == "BUY_SELL_SCONOSCIUTO"]
    assert len(unknown) == 1
    assert unknown[0].level == "CRITICAL"
    assert "XYZ" in unknown[0].message


def test_dup_discordante_stesso_id_valori_diversi(tmp_path):
    """Stesso ID, campi fiscali diversi -> DUP_DISCORDANTE, mai scarto cieco."""
    f1 = _write_xml(tmp_path, "f1.xml", _stmt_trades(_trade()))
    f2 = _write_xml(
        tmp_path, "f2.xml", _stmt_trades(_trade().replace('quantity="10"', 'quantity="12"'))
    )
    w = WarningCollector()
    stmt = load([f1, f2], warnings=w)
    assert len(stmt.trades) == 1
    assert stmt.trades[0].quantity == Decimal("10")
    dup = [x for x in w if x.code == "DUP_DISCORDANTE"]
    assert len(dup) == 1
    assert dup[0].level == "CRITICAL"
    assert "10" in dup[0].message and "12" in dup[0].message
