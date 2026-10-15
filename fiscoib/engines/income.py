"""Motore redditi di capitale — Quadro RM, Sez. II-A.

Gestisce:
- Dividendi esteri (rigo RM31, codice reddito H). Base imponibile secondo
  ``config.frontiera``: "lordo" (default, posizione AdE) o "netto" frontiera.
- Interessi attivi su liquidità (codice G) e cedole obbligazionarie:
  - titoli di Stato e assimilati white list (kwarg ``gov_bonds``):
    aliquota 12,5% (art. 31 DPR 601/1973; D.Lgs. 239/1996), codice A;
  - obbligazioni corporate e altri bond: aliquota 26%, codice I.
- Payment In Lieu of Dividends (titoli prestati) → ``config.pil_treatment``;
  quando trattato in RM usa codice C (reddito diverso assimilato, più coerente
  della H riservata ai dividendi; classificazione non normata: resta un warning).
- Dividend adjustment su CFD → ``config.cfd_dividend_adjustment`` (default RT,
  restituiti come componenti c-quater da sommare al Quadro RT).
- Interessi passivi/margin → NON deducibili: ignorati con nota.

Codici reddito usati (coerenti con istruzioni RM — nel modello 730 il quadro
omologo è il Quadro M, rigo M31):
  A = interessi su titoli di Stato e assimilati (12,5%);
  C = altri redditi (usato per PIL in RM; classificazione non consolidata);
  G = interessi attivi su deposito/liquidità (per interessi broker può essere
      ammissibile anche il codice I in via alternativa: qui si usa G);
  H = dividendi e utili esteri;
  I = interessi su obbligazioni corporate e altri bonds (26%).

Credito d'imposta estero: esiste una contrapposizione non risolta. Secondo la
posizione AdE (risposta a interpello n. 111/2020 e Istruzioni RM) nessun
credito è scomputabile in dichiarazione ordinaria quando il dividendo è tassato
integrato nel prelievo sostitutivo (si può solo tentare il rimborso); secondo
giurisprudenza di Cassazione (ordinanze n. 25698/2022 e n. 10204/2024) il
credito sarebbe invece recuperabile. Questo motore espone il credito teorico
come informazione, senza scomputarlo (scelta prudenziale, coerente con AdE).

I redditi di capitale NON si compensano con le minusvalenze.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple

from ..ade_tables import iso2_to_ade
from ..config import FiscoConfig
from ..money import ZERO, dec, q2
from ..fx.rates import RatesProvider
from ..parsing.models import CashTransaction
from ..prorata import (
    ALIQUOTA_WHITE_LIST,
    CODE_PRORATA_ANNI_PARZIALI,
    CODE_PRORATA_MANCANTE,
    FundGovQuotas,
    effective_rate,
)
from ..warnings import WarningCollector

DIVIDEND_TYPES = {"Dividends", "Dividend"}
PIL_TYPES = {"Payment In Lieu Of Dividends", "Payment In Lieu of Dividends"}
WHT_TYPES = {"Withholding Tax"}
INTEREST_RECEIVED = {"Broker Interest Received", "Bond Interest Received", "Credit Interest"}
INTEREST_PAID = {"Broker Interest Paid", "Bond Interest Paid", "Debit Interest"}

# Finestra di compatibilità data stacco / data ritenuta (giorni).
WHT_DATE_WINDOW = 3


def _country_from(ct: CashTransaction) -> str:
    inst = ct.instrument
    if inst and inst.isin and len(inst.isin) >= 2 and inst.isin[:2].isalpha():
        return inst.isin[:2].upper()
    return ""


def _issuers(ct: CashTransaction) -> tuple:
    """Chiave emittente: (conid, simbolo, ISIN) dell'eventuale strumento."""
    inst = ct.instrument
    if not inst:
        return ("", ct.description or "", "")
    return (inst.conid or "", inst.symbol or "", inst.isin or "")


def _group_key(ct: CashTransaction) -> Tuple[str, object]:
    inst = ct.instrument
    key = inst.key() if inst else (ct.description or "")
    return (key, ct.when)


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
    country_ade: str = ""
    # Aliquota applicata (26% ordinaria, 12,5% white list, effettiva con prorata).
    aliquota: Decimal = Decimal("0.26")
    # Quota media titoli di Stato white list usata per il prorata (solo fondi).
    quota_gov: Optional[Decimal] = None


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
    aliquota: Decimal = Decimal("0.26")
    codice_reddito: str = "G"
    country_ade: str = ""


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
        # Somma dei totali già q2 (entrambi somme dei q2 per-riga): il totale
        # è coerente per costruzione con le righe esposte.
        return self.tot_imposta_dividendi + self.tot_imposta_interessi


