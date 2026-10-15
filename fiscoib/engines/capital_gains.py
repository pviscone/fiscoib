"""Motore plusvalenze/minusvalenze — Quadro RT, Sezione II-A (26%).

Azioni quotate, azioni OTC (art. 67 c-bis) e CFD (art. 67 c-quater) confluiscono
tutte nella stessa sezione e si compensano tra loro. La componente cambio è
incorporata: ogni gamba dell'operazione è convertita in EUR al cambio giornaliero
ufficiale della propria data.

QUOTE OICR/ETF esteri (``Instrument.is_fund``): i risultati positivi da cessione o
rimborso sono REDDITI DI CAPITALE (art. 44 c.1 lett. g TUIR): NON entrano in RT,
NON concorrono al saldo e NON si compensano con le minusvalenze; finiscono nel
campo ``oicr_gains`` del risultato (tassati al 26% come redditi di capitale, quadro
RM sezione II, lett. H). I risultati NEGATIVI da OICR restano invece redditi
diversi e seguono il normale trattamento RT (minusvalenze compensabili).

Convenzione RT21/RT22 usata:
- RT21 (corrispettivi) = corrispettivo lordo di vendita (per le posizioni long è la
  chiusura, per le short è l'apertura/vendita allo scoperto).
- RT22 (costi) = costo di acquisto + TUTTE le commissioni/oneri (apertura+chiusura).
Così ``plus = RT21 - RT22`` include correttamente le commissioni deducibili
(Interpello AdE 344/2020). Gli interessi passivi/margin NON sono deducibili e non
entrano qui.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Set

from ..config import FiscoConfig
from ..money import ZERO, dec, q2
from ..fx.rates import RatesProvider
from ..prorata import (
    CODE_PRORATA_ANNI_PARZIALI,
    CODE_PRORATA_MANCANTE,
    FundGovQuotas,
    effective_rate,
)
from ..warnings import WarningCollector
from .lots import Closure


@dataclass
class GainRow:
    """Dettaglio EUR di una singola chiusura (per il report riga-per-riga)."""

    symbol: str
    asset_category: str
    is_long: bool
    qty: Decimal
    currency: str
    open_date: object
    close_date: object
    corrispettivo_eur: Decimal
    costo_eur: Decimal
    commissioni_eur: Decimal
    plus_minus_eur: Decimal
    rate_open: Decimal
    rate_close: Decimal


@dataclass
class RTResult:
    tax_year: int
    rows: List[GainRow] = field(default_factory=list)

    rt21_corrispettivi: Decimal = ZERO
    rt22_costi: Decimal = ZERO
    rt23_differenza: Decimal = ZERO          # plus lorda (se positiva)
    minus_pregresse_usate: Decimal = ZERO    # RT (righi minusvalenze pregresse)
    rt26_imponibile: Decimal = ZERO
    rt27_imposta: Decimal = ZERO

    minus_anno: Decimal = ZERO               # minusvalenza dell'anno (se saldo < 0)
    minus_da_riportare: Dict[int, Decimal] = field(default_factory=dict)  # anno->residuo

    # Proventi da cessione di quote OICR/ETF esteri in positivo: redditi di
    # capitale (art. 44 c.1 lett. g TUIR), tassati al 26% SENZA compensazione
    # con le minusvalenze; con --fund-gov-quota l'aliquota è l'effettiva
    # pro-rata (26% - 13,5% x quota titoli di Stato white list del fondo).
    # Chiavi: symbol, data_chiusura, descrizione, qty, gain_eur, aliquota,
    # quota_gov, imposta_eur, lettera ('H'), country.
    oicr_gains: List[dict] = field(default_factory=list)
    oicr_imponibile: Decimal = ZERO   # somma dei gain OICR (base, quadro RM)
    oicr_imposta: Decimal = ZERO      # imposta OICR (somma dei q2 per-riga)

    @property
    def saldo_netto(self) -> Decimal:
        return self.rt21_corrispettivi - self.rt22_costi


def _rate(rates: RatesProvider, currency: str, when) -> Decimal:
    return rates.daily_rate(currency, when)


def compute_rt(
    closures: List[Closure],
    rates: RatesProvider,
    config: FiscoConfig,
    prior_losses: Optional[Dict[int, Decimal]] = None,
    extra_components: Optional[List] = None,
    warnings: Optional[WarningCollector] = None,
    fund_gov_quotas: Optional[FundGovQuotas] = None,
) -> RTResult:
    """Calcola il Quadro RT per l'anno d'imposta ``config.tax_year``.

    ``prior_losses``: minusvalenze pregresse riportabili, mappa anno_realizzo ->
    importo residuo. Sono utilizzabili nei 4 anni successivi a quello di realizzo.

    ``extra_components``: lista di ``(label, importo_eur, data)`` per componenti
    c-quater esterni (es. dividend adjustment CFD, PIL trattati come RT). Positivi
    aumentano i corrispettivi, negativi aumentano i costi.

    ``fund_gov_quotas``: quote medie di titoli di Stato white list per gli OICR
    -- applica l'aliquota effettiva pro-rata ai gain degli ETF (art. 2 c. 1-quater
    D.L. 138/2011). Fondi assenti dal file o file mancante: 26% pieno + warning
    (una volta per fondo).
    """
    warnings = warnings or WarningCollector()
    result = RTResult(tax_year=config.tax_year)

    # Fondi per cui il warning prorata è già stato emesso (una volta per fondo).
    seen_prorata: Set[str] = set()

    for c in closures:
        if not c.close_date or c.close_date.year != config.tax_year:
            continue

        rate_open = _rate(rates, c.currency, c.open_date)
        rate_close = _rate(rates, c.currency, c.close_date)

        open_amount_eur = dec(c.open_amount) / rate_open
        open_comm_eur = dec(c.open_commission) / rate_open
        close_amount_eur = dec(c.close_amount) / rate_close
        close_comm_eur = dec(c.close_commission) / rate_close

        if c.is_long:
            corrispettivo = close_amount_eur
            costo = open_amount_eur + open_comm_eur + close_comm_eur
        else:
            # Short: il corrispettivo è la vendita allo scoperto (apertura),
            # il costo è il riacquisto (chiusura).
            corrispettivo = open_amount_eur
            costo = close_amount_eur + open_comm_eur + close_comm_eur

        commissioni = open_comm_eur + close_comm_eur
        plus = corrispettivo - costo

        # OICR/ETF: il GAIN è reddito di capitale (art. 44 c.1 lett. g TUIR):
        # escluso da RT e dalle compensazioni. La LOSS resta reddito diverso.
        if c.instrument.is_fund and plus > 0:
            isin = c.instrument.isin or ""
            country = isin[:2].upper() if len(isin) >= 2 and isin[:2].isalpha() else ""

            # Pro-rata titoli di Stato white list (art. 2 c. 1-quater D.L.
            # 138/2011): periodo di possesso = [primo acquisto del lotto a costo
            # medio ponderato, vendita]; anni senza dato pesano 0 (prudente).
            aliquota = config.aliquota_sostitutiva
            quota_gov: Optional[Decimal] = None
            sym = c.instrument.symbol
            info = (
                fund_gov_quotas.average_quota(
                    (isin, sym, c.instrument.conid), c.open_date, c.close_date
                )
                if fund_gov_quotas
                else None
            )
            if info is not None:
                quota_gov = info.quota
                aliquota = effective_rate(config.aliquota_sostitutiva, info.quota)
                if info.missing_years and sym not in seen_prorata:
                    seen_prorata.add(sym)
                    warnings.warn(
                        CODE_PRORATA_ANNI_PARZIALI,
                        f"Dati prorata parziali per {sym}: anni {list(info.missing_years)} "
                        f"assenti dal file --fund-gov-quota, conteggiati con quota 0 "
                        f"(aliquota piena su quella frazione): controllare il dato del gestore.",
                    )
            elif sym not in seen_prorata:
                seen_prorata.add(sym)
                note = (
                    "il file --fund-gov-quota non contiene l'identificativo"
                    if fund_gov_quotas
                    else "manca il file --fund-gov-quota"
                )
                warnings.warn(
                    CODE_PRORATA_MANCANTE,
                    f"Plusvalenza su ETF/fondo {sym}: {note} se il fondo contiene titoli di "
                    f"Stato white list. Applicata l'aliquota piena 26% (scelta prudente): con "
                    f"--fund-gov-quota si applicherebbe il pro-rata al 12,5% sulla quota "
                    f"governativa (art. 2 c. 1-quater D.L. 138/2011).",
                )

            result.oicr_gains.append(
                {
                    "symbol": sym,
                    "data_chiusura": c.close_date,
                    "descrizione": c.instrument.description,
                    "qty": c.qty,
                    "gain_eur": q2(plus),
                    "quota_gov": quota_gov,
                    "aliquota": str(aliquota),
                    "imposta_eur": q2(plus * aliquota),
                    "lettera": "H",
                    "country": country,
                }
            )
            result.oicr_imponibile += plus
            result.oicr_imposta += q2(plus * aliquota)
            continue

        result.rows.append(
            GainRow(
                symbol=c.instrument.symbol,
                asset_category=c.instrument.asset_category,
                is_long=c.is_long,
                qty=c.qty,
                currency=c.currency,
                open_date=c.open_date,
                close_date=c.close_date,
                corrispettivo_eur=q2(corrispettivo),
                costo_eur=q2(costo),
                commissioni_eur=q2(commissioni),
                plus_minus_eur=q2(plus),
                rate_open=rate_open,
                rate_close=rate_close,
            )
        )
        result.rt21_corrispettivi += corrispettivo
        result.rt22_costi += costo

    # Componenti c-quater esterni (dividend adjustment CFD, PIL→RT).
    for label, amount_eur, when in (extra_components or []):
        if when and getattr(when, "year", None) != config.tax_year:
            continue
        amt = dec(amount_eur)
        if amt >= 0:
            result.rt21_corrispettivi += amt
        else:
            result.rt22_costi += -amt
        result.rows.append(
            GainRow(
                symbol=label,
                asset_category="CFD",
                is_long=amt >= 0,
                qty=ZERO,
                currency="EUR",
                open_date=when,
                close_date=when,
                corrispettivo_eur=q2(amt) if amt >= 0 else ZERO,
                costo_eur=ZERO if amt >= 0 else q2(-amt),
                commissioni_eur=ZERO,
                plus_minus_eur=q2(amt),
                rate_open=Decimal("1"),
                rate_close=Decimal("1"),
            )
        )

    # Arrotondamenti finali.
    result.rt21_corrispettivi = q2(result.rt21_corrispettivi)
    result.rt22_costi = q2(result.rt22_costi)
    result.oicr_imponibile = q2(result.oicr_imponibile)
    result.oicr_imposta = q2(result.oicr_imposta)
    saldo = result.rt21_corrispettivi - result.rt22_costi

    prior = dict(prior_losses or {})
    # Filtra le minusvalenze ancora utilizzabili: realizzate negli ultimi 4 anni.
    usabili = {
        y: amt
        for y, amt in prior.items()
        if config.tax_year - 4 <= y <= config.tax_year - 1 and amt > 0
    }

    if saldo > 0:
        result.rt23_differenza = saldo
        # Usa prima le minusvalenze più vecchie (evita che scadano).
        residuo_plus = saldo
        used_total = ZERO
        for y in sorted(usabili.keys()):
            if residuo_plus <= 0:
                break
            use = min(residuo_plus, usabili[y])
            residuo_plus -= use
            used_total += use
            prior[y] = prior.get(y, ZERO) - use
        result.minus_pregresse_usate = q2(used_total)
        result.rt26_imponibile = q2(max(ZERO, saldo - used_total))
        result.rt27_imposta = q2(result.rt26_imponibile * config.aliquota_sostitutiva)
    else:
        # Saldo negativo: minusvalenza dell'anno, da riportare.
        result.rt23_differenza = ZERO
        result.minus_anno = q2(-saldo)
        prior[config.tax_year] = prior.get(config.tax_year, ZERO) + (-saldo)
        if result.minus_anno > 0:
            warnings.info(
                "MINUS_RIPORTO",
                f"Minusvalenza {config.tax_year} di € {result.minus_anno} da indicare "
                f"in RT per il riporto nei 4 anni successivi (pena decadenza).",
            )

    # Aggiorna il residuo delle minusvalenze da riportare (rimuove le scadute).
    result.minus_da_riportare = {
        y: q2(amt)
        for y, amt in prior.items()
        if amt > 0 and y >= config.tax_year - 3  # utilizzabili ancora in futuro
    }

    return result
