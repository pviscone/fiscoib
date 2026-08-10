"""Motore redditi di capitale — Quadro RM, Sez. II-A (26%).

Gestisce:
- Dividendi esteri (rigo RM31, codice reddito H). Base imponibile secondo
  ``config.frontiera``: "lordo" (default, posizione AdE) o "netto" frontiera.
  Il credito d'imposta estero NON è scomputabile in dichiarazione ordinaria: si
  espone solo come informazione (eventuale istanza di rimborso).
- Interessi attivi su liquidità (codice G) e cedole (codice I) → RM31/RM32.
- Interessi passivi/margin → NON deducibili: ignorati con nota.
- Payment In Lieu of Dividends (titoli prestati) → ``config.pil_treatment``.
- Dividend adjustment su CFD → ``config.cfd_dividend_adjustment`` (default RT,
  restituiti come componenti c-quater da sommare al Quadro RT).

I dividendi/interessi (redditi di capitale) NON si compensano con le minusvalenze.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from ..config import FiscoConfig
from ..money import ZERO, dec, q2
from ..fx.rates import RatesProvider
from ..parsing.models import CashTransaction
from ..warnings import WarningCollector

DIVIDEND_TYPES = {"Dividends", "Dividend"}
PIL_TYPES = {"Payment In Lieu Of Dividends", "Payment In Lieu of Dividends"}
WHT_TYPES = {"Withholding Tax"}
INTEREST_RECEIVED = {"Broker Interest Received", "Bond Interest Received", "Credit Interest"}
INTEREST_PAID = {"Broker Interest Paid", "Bond Interest Paid", "Debit Interest"}


def _country_from(ct: CashTransaction) -> str:
    inst = ct.instrument
    if inst and inst.isin and len(inst.isin) >= 2 and inst.isin[:2].isalpha():
        return inst.isin[:2].upper()
    return ""


@dataclass
class DividendRow:
    symbol: str
    country: str
    pay_date: date
    currency: str
    gross_ccy: Decimal
    wht_ccy: Decimal
    rate: Decimal
    gross_eur: Decimal
    wht_eur: Decimal
    base_imponibile_eur: Decimal
    imposta_eur: Decimal
    credito_teorico_eur: Decimal
    codice_reddito: str = "H"


@dataclass
class InterestRow:
    description: str
    country: str
    when: date
    currency: str
    amount_ccy: Decimal
    rate: Decimal
    base_eur: Decimal
    imposta_eur: Decimal
    codice_reddito: str = "G"


@dataclass
class RMResult:
    tax_year: int
    dividends: List[DividendRow] = field(default_factory=list)
    interests: List[InterestRow] = field(default_factory=list)

    tot_base_dividendi: Decimal = ZERO
    tot_imposta_dividendi: Decimal = ZERO
    tot_base_interessi: Decimal = ZERO
    tot_imposta_interessi: Decimal = ZERO
    tot_wht_estera_eur: Decimal = ZERO
    tot_credito_teorico_eur: Decimal = ZERO
    interessi_passivi_ignorati_eur: Decimal = ZERO

    # Componenti c-quater da sommare al Quadro RT (dividend adjustment CFD, PIL→RT)
    cquater_components: List[Tuple[str, Decimal, date]] = field(default_factory=list)

    @property
    def tot_imposta_rm(self) -> Decimal:
        return q2(self.tot_imposta_dividendi + self.tot_imposta_interessi)


def _group_key(ct: CashTransaction) -> Tuple[str, object]:
    inst = ct.instrument
    key = inst.key() if inst else (ct.description or "")
    return (key, ct.when)


def compute_rm(
    cash_txs: List[CashTransaction],
    rates: RatesProvider,
    config: FiscoConfig,
    warnings: Optional[WarningCollector] = None,
) -> RMResult:
    warnings = warnings or WarningCollector()
    res = RMResult(tax_year=config.tax_year)

    # Filtra sull'anno d'imposta (principio di cassa: pay date).
    txs = [c for c in cash_txs if c.when and c.when.year == config.tax_year]

    # --- Ritenute estere: aggregate per (strumento, data) ---
    wht_map: Dict[Tuple[str, object], Decimal] = {}
    for c in txs:
        if c.tx_type in WHT_TYPES:
            wht_map[_group_key(c)] = wht_map.get(_group_key(c), ZERO) + abs(c.amount)

    # --- Dividendi e PIL, aggregati per (strumento, data) ---
    div_groups: Dict[Tuple[str, object], List[CashTransaction]] = {}
    for c in txs:
        is_div = c.tx_type in DIVIDEND_TYPES
        is_pil = c.tx_type in PIL_TYPES
        if not (is_div or is_pil):
            continue

        inst = c.instrument
        is_cfd = bool(inst and inst.is_cfd)

        # Dividend adjustment su CFD.
        if is_cfd and (is_div or is_pil):
            if config.cfd_dividend_adjustment == "RT":
                res.cquater_components.append(
                    (f"CFD div.adj {inst.symbol}", q2(_to_eur(rates, c)), c.when)
                )
                warnings.info(
                    "CFD_DIVADJ",
                    f"Dividend adjustment CFD {inst.symbol} trattato come componente "
                    f"c-quater (Quadro RT).",
                )
            else:
                div_groups.setdefault(_group_key(c), []).append(c)
            continue

        # PIL da stock lending.
        if is_pil:
            if config.pil_treatment == "RT":
                res.cquater_components.append(
                    (f"PIL {inst.symbol if inst else ''}", q2(_to_eur(rates, c)), c.when)
                )
                continue
            warnings.info(
                "PIL",
                "Payment In Lieu of Dividends trattato come reddito di capitale "
                "(Quadro RM): classificazione non normata, verificare.",
            )

        div_groups.setdefault(_group_key(c), []).append(c)

    for key, group in div_groups.items():
        gross_ccy = sum((c.amount for c in group), ZERO)
        if gross_ccy <= 0:
            continue
        sample = group[0]
        currency = sample.currency
        pay_date = sample.when
        rate = rates.daily_rate(currency, pay_date)
        wht_ccy = wht_map.get(key, ZERO)

        gross_eur = dec(gross_ccy) / rate
        wht_eur = dec(wht_ccy) / rate

        if config.frontiera == "netto":
            base = gross_eur - wht_eur
        else:  # lordo (default)
            base = gross_eur

        imposta = base * config.aliquota_sostitutiva
        credito_teorico = min(wht_eur, imposta)

        res.dividends.append(
            DividendRow(
                symbol=sample.instrument.symbol if sample.instrument else "",
                country=_country_from(sample),
                pay_date=pay_date,
                currency=currency,
                gross_ccy=q2(gross_ccy),
                wht_ccy=q2(wht_ccy),
                rate=rate,
                gross_eur=q2(gross_eur),
                wht_eur=q2(wht_eur),
                base_imponibile_eur=q2(base),
                imposta_eur=q2(imposta),
                credito_teorico_eur=q2(credito_teorico),
            )
        )
        res.tot_base_dividendi += base
        res.tot_imposta_dividendi += imposta
        res.tot_wht_estera_eur += wht_eur
        res.tot_credito_teorico_eur += credito_teorico

    # --- Interessi ---
    for c in txs:
        if c.tx_type in INTEREST_RECEIVED and c.amount > 0:
            rate = rates.daily_rate(c.currency, c.when)
            base_eur = dec(c.amount) / rate
            imposta = base_eur * config.aliquota_sostitutiva
            code = "I" if "Bond" in c.tx_type else "G"
            res.interests.append(
                InterestRow(
                    description=c.description or c.tx_type,
                    country=_country_from(c) or config.account_country,
                    when=c.when,
                    currency=c.currency,
                    amount_ccy=q2(c.amount),
                    rate=rate,
                    base_eur=q2(base_eur),
                    imposta_eur=q2(imposta),
                    codice_reddito=code,
                )
            )
            res.tot_base_interessi += base_eur
            res.tot_imposta_interessi += imposta
        elif c.tx_type in INTEREST_PAID and c.amount < 0:
            rate = rates.daily_rate(c.currency, c.when)
            res.interessi_passivi_ignorati_eur += dec(-c.amount) / rate

    if res.interessi_passivi_ignorati_eur > 0:
        warnings.info(
            "INT_PASSIVI",
            f"Interessi passivi/margin per € {q2(res.interessi_passivi_ignorati_eur)} "
            f"NON deducibili per persona fisica: esclusi dal calcolo.",
        )

    # Arrotondamenti finali.
    res.tot_base_dividendi = q2(res.tot_base_dividendi)
    res.tot_imposta_dividendi = q2(res.tot_imposta_dividendi)
    res.tot_base_interessi = q2(res.tot_base_interessi)
    res.tot_imposta_interessi = q2(res.tot_imposta_interessi)
    res.tot_wht_estera_eur = q2(res.tot_wht_estera_eur)
    res.tot_credito_teorico_eur = q2(res.tot_credito_teorico_eur)
    res.interessi_passivi_ignorati_eur = q2(res.interessi_passivi_ignorati_eur)

    if config.frontiera == "lordo" and res.tot_wht_estera_eur > 0:
        warnings.warn(
            "FRONTIERA",
            f"Dividendi tassati al LORDO frontiera (posizione AdE). Ritenute estere "
            f"per € {res.tot_wht_estera_eur} non scomputate: credito teorico "
            f"€ {res.tot_credito_teorico_eur} recuperabile solo con istanza di "
            f"rimborso (esito incerto).",
        )

    return res


def _to_eur(rates: RatesProvider, c: CashTransaction) -> Decimal:
    rate = rates.daily_rate(c.currency, c.when)
    return dec(c.amount) / rate
