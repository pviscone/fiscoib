"""Costruttori sintetici di eventi per i test."""

from datetime import date
from decimal import Decimal

from fiscoib.parsing.models import Instrument, Trade, CashTransaction, OpenPosition


def stock(symbol="AAPL", currency="USD", exchange="NASDAQ", conid=None, isin="US0378331005"):
    return Instrument(
        conid=conid or symbol,
        symbol=symbol,
        description=symbol,
        asset_category="STK",
        isin=isin,
        listing_exchange=exchange,
        currency=currency,
    )


def cfd(symbol="AAPL-CFD", currency="USD", conid=None):
    return Instrument(
        conid=conid or symbol,
        symbol=symbol,
        description=symbol,
        asset_category="CFD",
        currency=currency,
    )


def trade(inst, when, buy_sell, qty, price, commission="0", currency="USD", tid=None):
    d = when if isinstance(when, date) else date.fromisoformat(when)
    return Trade(
        instrument=inst,
        trade_id=tid or f"{inst.symbol}-{d}-{buy_sell}-{qty}",
        transaction_id=tid or f"{inst.symbol}-{d}-{buy_sell}-{qty}",
        trade_date=d,
        settle_date=d,
        buy_sell=buy_sell,
        open_close="",
        quantity=Decimal(str(qty)),
        price=Decimal(str(price)),
        proceeds=Decimal("0"),
        commission=Decimal(str(commission)),
        commission_currency=currency,
        taxes=Decimal("0"),
        currency=currency,
    )


def cash_tx(inst, when, tx_type, amount, currency="USD", tid=None):
    d = when if isinstance(when, date) else date.fromisoformat(when)
    return CashTransaction(
        instrument=inst,
        transaction_id=tid or f"{tx_type}-{d}-{amount}",
        tx_type=tx_type,
        when=d,
        amount=Decimal(str(amount)),
        currency=currency,
    )


def open_position(inst, when, qty, mark_price, currency="USD"):
    d = when if isinstance(when, date) else date.fromisoformat(when)
    q = Decimal(str(qty))
    mp = Decimal(str(mark_price))
    return OpenPosition(
        instrument=inst,
        report_date=d,
        quantity=q,
        mark_price=mp,
        position_value=q * mp,
        cost_basis_money=Decimal("0"),
        currency=currency,
    )
