"""Parser dei Flex Query XML di Interactive Brokers.

Scelte di robustezza:
- Si usa ``xml.etree.ElementTree`` (stdlib) leggendo gli attributi in modo
  generico: se IBKR aggiunge/rinomina attributi il parser non si rompe.
- Si accettano PIÙ file (lo storico Activity Flex copre max 365 giorni): gli
  eventi vengono uniti e deduplicati per ``transactionID`` / ``tradeID``; se gli
  ID mancano (colonne opzionali della Flex Query) si emette un warning CRITICAL
  e si deduplica per hash dei campi fiscali.
- Le colonne fiscalmente obbligatorie sono validate all'apertura di OGNI file:
  una sezione presente ma senza le colonne chiave genera un errore esplicito
  (l'utente deve attivare la colonna nella Flex Query), invece di produrre
  importi a zero in modo opaco.
- Gli importi restano in valuta originale; ``fxRateToBase`` di IBKR è conservato
  solo come reference (non è fiscalmente valido).
"""

from __future__ import annotations

import glob
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from ..money import dec
from ..warnings import WarningCollector
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


# Colonne fiscalmente obbligatorie per sezione: se la sezione è presente ma una
# riga qualsiasi non ha uno di questi attributi, il file non è utilizzabile
# (importi mancanti verrebbero altrimenti trattati come zero in modo opaco).
REQUIRED_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "Trade": ("quantity", "tradePrice", "proceeds", "ibCommission", "taxes",
              "currency", "tradeDate"),
    "CashTransaction": ("amount", "type", "dateTime", "currency"),
    "OpenPosition": ("position", "positionValue", "markPrice", "reportDate"),
}


def _parse_date(
    value: Optional[str],
    *,
    context: str = "",
    warnings: Optional[WarningCollector] = None,
) -> Optional[date]:
    """Interpreta i formati data IBKR: ``yyyyMMdd``, ``yyyy-MM-dd``,
    con eventuale ``;HHmmss`` o spazio-orario.

    Un valore NON vuoto ma non interpretabile genera un warning
    ``DATA_IMPVERSABILE`` (con valore e contesto) invece di un None muto.
    """
    if not value:
        return None
    original = value
    v = value.strip()
    if not v:
        return None
    # Rimuove la parte oraria dopo ';' o spazio.
    for sep in (";", " "):
        if sep in v:
            v = v.split(sep, 1)[0]
    v = v.replace("-", "").replace("/", "")
    parsed: Optional[date] = None
    if len(v) >= 8 and v[:8].isdigit():
        try:
            parsed = datetime.strptime(v[:8], "%Y%m%d").date()
        except ValueError:
            parsed = None
    if parsed is None and warnings is not None:
        warnings.warn(
            "DATA_IMPVERSABILE",
            f"Data non interpretabile {original!r}"
            + (f" ({context})" if context else "")
            + ": la riga viene importata senza data, verificare il file.",
        )
    return parsed


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


def _validate_required_columns(root: ET.Element, path: str) -> None:
    """Verifica che le sezioni presenti abbiano le colonne fiscalmente
    obbligatorie in OGNI riga; altrimenti errore esplicito."""
    for tag, required in REQUIRED_COLUMNS.items():
        for el in _iter(root, tag):
            a = el.attrib
            missing = [c for c in required if c not in a]
            if not missing:
                continue
            row_desc = a.get("symbol") or a.get("description") or a.get("currency") or ""
            raise FlexParseError(
                f"{path}: sezione <{tag}> senza colonne obbligatorie "
                f"{', '.join(missing)}"
                + (f" (riga {row_desc})" if row_desc else "")
                + f". Attiva le colonne {', '.join(missing)} per la sezione "
                f"'{tag}' nella Flex Query di Interactive Brokers "
                "(Activity > Flex Query > sezioni/colonne) e riesporta il file."
            )


