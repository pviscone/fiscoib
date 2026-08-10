"""Utilità per importi monetari e arrotondamenti fiscali.

Regola generale: si usa SEMPRE ``decimal.Decimal`` per gli importi, mai ``float``,
per evitare errori di arrotondamento che, moltiplicati su molte operazioni,
falserebbero i totali dichiarati.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Optional, Union

Number = Union[str, int, float, Decimal, None]

# Precisione interna di lavoro (centesimi di valuta con margine).
CENT = Decimal("0.01")
FOUR = Decimal("0.0001")
SIX = Decimal("0.000001")

ZERO = Decimal("0")


def dec(value: Number, default: Decimal = ZERO) -> Decimal:
    """Converte in Decimal in modo sicuro.

    - ``None`` o stringa vuota -> ``default``.
    - I ``float`` vengono passati via ``str`` per evitare la rappresentazione
      binaria imprecisa (es. 0.1).
    """
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, int):
        return Decimal(value)
    s = str(value).strip().replace(",", "")
    if s == "" or s == "--":
        return default
    try:
        return Decimal(s)
    except InvalidOperation:
        return default


def q2(value: Number) -> Decimal:
    """Arrotonda a 2 decimali (centesimi) con arrotondamento commerciale."""
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def q4(value: Number) -> Decimal:
    """Arrotonda a 4 decimali (usato per i tassi di cambio)."""
    return dec(value).quantize(FOUR, rounding=ROUND_HALF_UP)


def q6(value: Number) -> Decimal:
    """Arrotonda a 6 decimali (tassi di cambio ad alta precisione)."""
    return dec(value).quantize(SIX, rounding=ROUND_HALF_UP)


def euro_int(value: Number) -> int:
    """Arrotonda all'euro intero.

    Il modello Redditi PF richiede l'esposizione dei valori del Quadro RW
    arrotondati all'unità di euro.
    """
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
