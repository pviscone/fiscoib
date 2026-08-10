"""Motore monitoraggio fiscale — Quadro RW e IVAFE.

Per ogni strumento detenuto durante l'anno d'imposta produce un rigo RW con:
codice bene, stato estero, valore iniziale/finale in EUR, giorni di detenzione e
IVAFE pro-rata. Aggiunge righe per la liquidità (cash) per valuta.

Valorizzazione (cambio MEDIO MENSILE ufficiale, non giornaliero):
- Titoli ancora aperti al 31/12: valore di mercato al 31/12 (cambio medio dicembre).
- Titoli chiusi in corso d'anno: valore all'ultima chiusura (cambio medio del mese).
- Valore iniziale: valore al 1/1 se già detenuto, altrimenti valore di acquisto.

IVAFE = valore_finale_EUR × aliquota × (giorni/365) × (quota%/100).
Aliquota 0,2% (0,4% se paese black list). CFD/OTC: IVAFE solo se abilitata in
config, altrimenti "solo monitoraggio".

Codici bene (colonna 3 del Quadro RW):
- 20 = conto deposito titoli estero (azioni quotate + liquidità)
-  2 = partecipazioni non quotate (azioni OTC)
-  9 = contratti derivati / rapporti finanziari (CFD)
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from ..config import FiscoConfig
from ..money import ZERO, dec, q2, euro_int
from ..fx.rates import RatesProvider
from ..parsing.models import CashReportRow, Instrument, OpenPosition, Statement, Trade
from ..warnings import WarningCollector

COD_DEPOSITO = "20"
COD_PARTECIPAZIONE = "2"
COD_DERIVATO = "9"


@dataclass
class RWRow:
    descrizione: str
    codice_bene: str
    stato_estero: str
    codice_valorizzazione: str        # 1=mercato, 2=nominale, 3=costo
    valore_iniziale_eur: int
    valore_finale_eur: int
    giorni: int
    quota_pct: Decimal
    ivafe_applicata: bool
    ivafe_aliquota: Decimal
    ivafe_eur: Decimal
    solo_monitoraggio: bool
    note: str = ""


@dataclass
class RWResult:
    tax_year: int
    rows: List[RWRow] = field(default_factory=list)
    tot_valore_finale_eur: int = 0
    tot_ivafe_eur: Decimal = ZERO

    def sanzione_potenziale(self) -> Tuple[Decimal, Decimal]:
        """Stima min/max sanzione per omessa dichiarazione RW (3%-15% white list)."""
        base = dec(self.tot_valore_finale_eur)
        return q2(base * Decimal("0.03")), q2(base * Decimal("0.15"))


def _year_bounds(year: int) -> Tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


def _days_inclusive(a: date, b: date) -> int:
    return (b - a).days + 1


def _instrument_intervals(
    trades: List[Trade], year: int
) -> Tuple[int, bool, Optional[date], Optional[Decimal], Optional[Decimal], Optional[date]]:
    """Ricostruisce la detenzione di uno strumento sull'intero storico.

    Ritorna:
    - giorni detenuti dentro l'anno
    - held_at_year_end
    - data primo acquisto nell'anno (o None se già detenuto a inizio anno)
    - valore all'ultima chiusura in valuta (per titoli chiusi in anno)
    - valore/quantità di acquisto iniziale nell'anno (per valore_iniziale)
    - data ultima chiusura in anno
    """
    ys, ye = _year_bounds(year)
    events = sorted(trades, key=lambda t: (t.trade_date, 0 if t.is_buy else 1))

    qty = ZERO
    interval_start: Optional[date] = None
    held_days = 0
    held_at_year_end = False
    first_open_in_year: Optional[date] = None
    last_close_value: Optional[Decimal] = None
    last_close_date: Optional[date] = None
    acq_value_in_year: Optional[Decimal] = None

    def add_overlap(start: date, end: date) -> int:
        s = max(start, ys)
        e = min(end, ye)
        if e < s:
            return 0
        return _days_inclusive(s, e)

    for t in events:
        prev_qty = qty
        qty = qty + t.signed_quantity

        opening = prev_qty == 0 and qty != 0
        closing = prev_qty != 0 and qty == 0
        # apertura di un nuovo intervallo
        if opening:
            interval_start = t.trade_date
            if ys <= t.trade_date <= ye:
                if first_open_in_year is None:
                    first_open_in_year = t.trade_date
                    acq_value_in_year = abs(t.signed_quantity) * t.price
        # chiusura a zero
        if closing and interval_start is not None:
            held_days += add_overlap(interval_start, t.trade_date)
            if ys <= t.trade_date <= ye:
                last_close_value = abs(prev_qty) * t.price
                last_close_date = t.trade_date
            interval_start = None

    # Intervallo ancora aperto alla fine dei dati.
    if interval_start is not None:
        held_days += add_overlap(interval_start, ye)
        held_at_year_end = True

    return (
        held_days,
        held_at_year_end,
        first_open_in_year,
        last_close_value,
        acq_value_in_year,
        last_close_date,
    )


def _codice_bene(inst: Instrument) -> str:
    if inst.is_cfd:
        return COD_DERIVATO
    if inst.is_otc:
        return COD_PARTECIPAZIONE
    return COD_DEPOSITO


def _ivafe_applies(inst: Instrument, config: FiscoConfig) -> bool:
    if inst.is_cfd:
        return config.ivafe_cfd
    if inst.is_otc:
        return config.ivafe_otc
    return True  # azioni quotate: sempre


def compute_rw(
    statement: Statement,
    rates: RatesProvider,
    config: FiscoConfig,
    warnings: Optional[WarningCollector] = None,
) -> RWResult:
    warnings = warnings or WarningCollector()
    res = RWResult(tax_year=config.tax_year)
    year = config.tax_year
    _, ye = _year_bounds(year)

    aliquota = (
        config.ivafe_rate_blacklist
        if config.is_blacklist(config.account_country)
        else config.ivafe_rate
    )
    quota = config.ownership_pct
    year_days = Decimal(config.year_days_basis)

    # Mappa posizioni aperte al 31/12 per strumento. Con Open Positions esportate
    # a livello "Lot" (come da README) ci sono PIÙ righe per lo stesso strumento,
    # una per tranche: vanno SOMMATE per ottenere la posizione complessiva, non
    # sovrascritte (altrimenti sopravvive un solo lotto e valore/IVAFE risultano
    # sottostimati).
    open_by_key: Dict[str, OpenPosition] = {}
    for p in statement.open_positions:
        if not (p.report_date and p.report_date.year == year):
            continue
        existing = open_by_key.get(p.instrument.key())
        if existing is None:
            open_by_key[p.instrument.key()] = replace(p)
        else:
            existing.quantity += p.quantity
            existing.position_value += p.position_value
            existing.cost_basis_money += p.cost_basis_money

    # Raggruppa i trade per strumento.
    trades_by_key: Dict[str, List[Trade]] = {}
    inst_by_key: Dict[str, Instrument] = {}
    for t in statement.trades:
        if not t.trade_date:
            continue
        trades_by_key.setdefault(t.instrument.key(), []).append(t)
        inst_by_key[t.instrument.key()] = t.instrument
    # Include strumenti presenti solo tra le posizioni aperte (nessun trade nell'anno).
    for key, p in open_by_key.items():
        inst_by_key.setdefault(key, p.instrument)
        trades_by_key.setdefault(key, [])

    for key, inst in inst_by_key.items():
        trades = trades_by_key.get(key, [])
        (
            giorni,
            held_end,
            first_open,
            last_close_val_ccy,
            acq_val_ccy,
            last_close_date,
        ) = _instrument_intervals(trades, year)

        open_pos = open_by_key.get(key)
        if open_pos is not None:
            held_end = True

        # Se non c'è detenzione nell'anno, salta.
        if giorni <= 0 and not held_end:
            continue
        if giorni <= 0 and held_end:
            giorni = _days_inclusive(_year_bounds(year)[0], ye)
        # Il pro-rata IVAFE è convenzionalmente su base 365: cap per gli anni
        # bisestili (una detenzione per l'intero anno vale 365/365, non 366/365).
        giorni = min(giorni, config.year_days_basis)

        currency = inst.currency or (open_pos.currency if open_pos else "EUR")

        # --- Base IVAFE (valore alla fine del periodo di detenzione) ---
        # NB: la colonna "valore finale" (col.8) del rigo RW è il valore al 31/12
        # (0 se il titolo è stato interamente ceduto in corso d'anno), mentre la
        # base IVAFE è il valore all'ultimo giorno di possesso.
        if held_end and open_pos is not None:
            ivafe_base_eur = rates.to_eur_monthly(
                abs(dec(open_pos.position_value)), currency, year, 12
            )
            valore_finale_col = ivafe_base_eur
            cod_val = "1"  # valore di mercato
        elif held_end and open_pos is None:
            # Aperto ma senza dato di mercato: usa costo di acquisto, con warning.
            ivafe_base_eur = rates.to_eur_monthly(abs(acq_val_ccy or ZERO), currency, year, 12)
            valore_finale_col = ivafe_base_eur
            cod_val = "3"
            warnings.warn(
                "RW_NO_MARKET",
                f"{inst.symbol}: posizione aperta al 31/12 senza valore di mercato "
                f"nel file (manca Open Position). Valorizzata al costo — verificare.",
            )
        else:
            # Chiuso in corso d'anno: base IVAFE = valore all'ultima chiusura,
            # colonna valore finale = 0 (non più detenuto al 31/12).
            m = (last_close_date or ye).month
            ivafe_base_eur = rates.to_eur_monthly(
                abs(last_close_val_ccy or ZERO), currency, year, m
            )
            valore_finale_col = ZERO
            cod_val = "1"

        # --- Valore iniziale ---
        if first_open is not None:
            # Acquistato nell'anno: valore di acquisto (mese di acquisto).
            valore_ini_eur = rates.to_eur_monthly(
                abs(acq_val_ccy or ZERO), currency, year, first_open.month
            )
        else:
            # Già detenuto a inizio anno: non disponibile il valore al 31/12
            # dell'anno precedente in questo file → warning, usa base IVAFE.
            valore_ini_eur = ivafe_base_eur
            warnings.info(
                "RW_VAL_INIZIALE",
                f"{inst.symbol}: valore iniziale al 1/1 non ricavabile dal file "
                f"(posizione ereditata da anni precedenti). Inserire il valore al "
                f"31/12 dell'anno precedente.",
            )

        # --- IVAFE ---
        applies = _ivafe_applies(inst, config)
        if applies:
            ivafe = (
                ivafe_base_eur
                * aliquota
                * (Decimal(giorni) / year_days)
                * (quota / Decimal("100"))
            )
            ivafe = q2(max(ZERO, ivafe))
        else:
            ivafe = ZERO
            warnings.warn(
                "IVAFE_INCERTA",
                f"{inst.symbol} ({'CFD' if inst.is_cfd else 'OTC'}): IVAFE non "
                f"applicata (solo monitoraggio) per incertezza normativa. Valutare "
                f"con il commercialista.",
            )

        res.rows.append(
            RWRow(
                descrizione=f"{inst.symbol} - {inst.description}".strip(" -"),
                codice_bene=_codice_bene(inst),
                stato_estero=config.account_country,
                codice_valorizzazione=cod_val,
                valore_iniziale_eur=euro_int(valore_ini_eur),
                valore_finale_eur=euro_int(valore_finale_col),
                giorni=int(giorni),
                quota_pct=quota,
                ivafe_applicata=applies,
                ivafe_aliquota=aliquota,
                ivafe_eur=ivafe,
                solo_monitoraggio=not applies,
                note="",
            )
        )
        res.tot_valore_finale_eur += euro_int(valore_finale_col)
        res.tot_ivafe_eur += ivafe

    # --- Liquidità (cash) per valuta al 31/12 ---
    account_days = _account_days_in_year(statement, year)
    for row in statement.cash_report:
        if row.to_date and row.to_date.year != year:
            continue
        ending = dec(row.ending_cash)
        if ending == 0:
            continue
        valore_eur = rates.to_eur_monthly(abs(ending), row.currency, year, 12)
        ivafe_cash = q2(
            valore_eur * aliquota * (Decimal(account_days) / year_days) * (quota / Decimal("100"))
        )
        res.rows.append(
            RWRow(
                descrizione=f"Liquidità {row.currency}",
                codice_bene=COD_DEPOSITO,
                stato_estero=config.account_country,
                codice_valorizzazione="1",
                valore_iniziale_eur=euro_int(
                    rates.to_eur_monthly(abs(dec(row.starting_cash)), row.currency, year, 1)
                    if row.starting_cash
                    else ZERO
                ),
                valore_finale_eur=euro_int(valore_eur),
                giorni=int(account_days),
                quota_pct=quota,
                ivafe_applicata=True,
                ivafe_aliquota=aliquota,
                ivafe_eur=ivafe_cash,
                solo_monitoraggio=False,
                note="Liquidità del conto deposito titoli",
            )
        )
        res.tot_valore_finale_eur += euro_int(valore_eur)
        res.tot_ivafe_eur += ivafe_cash

    res.tot_ivafe_eur = q2(res.tot_ivafe_eur)

    if not res.rows:
        warnings.warn(
            "RW_VUOTO",
            "Nessuna attività estera rilevata per il Quadro RW: verificare che il "
            "file contenga posizioni e movimenti dell'anno.",
        )
    return res


def _account_days_in_year(statement: Statement, year: int) -> int:
    ys, ye = _year_bounds(year)
    start = ys
    if statement.from_date and statement.from_date > ys:
        start = statement.from_date
    if start > ye:
        return 0
    return min(_days_inclusive(start, ye), 365)
