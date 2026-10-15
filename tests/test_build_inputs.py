"""Test della generazione automatica dei JSON di input (build_inputs)."""

import json
from datetime import date
from decimal import Decimal

from fiscoib.build_inputs import (
    classify_bonds,
    classify_funds,
    collect_bond_issuers,
    collect_funds,
    write_fund_quota_template,
    write_gov_bonds_template,
    write_overrides,
)
from fiscoib.parsing.models import Instrument, Statement
from helpers import cash_tx, etf, open_position, stock, trade


def _btp():
    return Instrument(
        conid="BTP35",
        symbol="BTPS",
        description="BTPS 4.4 01/05/35",
        asset_category="BOND",
        isin="IT0005425233",
        listing_exchange="MOT",
        currency="EUR",
    )


def _statement():
    btp = _btp()
    iwda = etf()  # is_fund
    aapl = stock()
    stmt = Statement()
    stmt.trades = [
        trade(aapl, "2024-01-15", "BUY", 10, 100, currency="USD"),
        trade(iwda, "2024-01-15", "BUY", 10, 80, currency="EUR"),
        trade(btp, "2024-02-01", "BUY", 2, 1000, currency="EUR"),
    ]
    stmt.cash_transactions = [
        cash_tx(btp, "2024-05-01", "Bond Interest Received", 44, currency="EUR"),
    ]
    stmt.open_positions = [open_position(iwda, "2024-12-31", 10, 90, currency="EUR")]
    return stmt


def test_collect_bond_issuers_unione_cedole_e_trade():
    bonds = collect_bond_issuers(_statement())
    assert [b.ident for b in bonds] == ["IT0005425233"]
    assert bonds[0].description.startswith("BTPS")


def test_collect_bond_issuers_solo_trade_bond():
    """Bond mai pagato cedola nello statement: entra comunque dal trade BOND."""
    stmt = Statement()
    stmt.trades = [trade(_btp(), "2024-02-01", "BUY", 2, 1000, currency="EUR")]
    assert [b.ident for b in collect_bond_issuers(stmt)] == ["IT0005425233"]


def test_collect_funds_da_trade_cash_e_posizioni():
    funds = collect_funds(_statement())
    assert {f.ident for f in funds} == {"IE00B4L5Y983"}
    # Azioni e bond non entrano.
    assert not any(f.symbol == "AAPL" for f in funds)


def test_gov_bonds_template_json_valido(tmp_path):
    p = tmp_path / "gov_bonds.bozza.json"
    groups = classify_bonds(collect_bond_issuers(_statement()))
    write_gov_bonds_template(groups["govies"], str(p))
    assert json.loads(p.read_text()) == ["IT0005425233"]


def _bond(isin, symbol, description):
    return Instrument(
        conid=symbol, symbol=symbol, description=description,
        asset_category="BOND", isin=isin, listing_exchange="MOT", currency="EUR",
    )


def _collect(*bonds):
    stmt = Statement()
    stmt.cash_transactions = [
        cash_tx(b, "2024-05-01", "Bond Interest Received", 10, currency="EUR")
        for b in bonds
    ]
    return collect_bond_issuers(stmt)


def test_classifica_govy_whitelist(token=""):
    groups = classify_bonds(_collect(
        _bond("IT0005425233", "BTPS 4.4 01/05/35", "ITALY GOVT BOND 4.4 2035"),
        _bond("US912810TV79", "T 4.5 11/15/53", "US TREASURY NOTE 4.5 2053"),
        _bond("DE000BU22026", "BUND 2.3 02/15/33", "FEDERAL REPUBLIC OF GERMANY 2.3 2033"),
    ))
    assert {g.ident for g in groups["govies"]} == {
        "IT0005425233", "US912810TV79", "DE000BU22026"}
    assert groups["non_whitelisted"] == []
    assert groups["da_verificare"] == []


def test_classifica_corporate_fiori():
    """Corporate dello stesso paese white list (ISPINT) NON deve assorbire il 12,5%."""
    groups = classify_bonds(_collect(
        _bond("XS1123456789", "ISPINT 5.0 03/08/26", "INTESA SANPAOLO 5.0 2026"),
    ))
    assert groups["govies"] == []
    assert {d.ident for d in groups["da_verificare"]} == {"XS1123456789"}
    # XS non è un paese white list; anche un ISPINT con ISIN IT493988...?
    groups2 = classify_bonds(_collect(
        _bond("IT0009998888", "ISPINT 5.0 03/08/26", "INTESA SANPAOLO 5.0 2026"),
    ))
    assert groups2["govies"] == []


