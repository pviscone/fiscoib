"""Export dei dati intermedi e finali in CSV e JSON."""

from __future__ import annotations

import csv
import json
import os
from decimal import Decimal

from ..pipeline import Results


def _default(o):
    if isinstance(o, Decimal):
        return float(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


def write_json(results: Results, path: str) -> None:
    r = results
    payload = {
        "anno": r.config.tax_year,
        "conto": r.statement.account_id,
        "config": {
            "frontiera": r.config.frontiera,
            "ivafe_cfd": r.config.ivafe_cfd,
            "ivafe_otc": r.config.ivafe_otc,
            "cfd_dividend_adjustment": r.config.cfd_dividend_adjustment,
            "pil_treatment": r.config.pil_treatment,
        },
        "RT": {
            "rt21_corrispettivi": r.rt.rt21_corrispettivi,
            "rt22_costi": r.rt.rt22_costi,
            "rt23_differenza": r.rt.rt23_differenza,
            "minus_pregresse_usate": r.rt.minus_pregresse_usate,
            "rt26_imponibile": r.rt.rt26_imponibile,
            "rt27_imposta": r.rt.rt27_imposta,
            "minus_anno": r.rt.minus_anno,
            "minus_da_riportare": r.rt.minus_da_riportare,
            "dettaglio": [row.__dict__ for row in r.rt.rows],
        },
        "RM": {
            "tot_base_dividendi": r.rm.tot_base_dividendi,
            "tot_imposta_dividendi": r.rm.tot_imposta_dividendi,
            "tot_base_interessi": r.rm.tot_base_interessi,
            "tot_imposta_interessi": r.rm.tot_imposta_interessi,
            "tot_wht_estera_eur": r.rm.tot_wht_estera_eur,
            "tot_credito_teorico_eur": r.rm.tot_credito_teorico_eur,
            "dividendi": [d.__dict__ for d in r.rm.dividends],
            "interessi": [i.__dict__ for i in r.rm.interests],
        },
        "RW": {
            "tot_valore_finale_eur": r.rw.tot_valore_finale_eur,
            "tot_ivafe_eur": r.rw.tot_ivafe_eur,
            "righi": [w.__dict__ for w in r.rw.rows],
        },
        "totale_imposte": r.imposta_totale,
        "warnings": [{"level": w.level, "code": w.code, "message": w.message} for w in r.warnings],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=_default)


def write_csv(results: Results, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)

    # RT dettaglio
    with open(os.path.join(out_dir, "rt_plusvalenze.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["symbol", "asset", "long", "qty", "valuta", "apertura", "chiusura",
             "corrispettivo_eur", "costo_eur", "commissioni_eur", "plus_minus_eur",
             "cambio_apertura", "cambio_chiusura"]
        )
        for row in results.rt.rows:
            w.writerow(
                [row.symbol, row.asset_category, row.is_long, row.qty, row.currency,
                 row.open_date, row.close_date, row.corrispettivo_eur, row.costo_eur,
                 row.commissioni_eur, row.plus_minus_eur, row.rate_open, row.rate_close]
            )

    # RM dividendi
    with open(os.path.join(out_dir, "rm_dividendi.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["symbol", "stato", "pay_date", "valuta", "lordo_ccy", "ritenuta_ccy",
             "cambio", "lordo_eur", "ritenuta_eur", "base_imponibile_eur", "imposta_eur",
             "credito_teorico_eur"]
        )
        for d in results.rm.dividends:
            w.writerow(
                [d.symbol, d.country, d.pay_date, d.currency, d.gross_ccy, d.wht_ccy,
                 d.rate, d.gross_eur, d.wht_eur, d.base_imponibile_eur, d.imposta_eur,
                 d.credito_teorico_eur]
            )

    # RW righi
    with open(os.path.join(out_dir, "rw_monitoraggio.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["descrizione", "codice_bene", "stato", "cod_valorizzazione",
             "valore_iniziale_eur", "valore_finale_eur", "giorni", "quota_pct",
             "ivafe_applicata", "ivafe_aliquota", "ivafe_eur", "solo_monitoraggio"]
        )
        for row in results.rw.rows:
            w.writerow(
                [row.descrizione, row.codice_bene, row.stato_estero, row.codice_valorizzazione,
                 row.valore_iniziale_eur, row.valore_finale_eur, row.giorni, row.quota_pct,
                 row.ivafe_applicata, row.ivafe_aliquota, row.ivafe_eur, row.solo_monitoraggio]
            )
