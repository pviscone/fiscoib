"""Facsimile testuale dei quadri RW / RT / RM da trascrivere nel modello Redditi PF.

I numeri di rigo (RT21, RT22, RM31...) seguono la struttura del modello ma vanno
sempre verificati sulle istruzioni ministeriali dell'anno d'imposta, perché possono
cambiare di anno in anno.
"""

from __future__ import annotations

from ..pipeline import Results
from . import DISCLAIMER


def _line(char="-", n=78):
    return char * n


def _g(row, key, default=None):
    """Legge un attributo (o chiave) opzionale di una riga risultato."""
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def render(results: Results) -> str:
    r = results
    cfg = r.config
    out = []
    out.append(_line("="))
    out.append(f"  FACSIMILE QUADRI - Modello Redditi PF - Anno d'imposta {cfg.tax_year}")
    out.append(f"  Conto: {r.statement.account_id or 'n/d'}  Stato estero: {cfg.account_country}")
    out.append(_line("="))
    out.append("")

    # ---------------- QUADRO RT ----------------
    out.append(_line())
    out.append("QUADRO RT - Sezione II-A - Plusvalenze di natura finanziaria (26%)")
    out.append(_line())
    out.append(f"  RT21  Totale corrispettivi ...................... € {r.rt.rt21_corrispettivi:>14,.2f}")
    out.append(f"  RT22  Totale costi (incl. commissioni) .......... € {r.rt.rt22_costi:>14,.2f}")
    out.append(f"  RT23  Differenza (plusvalenza lorda) ............ € {r.rt.rt23_differenza:>14,.2f}")
    out.append(f"  RT24  Minusvalenze pregresse utilizzate ......... € {r.rt.minus_pregresse_usate:>14,.2f}")
    out.append(f"  RT26  Imponibile ................................ € {r.rt.rt26_imponibile:>14,.2f}")
    out.append(f"  RT27  Imposta sostitutiva (26%) ................. € {r.rt.rt27_imposta:>14,.2f}")
    if r.rt.minus_anno > 0:
        out.append(f"  >> Minusvalenza {cfg.tax_year} da riportare (Sez. dedicata): € {r.rt.minus_anno:,.2f}")
    if r.rt.minus_da_riportare:
        det = ", ".join(f"{y}: € {v:,.2f}" for y, v in sorted(r.rt.minus_da_riportare.items()))
        out.append(f"  >> Minusvalenze residue riportabili: {det}")
    out.append("  Codice tributo versamento F24 per RT: 1100")
    out.append("")

    # ---------------- QUADRO RM ----------------
    out.append(_line())
    out.append("QUADRO RM - Sezione II-A (rigo RM31) - Redditi di capitale esteri (26%)")
    out.append(_line())
    if r.rm.dividends:
        out.append("  Dividendi (codice reddito H):")
        out.append("    " + f"{'Titolo':<14}{'Stato':<6}{'AdE':>4}{'Alq.':>6}{'Base imp.EUR':>14}{'Imposta EUR':>14}")
        for d in r.rm.dividends:
            ali = _g(d, "aliquota", cfg.aliquota_sostitutiva)
            country_ade = _g(d, "country_ade", "") or ""
            out.append(
                "    "
                + f"{d.symbol[:13]:<14}{d.country:<6}{str(country_ade)[:4]:>4}"
                + f"{float(ali) * 100:>5.1f}%{d.base_imponibile_eur:>14,.2f}{d.imposta_eur:>14,.2f}"
            )
    if r.rm.interests:
        out.append("  Interessi (codice reddito G/I):")
        for i in r.rm.interests:
            ali = _g(i, "aliquota", cfg.aliquota_sostitutiva)
            country_ade = _g(i, "country_ade", "") or ""
            tag = ""
            if _g(i, "lettera"):
                tag = f" [lett. {_g(i, 'lettera')}]"
            if ali != cfg.aliquota_sostitutiva:
                tag += f" [{float(ali) * 100:.0f}%]"
            out.append(
                "    "
                + f"{i.description[:20]:<22}{i.country:<6}{str(country_ade)[:4]:>4}"
                + f"{i.base_eur:>14,.2f}{i.imposta_eur:>14,.2f}{tag}"
            )
    if r.rt.oicr_gains:
        out.append("  Plusvalenze su quote OICR/ETF (reddito di capitale, codice reddito H):")
        out.append("    " + f"{'Titolo':<14}{'Stato':<6}{'Base EUR':>14}{'Quota gov':>10}{'Alq.eff.':>10}{'Imposta EUR':>14}")
        for g in r.rt.oicr_gains:
            qg = _g(g, "quota_gov", None)
            qg_s = f"{float(qg) * 100:.1f}%" if qg is not None else "-"
            ali = _g(g, "aliquota", "0.26")
            out.append(
                "    "
                + f"{str(_g(g, 'symbol', ''))[:13]:<14}{str(_g(g, 'country', '')):<6}"
                + f"{_g(g, 'gain_eur', 0):>14,.2f}{qg_s:>10}"
                + f"{float(ali) * 100:>9.2f}%{_g(g, 'imposta_eur', 0):>14,.2f}"
            )
        out.append(
            f"    {'TOTALE OICR':<20}{r.rt.oicr_imponibile:>14,.2f}"
            f"{'':>10}{'':>10}{r.rt.oicr_imposta:>14,.2f}"
        )
        if any(_g(g, "quota_gov", None) is not None for g in r.rt.oicr_gains):
            out.append(
                "    (pro-rata titoli di Stato: aliquota effettiva = 26% - 13,5% x quota "
                "govies white list, art. 2 c. 1-quater D.L. 138/2011)"
            )
    out.append("")
    out.append(f"  RM31 col.3  Totale base imponibile dividendi .... € {r.rm.tot_base_dividendi:>14,.2f}")
    out.append(f"              Totale base imponibile interessi .... € {r.rm.tot_base_interessi:>14,.2f}")
    if r.rt.oicr_gains:
        out.append(f"              Totale base plusvalenze OICR ........ € {r.rt.oicr_imponibile:>14,.2f}")
    out.append(f"  RM31 col.8  Imposta sostitutiva RM (26%) ....... € {r.rm.tot_imposta_rm:>14,.2f}")
    if r.rt.oicr_gains:
        out.append(f"              Imposta su plusvalenze OICR ........ € {r.rt.oicr_imposta:>14,.2f}")
        tot_f24 = r.rm.tot_imposta_rm + r.rt.oicr_imposta
        out.append(f"              Totale F24 codice 1242 ............. € {tot_f24:>14,.2f}")
    if r.rm.tot_wht_estera_eur > 0:
        out.append(f"  (info) Ritenute estere subite .................. € {r.rm.tot_wht_estera_eur:>14,.2f}")
        out.append(f"  (info) Credito teorico da eventuale rimborso ... € {r.rm.tot_credito_teorico_eur:>14,.2f}")
        out.append(f"  Base imponibile: frontiera = {cfg.frontiera.upper()}")
    out.append("  Codice tributo versamento F24 per RM: 1242")
    out.append("")

    # ---------------- QUADRO RW ----------------
    aliquota_rw = (
        cfg.ivafe_rate_blacklist
        if cfg.is_blacklist(cfg.account_country)
        else cfg.ivafe_rate
    )
    out.append(_line())
    out.append(f"QUADRO RW - Monitoraggio fiscale e IVAFE ({float(aliquota_rw) * 100:.1f}%)")
    out.append(_line())
    hdr = (
        f"{'#':>2} {'Descrizione':<26}{'Cod':>4}{'Stato':>6}{'StatoAdE':>9}"
        f"{'ValIniz':>10}{'ValFin':>10}{'gg':>5}{'IVAFE':>9}"
    )
    out.append("  " + hdr)
    for idx, w in enumerate(r.rw.rows, 1):
        flag = " *" if w.solo_monitoraggio else ""
        out.append(
            "  "
            + f"{idx:>2} {w.descrizione[:25]:<26}{w.codice_bene:>4}{w.stato_estero:>6}"
            + f"{w.stato_estero_ade:>9}"
            + f"{w.valore_iniziale_eur:>10,d}{w.valore_finale_eur:>10,d}{w.giorni:>5}{w.ivafe_eur:>9,.2f}{flag}"
        )
    out.append("")
    out.append(f"  Totale valore finale monitorato ................ € {r.rw.tot_valore_finale_eur:>14,d}")
    out.append(f"  IVAFE teorica ({float(aliquota_rw) * 100:.1f}%) ........................ € {r.rw.tot_ivafe_eur:>14,.2f}")
    if r.rw.ivafe_non_dovuta:
        out.append(
            f"  >> IVAFE € {r.rw.tot_ivafe_eur:,.2f} ≤ 200€: VERSAMENTO NON DOVUTO "
            f"(dichiarare solo RW) [art. 19 c.20 DL 201/2011]"
        )
    else:
        out.append(f"  IVAFE da versare ............................... € {r.rw.ivafe_da_versare:>14,.2f}")
    out.append("  (*) rigo con casella 'solo monitoraggio' barrata (IVAFE non applicata)")
    smin, smax = r.rw.sanzione_potenziale()
    fascia = "6%-30% (conto black list)" if cfg.account_is_blacklist else "3%-15%"
    out.append(
        f"  ATTENZIONE: l'omessa compilazione RW comporta sanzioni stimate tra "
        f"€ {smin:,.2f} e € {smax:,.2f} ({fascia} del valore)."
    )
    out.append("")

    # ---------------- TOTALI ----------------
    out.append(_line("="))
    out.append("  RIEPILOGO IMPOSTE DA VERSARE (F24: RT cod. 1100, RM cod. 1242)")
    out.append(_line("="))
    out.append(f"  Imposta sostitutiva RT (plusvalenze) ........... € {r.rt.rt27_imposta:>14,.2f}")
    out.append(f"  Imposta sostitutiva RM (dividendi/interessi) ... € {r.rm.tot_imposta_rm:>14,.2f}")
    if r.rt.oicr_gains:
        out.append(f"  Imposta su plusvalenze OICR (reddito capitale) € {r.rt.oicr_imposta:>14,.2f}")
    if r.rw.ivafe_non_dovuta:
        out.append(f"  IVAFE (RW) teorica € {r.rw.tot_ivafe_eur:,.2f} -> 0,00 (≤ 200€, non dovuta)")
    else:
        out.append(f"  IVAFE (RW) ..................................... € {r.rw.tot_ivafe_eur:>14,.2f}")
    out.append(f"  {'TOTALE IMPOSTE DA VERSARE':<46} € {r.imposta_totale:>14,.2f}")
    out.append("")
    if r.rw.ivafe_non_dovuta:
        out.append(
            "  NOTA IVAFE: versamento non dovuto perché l'imposta complessiva non supera "
            "€ 200; l'obbligo di monitoraggio (Quadro RW) resta."
        )
        out.append("")
    out.append(_line())
    out.append("  Chi si avvale del 730: le attività estere del Quadro RW si espongono nel")
    out.append("  modello 730 nel Quadro W; i redditi di capitale del Quadro RM vanno")
    out.append("  ricondotti nel Quadro M (rigo M31) del Modello Redditi PF secondo le")
    out.append("  istruzioni ministeriali: in quel caso l'imposta qui calcolata non va")
    out.append("  autoliquidata con F24 ma gestita tramite F24/730 come da istruzioni.")
    out.append(_line())
    out.append("  " + DISCLAIMER)
    out.append(_line())
    return "\n".join(out)


def write(results: Results, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(results))