def _funds_collected(insts):
    stmt = Statement()
    stmt.trades = [
        trade(f, "2024-01-15", "BUY", 10, 80, currency="EUR") for f in insts
    ]
    return collect_funds(stmt)


def test_classifica_etf_equity_vs_bond():
    iwda = etf(symbol="SWDA", isin="IE00B4L5Y983")
    iwda.description = "ISHARES CORE MSCI WORLD UCITS ACC"
    agg = etf(symbol="AGGG", isin="IE00BDBRDM35")
    agg.description = "ISHARES CORE GLOBAL AGGREGATE BOND UCITS ACC"
    xyz = etf(symbol="XYZQ", isin="IE00A")
    xyz.description = "XYZ UCITS ETF"
    groups = classify_funds(_funds_collected([iwda, agg, xyz]))

    assert {f.ident for f in groups["equity_only"]} == {"IE00B4L5Y983"}
    # Obbligazionario e incerto finiscono in bozza (prudente: rigo in più).
    assert {f.ident for f in groups["bond_like"]} == {"IE00BDBRDM35", "IE00A"}


def test_classifica_etf_govt_batteketo_equity():
    """'WORLD' (hint equity) + 'GOVT BOND' (hint bond): vince il bond."""
    f = etf(symbol="WGEB", isin="IE00B")
    f.description = "VANGUARD GLOBAL WORLD GOVT BOND UCITS"
    groups = classify_funds(_funds_collected([f]))
    assert {x.ident for x in groups["bond_like"]} == {"IE00B"}
    assert groups["equity_only"] == []


def test_classifica_emergente_fuori_dal_file():
    """Sovrano emergente: riconosciuto ma FUORI dalla lista conservativa."""
    groups = classify_bonds(_collect(
        _bond("BRSTNCNTF1W8", "BRAZIL 6.0 05/15/35", "BRAZIL GOVT INTL BOND 6.0 2035"),
    ))
    assert groups["govies"] == []
    assert {n.ident for n in groups["non_whitelisted"]} == {"BRSTNCNTF1W8"}


def test_fund_quota_template_sicuro_e_valido(tmp_path):
    """Quote a 0.0 = aliquota piena (mai meno imposta del dovuto)."""
    p = tmp_path / "fund_gov_quota.bozza.json"
    funds = collect_funds(_statement())
    write_fund_quota_template(funds, str(p))
    data = json.loads(p.read_text())
    assert data == {"IE00B4L5Y983": 0.0}

    # Il file prodotto è caricabile da FundGovQuotas.
    from fiscoib.prorata import FundGovQuotas

    fq = FundGovQuotas.load(str(p))
    info = fq.average_quota(("IE00B4L5Y983",), date(2024, 1, 1), date(2024, 12, 31))
    assert info is not None
    assert info.quota == Decimal("0")


def test_overrides_mesi_completi_e_valute(tmp_path, rates):
    """USD presente nello statement (preloadato), EUR escluso per convenzione."""
    for m in range(1, 13):
        rates.preload(f"2024-{m:02d}", "USD", "monthly", Decimal("1.10"), "test")

    p = tmp_path / "overrides.json"
    missing = write_overrides(_statement(), 2024, rates, str(p))
    assert missing == []

    rows = json.loads(p.read_text())
    assert len(rows) == 12
    assert rows[0] == {"currency": "USD", "year": 2024, "month": 1, "rate": 1.1}


def test_overrides_valuta_mancante_segnalata(tmp_path, rates):
    """Offline/senza dato: valuta segnalata e file parziale ma valido.

    La fixture condivide un override per gennaio 2024: il file scritto contiene
    solo i mesi disponibili fino al primo fetch fallito.
    """
    p = tmp_path / "overrides.json"
    missing = write_overrides(_statement(), 2024, rates, str(p))
    assert missing == ["USD"]
    rows = json.loads(p.read_text())
    assert rows == [{"currency": "USD", "year": 2024, "month": 1, "rate": 1.09}]
