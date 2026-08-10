"""Parser dei Flex Query XML di Interactive Brokers.

Scelte di robustezza:
- Si usa ``xml.etree.ElementTree`` (stdlib) leggendo gli attributi in modo
  generico: se IBKR aggiunge/rinomina attributi il parser non si rompe.
- Si accettano PIÙ file (lo storico Activity Flex copre max 365 giorni): gli
  eventi vengono uniti e deduplicati per ``transactionID`` / ``tradeID``.
- Gli importi restano in valuta originale; ``fxRateToBase`` di IBKR è conservato
  solo come reference (non è fiscalmente valido).
"""

from __future__ import annotations

import glob
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

from ..money import dec
from .models import (
    CashReportRow,
    CashTransaction,
    CorporateAction,
    Instrument,
    OpenPosition,
    Statement,
    Trade,
)


class FlexParseError(Exception):
    pass


def _parse_date(value: Optional[str]) -> Optional[date]:
    """Interpreta i formati data IBKR: ``yyyyMMdd``, ``yyyy-MM-dd``,
    con eventuale ``;HHmmss`` o spazio-orario."""
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    # Rimuove la parte oraria dopo ';' o spazio.
    for sep in (";", " "):
        if sep in v:
            v = v.split(sep, 1)[0]
    v = v.replace("-", "").replace("/", "")
    if len(v) >= 8 and v[:8].isdigit():
        try:
            return datetime.strptime(v[:8], "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _instrument(attr: Dict[str, str]) -> Instrument:
    return Instrument(
        conid=attr.get("conid", ""),
        symbol=attr.get("symbol", ""),
        description=attr.get("description", ""),
        asset_category=attr.get("assetCategory", ""),
        isin=attr.get("isin", ""),
        listing_exchange=attr.get("listingExchange", ""),
        currency=attr.get("currency", ""),
        multiplier=dec(attr.get("multiplier"), Decimal("1")) or Decimal("1"),
        sub_category=attr.get("subCategory", ""),
    )


def _iter(root: ET.Element, tag: str):
    """Itera su tutti gli elementi con un dato tag ovunque nell'albero."""
    yield from root.iter(tag)


def _parse_trade(el: ET.Element) -> Optional[Trade]:
    a = el.attrib
    tx_type = a.get("transactionType", "")
    buy_sell = a.get("buySell", "")
    # Scarta cancellazioni: verranno segnalate a monte.
    if tx_type in {"TradeCancel"} or buy_sell.upper().startswith("CANCEL"):
        return None
    # Considera solo movimenti di compravendita reali.
    if buy_sell.upper() not in {"BUY", "SELL"}:
        return None
    return Trade(
        instrument=_instrument(a),
        trade_id=a.get("tradeID", ""),
        transaction_id=a.get("transactionID", "") or a.get("ibExecID", ""),
        trade_date=_parse_date(a.get("tradeDate") or a.get("dateTime")),
        settle_date=_parse_date(a.get("settleDateTarget") or a.get("settleDate")),
        buy_sell=buy_sell,
        open_close=a.get("openCloseIndicator", ""),
        quantity=abs(dec(a.get("quantity"))),
        price=dec(a.get("tradePrice")),
        proceeds=dec(a.get("proceeds")),
        commission=dec(a.get("ibCommission")),
        commission_currency=a.get("ibCommissionCurrency", a.get("currency", "")),
        taxes=dec(a.get("taxes")),
        currency=a.get("currency", ""),
        notes=a.get("notes", a.get("code", "")),
        fx_rate_to_base=dec(a.get("fxRateToBase")),
        raw=dict(a),
    )


def _parse_cash_tx(el: ET.Element) -> Optional[CashTransaction]:
    a = el.attrib
    tx_type = a.get("type", "")
    if not tx_type:
        return None
    inst = _instrument(a) if a.get("symbol") or a.get("conid") else None
    return CashTransaction(
        instrument=inst,
        transaction_id=a.get("transactionID", ""),
        tx_type=tx_type,
        when=_parse_date(a.get("dateTime") or a.get("settleDate") or a.get("reportDate")),
        amount=dec(a.get("amount")),
        currency=a.get("currency", ""),
        description=a.get("description", ""),
        fx_rate_to_base=dec(a.get("fxRateToBase")),
        raw=dict(a),
    )


def _parse_open_position(el: ET.Element) -> Optional[OpenPosition]:
    a = el.attrib
    # Evita di duplicare i livelli SUMMARY+LOT: si tiene solo LOT se presente,
    # altrimenti SUMMARY. La deduplica fine avviene a valle; qui prendiamo tutto
    # e filtriamo per levelOfDetail nel builder.
    return OpenPosition(
        instrument=_instrument(a),
        report_date=_parse_date(a.get("reportDate")),
        quantity=dec(a.get("position")),
        mark_price=dec(a.get("markPrice")),
        position_value=dec(a.get("positionValue")),
        cost_basis_money=dec(a.get("costBasisMoney")),
        currency=a.get("currency", ""),
        side=a.get("side", ""),
        open_datetime=_parse_date(a.get("openDateTime")),
        raw=dict(a),
    )


def _parse_cash_report(el: ET.Element) -> Optional[CashReportRow]:
    a = el.attrib
    cur = a.get("currency", "")
    # Le righe aggregate "BASE_SUMMARY" non servono: si lavora per valuta.
    if cur in {"", "BASE_SUMMARY"}:
        return None
    return CashReportRow(
        currency=cur,
        from_date=_parse_date(a.get("fromDate")),
        to_date=_parse_date(a.get("toDate")),
        starting_cash=dec(a.get("startingCash")),
        ending_cash=dec(a.get("endingCash")),
        ending_settled_cash=dec(a.get("endingSettledCash", a.get("endingCash"))),
        raw=dict(a),
    )


def _parse_corporate_action(el: ET.Element) -> Optional[CorporateAction]:
    a = el.attrib
    return CorporateAction(
        instrument=_instrument(a),
        transaction_id=a.get("transactionID", ""),
        when=_parse_date(a.get("dateTime") or a.get("reportDate")),
        ca_type=a.get("type", ""),
        description=a.get("description", ""),
        quantity=dec(a.get("quantity")),
        value=dec(a.get("value")),
        currency=a.get("currency", ""),
        raw=dict(a),
    )


def parse_file(path: str) -> Statement:
    """Parsa un singolo file Flex XML in uno ``Statement``."""
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise FlexParseError(f"XML non valido in {path}: {exc}") from exc
    root = tree.getroot()

    stmt = Statement()

    # Metadati dal primo FlexStatement.
    fs = root.find(".//FlexStatement")
    if fs is not None:
        stmt.account_id = fs.attrib.get("accountId", "")
        stmt.from_date = _parse_date(fs.attrib.get("fromDate"))
        stmt.to_date = _parse_date(fs.attrib.get("toDate"))
    # Base currency: talvolta su AccountInformation.
    ai = root.find(".//AccountInformation")
    if ai is not None:
        stmt.base_currency = ai.attrib.get("currency", "")

    for el in _iter(root, "Trade"):
        t = _parse_trade(el)
        if t:
            stmt.trades.append(t)
    for el in _iter(root, "CashTransaction"):
        c = _parse_cash_tx(el)
        if c:
            stmt.cash_transactions.append(c)
    for el in _iter(root, "OpenPosition"):
        p = _parse_open_position(el)
        if p:
            stmt.open_positions.append(p)
    for el in _iter(root, "CashReportCurrency"):
        r = _parse_cash_report(el)
        if r:
            stmt.cash_report.append(r)
    for el in _iter(root, "CorporateAction"):
        ca = _parse_corporate_action(el)
        if ca:
            stmt.corporate_actions.append(ca)

    return stmt


def _dedup_by_id(items: List, id_getter) -> List:
    """Rimuove i duplicati mantenendo il primo, per file sovrapposti."""
    seen = set()
    out = []
    for it in items:
        key = id_getter(it)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(it)
    return out


def load(paths: List[str]) -> Statement:
    """Carica e unisce più file Flex (supporta glob), deduplicando gli eventi.

    ``paths`` può contenere pattern glob (es. ``ib_*.xml``).
    """
    expanded: List[str] = []
    for p in paths:
        matches = sorted(glob.glob(p))
        expanded.extend(matches if matches else [p])
    if not expanded:
        raise FlexParseError("Nessun file di input trovato.")

    merged = Statement()
    for path in expanded:
        merged.merge(parse_file(path))

    # Deduplica: i file annuali possono sovrapporsi ai bordi.
    merged.trades = _dedup_by_id(merged.trades, lambda t: t.transaction_id or t.trade_id)
    merged.cash_transactions = _dedup_by_id(
        merged.cash_transactions, lambda c: c.transaction_id
    )
    merged.corporate_actions = _dedup_by_id(
        merged.corporate_actions, lambda c: c.transaction_id
    )
    # Open positions: si tengono le righe LOT se disponibili, evitando di sommare
    # anche il livello SUMMARY per lo stesso strumento/data.
    merged.open_positions = _dedup_open_positions(merged.open_positions)
    return merged


def _dedup_open_positions(positions: List[OpenPosition]) -> List[OpenPosition]:
    """Se per (strumento, data) esistono righe LOT, scarta la riga SUMMARY."""
    by_key: Dict[tuple, List[OpenPosition]] = {}
    for p in positions:
        key = (p.instrument.key(), p.report_date)
        by_key.setdefault(key, []).append(p)

    out: List[OpenPosition] = []
    for key, group in by_key.items():
        levels = {(pos.raw.get("levelOfDetail") or "").upper() for pos in group}
        if "LOT" in levels and "SUMMARY" in levels:
            out.extend(p for p in group if (p.raw.get("levelOfDetail") or "").upper() == "LOT")
        else:
            out.extend(group)
    return out