def compute_rm(
    cash_txs: List[CashTransaction],
    rates: RatesProvider,
    config: FiscoConfig,
    warnings: Optional[WarningCollector] = None,
    gov_bonds: Optional[Set[str]] = None,
    fund_gov_quotas: Optional[FundGovQuotas] = None,
) -> RMResult:
    """Calcola il Quadro RM da transazioni cash.

    ``gov_bonds``: insieme opzionale di identificativi (ISIN e/o simboli)
    dei titoli di Stato white list posseduti; serve a distinguere le cedole
    al 12,5% da quelle corporate al 26%. Se manca e sono presenti cedole
    obbligazionarie viene emesso un warning CRITICAL GOVBONDS_DA_CLASSIFICARE
    (una volta per emittente) e si applica il 26%.

    ``fund_gov_quotas``: quote medie di titoli di Stato white list per gli
    OICR (ETF/fondi), dal file --fund-gov-quota. Le distribuzioni dei fondi
    sono tassate con l'aliquota effettiva pro-rata (art. 2 c. 1-quater
    D.L. 138/2011): a parità di tutto il resto, aliquota = 26% - 13,5% x
    quota_govies. Fondi assenti dal file: 26% pieno + warning (una volta per
    fondo). Senza file: 26% pieno per tutti i fondi.
    """
    warnings = warnings or WarningCollector()
    res = RMResult(tax_year=config.tax_year)

    # Fondi per cui il warning prorata è già stato emesso (una volta per fondo).
    seen_prorata: Set[str] = set()

    # Paesi a cui non si riesce ad assegnare il codice AdE (warning una volta).
    seen_countries_unknown: Set[str] = set()

    def country_ade_of(country_iso: str) -> str:
        if country_iso in seen_countries_unknown:
            return country_iso
        code = iso2_to_ade(country_iso)
        if code is not None:
            return code
        seen_countries_unknown.add(country_iso)
        warnings.warn(
            "PAESE_ADE_SCONOSCIUTO",
            f"Codice paese '{country_iso or '(vuoto)'}' non mappato nella Tabella 10 AdE: "
            f"colonna 'paese' riportata con il valore originale. Estendere "
            f"fiscoib/ade_tables.py.",
        )
        return country_iso

    # Filtra sull'anno d'imposta (principio di cassa: pay date).
    txs = [c for c in cash_txs if c.when and c.when.year == config.tax_year]

    # --- Ritenute estere: somma ALGEBRICA per (strumento, data) ---
    # Le storni (reversal) hanno segno positivo e si compensano con le ritenute;
    # l'abs() finale rende l'importo positivo. abs() sulla singola riga 
    # introdurrebbe un doppio conteggio in caso di reversal.
    wht_map: Dict[Tuple[str, object], Decimal] = {}
    for c in txs:
        if c.tx_type in WHT_TYPES:
            key = _group_key(c)
            wht_map[key] = wht_map.get(key, ZERO) + c.amount

    # --- Dividendi e PIL, aggregati per (strumento, data) ---
    div_groups: Dict[Tuple[str, object], List[CashTransaction]] = {}
    # Gruppi composti da PIL: codice reddito C (alternativa più coerente alla H).
    pil_groups: Set[Tuple[str, object]] = set()
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
                "(Quadro RM, codice C): classificazione non normata, verificare.",
            )

        gkey = _group_key(c)
        div_groups.setdefault(gkey, []).append(c)
        if is_pil:
            pil_groups.add(gkey)

    matched_wht: Set[Tuple[str, object]] = set()

    for key, group in div_groups.items():
        gross_ccy = sum((c.amount for c in group), ZERO)
        if gross_ccy <= 0:
            continue
        sample = group[0]
        currency = sample.currency
        pay_date = sample.when
        rate = rates.daily_rate(currency, pay_date)

        # Match WHT: stesso strumento entro ±WHT_DATE_WINDOW giorni rispetto
        # alla data del dividendo (IB può contabilizzare la ritenuta in giorni
        # adiacenti, es. fine settimana).
        compat = [
            wkey for wkey in wht_map
            if wkey[0] == key[0]
            and abs((wkey[1] - pay_date).days) <= WHT_DATE_WINDOW
        ]
        wht_ccy = sum((abs(wht_map[wk]) for wk in compat), ZERO)
        for wk in compat:
            matched_wht.add(wk)

        gross_eur = dec(gross_ccy) / rate
        wht_eur = dec(wht_ccy) / rate

        if config.frontiera == "netto":
            base = gross_eur - wht_eur
        else:  # lordo (default)
            base = gross_eur

        # Pro-rata titoli di Stato: le distribuzioni di OICR sono risultato
        # maturato del fondo. Il periodo di maturazione non è noto: si usa la
        # quota media dell'anno solare di pagamento (vedi fiscoib/prorata.py).
        aliquota = config.aliquota_sostitutiva
        quota_gov: Optional[Decimal] = None
        inst = sample.instrument
        if inst is not None and inst.is_fund:
            info = (
                fund_gov_quotas.average_quota(
                    (inst.isin, inst.symbol, inst.conid),
                    date(pay_date.year, 1, 1),
                    date(pay_date.year, 12, 31),
                )
                if fund_gov_quotas
                else None
            )
            if info is not None:
                quota_gov = info.quota
                aliquota = effective_rate(config.aliquota_sostitutiva, info.quota)
                if info.missing_years and inst.symbol not in seen_prorata:
                    seen_prorata.add(inst.symbol)
                    warnings.warn(
                        CODE_PRORATA_ANNI_PARZIALI,
                        f"Dati prorata parziali per {inst.symbol}: anni {list(info.missing_years)} "
                        f"assenti dal file --fund-gov-quota, conteggiati con quota 0 "
                        f"(aliquota piena su quella frazione): controllare il dato del gestore.",
                    )
            elif inst.symbol not in seen_prorata:
                seen_prorata.add(inst.symbol)
                note = (
                    "il file --fund-gov-quota non contiene l'identificativo"
                    if fund_gov_quotas
                    else "manca il file --fund-gov-quota"
                )
                warnings.warn(
                    CODE_PRORATA_MANCANTE,
                    f"Distribuzione da fondo {inst.symbol}: {note} se il fondo contiene titoli di "
                    f"Stato white list. Applicata l'aliquota piena 26% (scelta prudente): con "
                    f"--fund-gov-quota si applicherebbe il pro-rata al 12,5% sulla quota "
                    f"governativa (art. 2 c. 1-quater D.L. 138/2011). "
                    f"Template: python -m fiscoib.build_inputs.",
                )

        imposta = base * aliquota
        credito_teorico = min(wht_eur, imposta)

        country_iso = _country_from(sample)
        res.dividends.append(
            DividendRow(
                symbol=sample.instrument.symbol if sample.instrument else "",
                country=country_iso,
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
                codice_reddito="C" if key in pil_groups else "H",
                country_ade=country_ade_of(country_iso),
                aliquota=aliquota,
                quota_gov=quota_gov,
            )
        )
        res.tot_base_dividendi += base
        res.tot_wht_estera_eur += wht_eur
        res.tot_credito_teorico_eur += credito_teorico
        # Totale imposta = somma dei q2 per-riga (coerenza riga/totale).
        res.tot_imposta_dividendi += q2(imposta)

    # Ritenute senza alcun dividendo compatibile: rischio di doppia imposizione
    # o di scarto dati silenti → CRITICAL.
    for wkey, amt in wht_map.items():
        if wkey in matched_wht:
            continue
        # cerca simbolo dalle txs WHT
        sym = next(
            (c.instrument.symbol for c in txs
             if c.tx_type in WHT_TYPES and _group_key(c) == wkey and c.instrument),
            str(wkey[0]),
        )
        warnings.critical(
            "WHT_SPAIATA",
            f"Ritenuta estera di {amt} {next((c.currency for c in txs if _group_key(c)==wkey), '')} "
            f"su {sym} del {wkey[1]} senza dividendo compatibile (finestra ±"
            f"{WHT_DATE_WINDOW}g): NON imputata. Verificare a mano il cassetto fiscale.",
        )

    # --- Interessi ---
    # Emittenti per cui è già stato emesso il warning CRITICAL una sola volta.
    seen_gov_unknown: Set[str] = set()

    for c in txs:
        if c.tx_type in INTEREST_RECEIVED and c.amount > 0:
            rate = rates.daily_rate(c.currency, c.when)
            base_eur = dec(c.amount) / rate

            is_bond = "Bond" in c.tx_type
            aliquota = config.aliquota_sostitutiva
            code = "G"
            if is_bond:
                # Titoli di Stato white list vs corporate.
                conid, sym, isin = _issuers(c)
                is_gov = bool(gov_bonds) and any(
                    v and v in gov_bonds for v in (conid, sym, isin)
                )
                if is_gov:
                    aliquota = ALIQUOTA_WHITE_LIST
                    code = "A"
                else:
                    code = "I"
                    issuer = sym or isin or c.description or "?"
                    if gov_bonds is None and issuer not in seen_gov_unknown:
                        seen_gov_unknown.add(issuer)
                        warnings.critical(
                            "GOVBONDS_DA_CLASSIFICARE",
                            f"Cedole da '{issuer}' (Bond Interest) SENZA lista "
                            f"'--gov-bonds': classificate al 26% come corporate. "
                            f"Passare --gov-bonds file.json con la lista degli ISIN/simboli "
                            f"dei titoli di Stato white list (aliquota 12,5%). "
                            f"Template: python -m fiscoib.build_inputs.",
                        )
                    elif gov_bonds is not None and issuer not in seen_gov_unknown:
                        # Lista passata ma emittente assente: 26% prudente, ma se è
                        # un governativo dimenticato l'utente perderebbe il 12,5%.
                        seen_gov_unknown.add(issuer)
                        warnings.warn(
                            "GOVBOND_NON_IN_LISTA",
                            f"Cedole da '{issuer}' NON presenti nella lista --gov-bonds: "
                            f"classificate al 26% come corporate. Se si tratta di un "
                            f"titolo di Stato white list (descrizione: '{(c.description or '')[:50]}'), "
                            f"aggiungere l'ISIN al file e rieseguire.",
                        )

            imposta = base_eur * aliquota
            country_iso = _country_from(c) or config.account_country
            res.interests.append(
                InterestRow(
                    description=c.description or c.tx_type,
                    country=country_iso,
                    when=c.when,
                    currency=c.currency,
                    amount_ccy=q2(c.amount),
                    rate=rate,
                    base_eur=q2(base_eur),
                    imposta_eur=q2(imposta),
                    aliquota=aliquota,
                    codice_reddito=code,
                    country_ade=country_ade_of(country_iso),
                )
            )
            res.tot_base_interessi += base_eur
            res.tot_imposta_interessi += q2(imposta)
        elif c.tx_type in INTEREST_PAID and c.amount < 0:
            rate = rates.daily_rate(c.currency, c.when)
            res.interessi_passivi_ignorati_eur += dec(-c.amount) / rate

    if res.interessi_passivi_ignorati_eur > 0:
        warnings.info(
            "INT_PASSIVI",
            f"Interessi passivi/margin per € {q2(res.interessi_passivi_ignorati_eur)} "
            f"NON deducibili per persona fisica: esclusi dal calcolo.",
        )

    # Arrotondamenti finali (imposte già somme di q2 per-riga: si q2 solo le basi).
    res.tot_base_dividendi = q2(res.tot_base_dividendi)
    res.tot_base_interessi = q2(res.tot_base_interessi)
    res.tot_wht_estera_eur = q2(res.tot_wht_estera_eur)
    res.tot_credito_teorico_eur = q2(res.tot_credito_teorico_eur)
    res.interessi_passivi_ignorati_eur = q2(res.interessi_passivi_ignorati_eur)
    res.tot_imposta_dividendi = q2(res.tot_imposta_dividendi)
    res.tot_imposta_interessi = q2(res.tot_imposta_interessi)

    if config.frontiera == "lordo" and res.tot_wht_estera_eur > 0:
        warnings.warn(
            "FRONTIERA",
            f"Dividendi tassati al LORDO frontiera (posizione AdE). Ritenute estere "
            f"per € {res.tot_wht_estera_eur} non scomputate: credito teorico "
            f"€ {res.tot_credito_teorico_eur} recuperabile solo con istanza di "
            f"rimborso (esito incerto; Cass. 25698/2022 e 10204/2024 sono favorevoli "
            f"ma la prassi AdE resta contraria — interpello 111/2020).",
        )

    return res


def _to_eur(rates: RatesProvider, c: CashTransaction) -> Decimal:
    rate = rates.daily_rate(c.currency, c.when)
    return dec(c.amount) / rate