def _parse_trade(el: ET.Element, warnings: WarningCollector) -> Optional[Trade]:
    a = el.attrib
    tx_type = a.get("transactionType", "")
    buy_sell = a.get("buySell", "")
    symbol = a.get("symbol", "?")
    when_raw = a.get("tradeDate") or a.get("dateTime") or ""

    # Cancellazioni: fuori dal LIFO (come l'originale) MA contate e segnalate,
    # perché una cancellazione senza la controparte originale falserebbe il
    # calcolo se passasse inosservata.
    if "cancel" in tx_type.lower() or "(ca." in buy_sell.lower():
        warnings.critical(
            "TRADE_CANCELLED",
            f"Operazione annullata esclusa dal calcolo: {symbol} del {when_raw} "
            f"(transactionType={tx_type!r}, buySell={buy_sell!r}). Verificare che "
            "anche l'esecuzione originale sia stata stornata da IBKR.",
        )
        return None

    # buySell: accetta 'BUY'/'SELL' con suffissi parentetici (es. 'SELL (Short)').
    base_bs = buy_sell.split("(", 1)[0].strip().upper()
    if base_bs not in {"BUY", "SELL"}:
        warnings.critical(
            "BUY_SELL_SCONOSCIUTO",
            f"buySell={buy_sell!r} non riconosciuto per {symbol} del {when_raw}: "
            "riga esclusa dal calcolo LIFO. Classificarla manualmente.",
        )
        return None

    return Trade(
        instrument=_instrument(a),
        trade_id=a.get("tradeID", ""),
        transaction_id=a.get("transactionID", "") or a.get("ibExecID", ""),
        trade_date=_parse_date(
            a.get("tradeDate") or a.get("dateTime"),
            context=f"Trade {symbol} tradeDate",
            warnings=warnings,
        ),
        settle_date=_parse_date(
            a.get("settleDateTarget") or a.get("settleDate"),
            context=f"Trade {symbol} settleDate",
            warnings=warnings,
        ),
        buy_sell=base_bs,
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


def _parse_cash_tx(el: ET.Element, warnings: WarningCollector) -> Optional[CashTransaction]:
    a = el.attrib
    tx_type = a.get("type", "")
    if not tx_type:
        return None
    inst = _instrument(a) if a.get("symbol") or a.get("conid") else None
    return CashTransaction(
        instrument=inst,
        transaction_id=a.get("transactionID", ""),
        tx_type=tx_type,
        when=_parse_date(
            a.get("dateTime") or a.get("settleDate") or a.get("reportDate"),
            context=f"CashTransaction {tx_type} dateTime",
            warnings=warnings,
        ),
        amount=dec(a.get("amount")),
        currency=a.get("currency", ""),
        description=a.get("description", ""),
        fx_rate_to_base=dec(a.get("fxRateToBase")),
        raw=dict(a),
    )


def _parse_open_position(el: ET.Element, warnings: WarningCollector) -> Optional[OpenPosition]:
    a = el.attrib
    # Evita di duplicare i livelli SUMMARY+LOT: si tiene solo LOT se presente,
    # altrimenti SUMMARY. La deduplica fine avviene a valle; qui prendiamo tutto
    # e filtriamo per levelOfDetail nel builder.
    symbol = a.get("symbol", "?")
    return OpenPosition(
        instrument=_instrument(a),
        report_date=_parse_date(
            a.get("reportDate"),
            context=f"OpenPosition {symbol} reportDate",
            warnings=warnings,
        ),
        quantity=dec(a.get("position")),
        mark_price=dec(a.get("markPrice")),
        position_value=dec(a.get("positionValue")),
        cost_basis_money=dec(a.get("costBasisMoney")),
        currency=a.get("currency", ""),
        side=a.get("side", ""),
        open_datetime=_parse_date(
            a.get("openDateTime"),
            context=f"OpenPosition {symbol} openDateTime",
            warnings=warnings,
        ),
        raw=dict(a),
    )


def _parse_cash_report(el: ET.Element, warnings: WarningCollector) -> Optional[CashReportRow]:
    a = el.attrib
    cur = a.get("currency", "")
    # Le righe aggregate "BASE_SUMMARY" non servono: si lavora per valuta.
    if cur in {"", "BASE_SUMMARY"}:
        return None
    return CashReportRow(
        currency=cur,
        from_date=_parse_date(a.get("fromDate"), context=f"CashReport {cur} fromDate", warnings=warnings),
        to_date=_parse_date(a.get("toDate"), context=f"CashReport {cur} toDate", warnings=warnings),
        starting_cash=dec(a.get("startingCash")),
        ending_cash=dec(a.get("endingCash")),
        ending_settled_cash=dec(a.get("endingSettledCash", a.get("endingCash"))),
        raw=dict(a),
    )


def _parse_corporate_action(el: ET.Element, warnings: WarningCollector) -> Optional[CorporateAction]:
    a = el.attrib
    return CorporateAction(
        instrument=_instrument(a),
        transaction_id=a.get("transactionID", ""),
        when=_parse_date(
            a.get("dateTime") or a.get("reportDate"),
            context=f"CorporateAction {a.get('symbol', '?')} dateTime",
            warnings=warnings,
        ),
        ca_type=a.get("type", ""),
        description=a.get("description", ""),
        quantity=dec(a.get("quantity")),
        value=dec(a.get("value")),
        currency=a.get("currency", ""),
        raw=dict(a),
    )


def parse_file(
    path: str, warnings: Optional[WarningCollector] = None
) -> Statement:
    """Parsa un singolo file Flex XML in uno ``Statement``.

    ``warnings`` (opzionale) raccoglie i rilievi di parsing (ID mancanti,
    cancellazioni, date non interpretabili, buySell sconosciuti). Le colonne
    obbligatorie mancanti generano invece ``FlexParseError``.
    """
    if warnings is None:
        warnings = WarningCollector()
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise FlexParseError(f"XML non valido in {path}: {exc}") from exc
    root = tree.getroot()

    # Le sezioni presenti devono avere le colonne fiscalmente obbligatorie.
    _validate_required_columns(root, path)

    stmt = Statement()

    # Metadati dal primo FlexStatement.
    fs = root.find(".//FlexStatement")
    if fs is not None:
        stmt.account_id = fs.attrib.get("accountId", "")
        stmt.from_date = _parse_date(fs.attrib.get("fromDate"), context="FlexStatement fromDate", warnings=warnings)
        stmt.to_date = _parse_date(fs.attrib.get("toDate"), context="FlexStatement toDate", warnings=warnings)
    # Base currency: talvolta su AccountInformation.
    ai = root.find(".//AccountInformation")
    if ai is not None:
        stmt.base_currency = ai.attrib.get("currency", "")

    for el in _iter(root, "Trade"):
        t = _parse_trade(el, warnings)
        if t:
            stmt.trades.append(t)
    for el in _iter(root, "CashTransaction"):
        c = _parse_cash_tx(el, warnings)
        if c:
            stmt.cash_transactions.append(c)
    for el in _iter(root, "OpenPosition"):
        p = _parse_open_position(el, warnings)
        if p:
            stmt.open_positions.append(p)
    for el in _iter(root, "CashReportCurrency"):
        r = _parse_cash_report(el, warnings)
        if r:
            stmt.cash_report.append(r)
    for el in _iter(root, "CorporateAction"):
        ca = _parse_corporate_action(el, warnings)
        if ca:
            stmt.corporate_actions.append(ca)

    # ID opzionali: senza transactionID/tradeID la dedup per ID non funziona e
    # file sovrapposti rischiano doppi conteggi -> warning CRITICAL + hash.
    missing = {
        "Trade": sum(1 for t in stmt.trades if not (t.transaction_id or t.trade_id)),
        "CashTransaction": sum(
            1 for c in stmt.cash_transactions if not c.transaction_id
        ),
        "CorporateAction": sum(
            1 for c in stmt.corporate_actions if not c.transaction_id
        ),
    }
    for section, n in missing.items():
        if n:
            warnings.critical(
                "IDS_MANCANTI",
                f"{path}: {n} righe {section} senza transactionID/tradeID. "
                "La dedup avverrà per hash dei campi fiscali: RISCHIO DOPPIO "
                "CONTEGGIO se due righe distinte risultano identiche o se i file "
                "si sovrappongono parzialmente. Attiva le colonne transactionID/"
                "tradeID nella Flex Query per una dedup affidabile.",
            )

    return stmt


# --------------------------------------------------------------------------- #
# Deduplica
# --------------------------------------------------------------------------- #

def _trade_fiscal_fields(t: Trade) -> Tuple[Tuple[str, object], ...]:
    return (
        ("instrument", t.instrument.key()),
        ("trade_date", t.trade_date),
        ("buy_sell", t.buy_sell),
        ("quantity", t.quantity),
        ("price", t.price),
        ("proceeds", t.proceeds),
        ("commission", t.commission),
        ("taxes", t.taxes),
        ("currency", t.currency),
    )


def _cash_fiscal_fields(c: CashTransaction) -> Tuple[Tuple[str, object], ...]:
    return (
        ("instrument", c.instrument.key() if c.instrument else ""),
        ("type", c.tx_type),
        ("when", c.when),
        ("amount", c.amount),
        ("currency", c.currency),
        ("description", c.description),
    )


def _cash_report_fiscal_fields(r: CashReportRow) -> Tuple[Tuple[str, object], ...]:
    return (
        ("currency", r.currency),
        ("from_date", r.from_date),
        ("to_date", r.to_date),
        ("starting_cash", r.starting_cash),
        ("ending_cash", r.ending_cash),
        ("ending_settled_cash", r.ending_settled_cash),
    )


def _ca_fiscal_fields(c: CorporateAction) -> Tuple[Tuple[str, object], ...]:
    return (
        ("instrument", c.instrument.key()),
        ("type", c.ca_type),
        ("when", c.when),
        ("quantity", c.quantity),
        ("value", c.value),
        ("currency", c.currency),
        ("description", c.description),
    )


def _dedup_events(
    items: List,
    id_getter,
    fields_getter,
    kind: str,
    warnings: WarningCollector,
) -> List:
    """Deduplica per ID; in assenza di ID deduplica per hash dei campi fiscali.

    Se due righe collidono sullo stesso ID ma differiscono nei campi fiscali,
    emette ``DUP_DISCORDANTE`` (CRITICAL) con i valori a confronto: nessuno
    scarto cieco.
    """
    seen_ids: Dict[str, object] = {}
    seen_hashes = set()
    out = []
    for it in items:
        key = id_getter(it)
        content = tuple((k, str(v)) for k, v in fields_getter(it))
        if key:
            prev = seen_ids.get(key)
            if prev is not None:
                prev_content = tuple((k, str(v)) for k, v in fields_getter(prev))
                if prev_content != content:
                    diff = "; ".join(
                        f"{k}: {v1!r} vs {v2!r}"
                        for (k, v1), (_, v2) in zip(prev_content, content)
                        if v1 != v2
                    )
                    warnings.critical(
                        "DUP_DISCORDANTE",
                        f"{kind}: ID {key!r} compare in più file con valori "
                        f"diversi ({diff}). Mantenuta la prima occorrenza: "
                        "verificare manualmente quale sia corretta.",
                    )
                continue
            seen_ids[key] = it
            out.append(it)
        else:
            if content in seen_hashes:
                continue
            seen_hashes.add(content)
            out.append(it)
    return out


def load(
    paths: List[str], warnings: Optional[WarningCollector] = None
) -> Statement:
    """Carica e unisce più file Flex (supporta glob), deduplicando gli eventi.

    ``paths`` può contenere pattern glob (es. ``ib_*.xml``). ``warnings``
    (opzionale) raccoglie i rilievi di parsing e dedup.
    """
    if warnings is None:
        warnings = WarningCollector()
    expanded: List[str] = []
    for p in paths:
        matches = sorted(glob.glob(p))
        expanded.extend(matches if matches else [p])
    if not expanded:
        raise FlexParseError("Nessun file di input trovato.")

    merged = Statement()
    for path in expanded:
        merged.merge(parse_file(path, warnings))

    # Deduplica: i file annuali possono sovrapporsi ai bordi. Senza ID si ricade
    # sull'hash dei campi fiscali (già segnalato con IDS_MANCANTI in parse_file).
    merged.trades = _dedup_events(
        merged.trades,
        lambda t: t.transaction_id or t.trade_id,
        _trade_fiscal_fields,
        "Trade",
        warnings,
    )
    merged.cash_transactions = _dedup_events(
        merged.cash_transactions,
        lambda c: c.transaction_id,
        _cash_fiscal_fields,
        "CashTransaction",
        warnings,
    )
    merged.corporate_actions = _dedup_events(
        merged.corporate_actions,
        lambda c: c.transaction_id,
        _ca_fiscal_fields,
        "CorporateAction",
        warnings,
    )
    # Cash report: file sovrapposti ripetono le stesse righe di saldo per valuta;
    # senza dedup la liquidità (e quindi l'IVAFE) raddoppierebbe.
    merged.cash_report = _dedup_events(
        merged.cash_report,
        lambda r: "",
        _cash_report_fiscal_fields,
        "CashReportCurrency",
        warnings,
    )
    # Open positions: si tengono le righe LOT se disponibili, evitando di sommare
    # anche il livello SUMMARY per lo stesso strumento/data; le righe identiche
    # ripetute in più file vengono deduplicate (IVAFE non raddoppia).
    merged.open_positions = _dedup_open_positions(merged.open_positions, warnings)
    return merged


def _dedup_open_positions(
    positions: List[OpenPosition], warnings: WarningCollector
) -> List[OpenPosition]:
    """Dedup posizioni aperte.

    1. Se per (strumento, data) esistono righe LOT, scarta la riga SUMMARY
       (logica intra-file preesistente).
    2. Deduplica cross-file per (strumento, report_date, quantity,
       positionValue, openDateTime): la stessa posizione ripetuta in due file
       non deve raddoppiare l'IVAFE. Se la tupla coincide ma markPrice o
       costBasis differiscono, emette ``DUP_DISCORDANTE``.
    """
    by_key: Dict[tuple, List[OpenPosition]] = {}
    for p in positions:
        key = (p.instrument.key(), p.report_date)
        by_key.setdefault(key, []).append(p)

    filtered: List[OpenPosition] = []
    for key, group in by_key.items():
        levels = {(pos.raw.get("levelOfDetail") or "").upper() for pos in group}
        if "LOT" in levels and "SUMMARY" in levels:
            filtered.extend(
                p
                for p in group
                if (p.raw.get("levelOfDetail") or "").upper() == "LOT"
            )
        else:
            filtered.extend(group)

    seen: Dict[tuple, OpenPosition] = {}
    out: List[OpenPosition] = []
    for p in filtered:
        dup_key = (
            p.instrument.key(),
            p.report_date,
            p.quantity,
            p.position_value,
            p.open_datetime,
        )
        prev = seen.get(dup_key)
        if prev is None:
            seen[dup_key] = p
            out.append(p)
            continue
        if (prev.mark_price, prev.cost_basis_money) != (p.mark_price, p.cost_basis_money):
            warnings.critical(
                "DUP_DISCORDANTE",
                f"OpenPosition {p.instrument.symbol} del {p.report_date} ripetuta "
                f"con valori diversi (markPrice {prev.mark_price} vs {p.mark_price}, "
                f"costBasis {prev.cost_basis_money} vs {p.cost_basis_money}). "
                "Mantenuta la prima occorrenza: verificare manualmente.",
            )
    return out
