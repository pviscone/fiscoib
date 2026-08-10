"""Motore dei lotti con matching LIFO (art. 67 c.1-bis TUIR).

L'Italia impone il metodo LIFO: alla vendita si considerano cedute per prime le
quote acquisite in data più recente. IBKR calcola invece in FIFO, quindi i suoi
``fifoPnlRealized`` NON sono utilizzabili e qui si ricostruisce tutto dai trade
grezzi.

Il motore gestisce sia posizioni long sia short (le vendite allo scoperto aprono
lotti negativi). Elabora i trade in ordine cronologico, intercalando le corporate
action (split/raggruppamenti) che rettificano i lotti aperti.

Output: una lista di ``Closure`` (chiusure realizzate, in valuta originale), che il
motore RT converte in EUR e trasforma in plus/minusvalenze.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from ..money import ZERO, dec
from ..parsing.models import CorporateAction, Instrument, Trade
from ..warnings import WarningCollector


@dataclass
class Lot:
    """Tranche aperta di una posizione.

    ``qty`` è con segno: positivo=long, negativo=short. ``unit_price`` e
    ``unit_commission`` sono per singola unità, in valuta dello strumento.
    """

    instrument: Instrument
    open_date: date
    qty: Decimal
    unit_price: Decimal
    unit_commission: Decimal  # onere accessorio di acquisto/apertura per unità
    currency: str

    @property
    def is_long(self) -> bool:
        return self.qty > 0


@dataclass
class Closure:
    """Una chiusura realizzata (match tra apertura e chiusura)."""

    instrument: Instrument
    currency: str
    is_long: bool
    qty: Decimal                 # quantità chiusa (positiva)
    open_date: date
    close_date: date
    open_unit_price: Decimal
    open_unit_commission: Decimal
    close_unit_price: Decimal
    close_unit_commission: Decimal

    # Valori aggregati in valuta (comodi per il report)
    @property
    def open_amount(self) -> Decimal:
        return self.qty * self.open_unit_price

    @property
    def close_amount(self) -> Decimal:
        return self.qty * self.close_unit_price

    @property
    def open_commission(self) -> Decimal:
        return self.qty * self.open_unit_commission

    @property
    def close_commission(self) -> Decimal:
        return self.qty * self.close_unit_commission


class LotBook:
    """Registro dei lotti aperti per ogni strumento con matching LIFO."""

    def __init__(self, warnings: Optional[WarningCollector] = None):
        # stack per strumento: l'ultimo elemento è il più recente (LIFO)
        self._lots: Dict[str, List[Lot]] = {}
        self.closures: List[Closure] = []
        self.warnings = warnings or WarningCollector()

    # ------------------------------------------------------------------ #
    def open_lots(self, key: str) -> List[Lot]:
        return self._lots.get(key, [])

    def _unit_commission(self, trade: Trade) -> Decimal:
        if trade.quantity == 0:
            return ZERO
        # Commissioni + imposte di transazione come oneri accessori.
        total = trade.abs_commission + trade.abs_taxes
        return total / trade.quantity

    # ------------------------------------------------------------------ #
    def process_trade(self, trade: Trade) -> None:
        key = trade.instrument.key()
        stack = self._lots.setdefault(key, [])
        remaining = trade.quantity
        incoming_sign = Decimal("1") if trade.is_buy else Decimal("-1")
        unit_price = trade.price
        unit_comm = self._unit_commission(trade)

        # 1) Chiude i lotti di segno opposto (LIFO: dal più recente).
        while remaining > 0 and stack and (stack[-1].qty > 0) == (incoming_sign < 0):
            lot = stack[-1]
            lot_qty_abs = abs(lot.qty)
            matched = min(remaining, lot_qty_abs)

            self.closures.append(
                Closure(
                    instrument=lot.instrument,
                    currency=lot.currency,
                    is_long=lot.is_long,
                    qty=matched,
                    open_date=lot.open_date,
                    close_date=trade.trade_date,
                    open_unit_price=lot.unit_price,
                    open_unit_commission=lot.unit_commission,
                    close_unit_price=unit_price,
                    close_unit_commission=unit_comm,
                )
            )

            # Riduce il lotto (mantiene il segno).
            if lot.is_long:
                lot.qty -= matched
            else:
                lot.qty += matched
            if lot.qty == 0:
                stack.pop()
            remaining -= matched

        # 2) La quantità residua apre un nuovo lotto nel nuovo verso.
        if remaining > 0:
            stack.append(
                Lot(
                    instrument=trade.instrument,
                    open_date=trade.trade_date,
                    qty=remaining * incoming_sign,
                    unit_price=unit_price,
                    unit_commission=unit_comm,
                    currency=trade.currency,
                )
            )

    # ------------------------------------------------------------------ #
    def process_corporate_action(self, ca: CorporateAction) -> None:
        """Rettifica i lotti aperti per split/raggruppamenti.

        Gestione precisa solo per variazioni di quantità che preservano il valore
        (forward split FS, reverse split RS, stock dividend SD): si scala la
        quantità dei lotti aperti e, in modo inverso, prezzo e commissione unitari
        così da lasciare invariato il costo complessivo. Per gli altri tipi
        (merger, symbol change, spin-off) si emette un warning: vanno verificati a
        mano perché possono cambiare l'identità dello strumento.
        """
        key = ca.instrument.key()
        stack = self._lots.get(key)
        if not stack:
            return

        if ca.ca_type in {"FS", "RS", "SD"} and ca.quantity != 0:
            total_qty = sum(abs(l.qty) for l in stack)
            if total_qty == 0:
                return
            new_total = total_qty + abs(ca.quantity)
            if new_total <= 0:
                return
            factor = new_total / total_qty  # >1 forward split, <1 reverse
            for lot in stack:
                lot.qty = lot.qty * factor
                lot.unit_price = lot.unit_price / factor
                lot.unit_commission = lot.unit_commission / factor
        else:
            self.warnings.warn(
                "CORP_ACTION",
                f"Operazione societaria '{ca.ca_type}' su {ca.instrument.symbol} "
                f"del {ca.when}: non gestita automaticamente, verificare manualmente "
                f"l'impatto su costo e quantità dei lotti.",
            )


def build_closures(
    trades: List[Trade],
    corporate_actions: List[CorporateAction],
    warnings: Optional[WarningCollector] = None,
) -> Tuple[List[Closure], LotBook]:
    """Processa trade e corporate action in ordine cronologico.

    A parità di data, le corporate action vengono applicate prima dei trade
    (di norma diventano efficaci a mercato aperto).
    """
    book = LotBook(warnings)

    events: List[Tuple[date, int, object]] = []
    for ca in corporate_actions:
        if ca.when:
            events.append((ca.when, 0, ca))
    for t in trades:
        if t.trade_date:
            events.append((t.trade_date, 1, t))

    events.sort(key=lambda e: (e[0], e[1]))

    for _, kind, obj in events:
        if kind == 0:
            book.process_corporate_action(obj)  # type: ignore[arg-type]
        else:
            book.process_trade(obj)  # type: ignore[arg-type]

    # Chiusure senza lotto di carico (storico incompleto) si manifestano come
    # vendite che aprono lotti short "spurii": segnala se restano short non
    # spiegati su titoli azionari (non CFD).
    return book.closures, book
