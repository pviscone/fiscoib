"""Cambi medi mensili UFFICIALI dell'Agenzia delle Entrate (override).

Ai fini del Quadro RW/IVAFE la fonte fiscalmente corretta è il provvedimento
mensile dell'Agenzia delle Entrate (non la media Banca d'Italia, che può differire
di poco). Qui si raccolgono i valori ufficiali noti; l'utente può aggiungerne altri
via file JSON (``RatesProvider.load_overrides_file``).

Convenzione: 1 EUR = valore indicato in valuta estera.

Fonte dicembre 2024: Provvedimento AdE prot. 25916/2025 del 31/01/2025.
"""

from decimal import Decimal
from typing import Dict, Tuple

# chiave: (valuta, anno, mese) -> tasso
ADE_MONTHLY: Dict[Tuple[str, int, int], Decimal] = {
    ("USD", 2024, 12): Decimal("1.0479"),
    ("GBP", 2024, 12): Decimal("0.82804"),
    ("CHF", 2024, 12): Decimal("0.9339"),
    ("JPY", 2024, 12): Decimal("161.0835"),
    ("CAD", 2024, 12): Decimal("1.4915"),
    ("AUD", 2024, 12): Decimal("1.6529"),
}


def builtin_overrides() -> Dict[Tuple[str, int, int], Decimal]:
    """Ritorna una copia della tabella built-in."""
    return dict(ADE_MONTHLY)
