"""Configurazione dei trattamenti fiscali (con default prudenti).

Molte scelte riguardano casi normativamente incerti: i default seguono la
posizione più difendibile/prudente e ogni scelta genera un warning nel report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Set


@dataclass
class FiscoConfig:
    tax_year: int

    # Aliquote
    aliquota_sostitutiva: Decimal = Decimal("0.26")   # RT e RM (26%)
    ivafe_rate: Decimal = Decimal("0.002")            # 0,2%
    ivafe_rate_blacklist: Decimal = Decimal("0.004")  # 0,4% paesi black list

    # Dividendi esteri: base imponibile.
    #   "lordo" = 26% sul dividendo lordo (posizione AdE vigente, default)
    #   "netto" = 26% sul netto frontiera (contestata, più favorevole)
    frontiera: str = "lordo"

    # IVAFE su strumenti a trattamento incerto: default solo monitoraggio.
    ivafe_cfd: bool = False
    ivafe_otc: bool = False

    # Dividend adjustment su CFD: "RT" (redditi diversi, default) | "RM".
    cfd_dividend_adjustment: str = "RT"

    # Payment In Lieu of Dividends (titoli prestati): "RM" (default) | "RT".
    pil_treatment: str = "RM"

    # Dati del contribuente / conto
    account_country: str = "IE"           # codice stato estero per il Quadro RW
    ownership_pct: Decimal = Decimal("100")

    # Base per il pro-rata IVAFE e per i giorni di detenzione.
    year_days_basis: int = 365

    # Paesi a fiscalità privilegiata (black list) — IE/US NON inclusi.
    blacklist_countries: Set[str] = field(default_factory=set)

    def is_blacklist(self, country: str) -> bool:
        return (country or "").upper() in self.blacklist_countries
