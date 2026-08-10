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
    out.append("")

    # ---------------- QUADRO RM ----------------
    out.append(_line())
    out.append("QUADRO RM - Sezione II-A (rigo RM31) - Redditi di capitale esteri (26%)")
    out.append(_line())
    if r.rm.dividends:
        out.append("  Dividendi (codice reddito H):")
        out.append("    " + f"{'Titolo':<14}{'Stato':<6}{'Base imp.EUR':>14}{'Imposta EUR':>14}")
        for d in r.rm.dividends:
            out.append(
                "    "
                + f"{d.symbol[:13]:<14}{d.country:<6}{d.base_imponibile_eur:>14,.2f}{d.imposta_eur:>14,.2f}"
            )
    if r.rm.interests:
        out.append("  Interessi (codice reddito G/I):")
        for i in r.rm.interests:
            out.append(
                "    "
                + f"{i.description[:20]:<22}{i.country:<6}{i.base_eur:>14,.2f}{i.imposta_eur:>14,.2f}"
            )
    out.append("")
    out.append(f"  RM31 col.3  Totale base imponibile dividendi .... € {r.rm.tot_base_dividendi:>14,.2f}")
    out.append(f"              Totale base imponibile interessi .... € {r.rm.tot_base_interessi:>14,.2f}")
    out.append(f"  RM31 col.8  Imposta sostitutiva RM (26%) ....... € {r.rm.tot_imposta_rm:>14,.2f}")
    if r.rm.tot_wht_estera_eur > 0:
        out.append(f"  (info) Ritenute estere subite .................. € {r.rm.tot_wht_estera_eur:>14,.2f}")
        out.append(f"  (info) Credito teorico da eventuale rimborso ... € {r.rm.tot_credito_teorico_eur:>14,.2f}")
        out.append(f"  Base imponibile: frontiera = {cfg.frontiera.upper()}")
    out.append("  Codice tributo versamento F24: 1242")
    out.append("")

    # ---------------- QUADRO RW ----------------
    out.append(_line())
    out.append("QUADRO RW - Monitoraggio fiscale e IVAFE (0,2%)")
    out.append(_line())
    hdr = f"{'#':>2} {'Descrizione':<26}{'Cod':>4}{'Stato':>6}{'ValIniz':>10}{'ValFin':>10}{'gg':>5}{'IVAFE':>9}"
    out.append("  " + hdr)
    for idx, w in enumerate(r.rw.rows, 1):
        flag = " *" if w.solo_monitoraggio else ""
        out.append(
            "  "
            + f"{idx:>2} {w.descrizione[:25]:<26}{w.codice_bene:>4}{w.stato_estero:>6}"
            + f"{w.valore_iniziale_eur:>10,d}{w.valore_finale_eur:>10,d}{w.giorni:>5}{w.ivafe_eur:>9,.2f}{flag}"
        )
    out.append("")
    out.append(f"  Totale valore finale monitorato ................ € {r.rw.tot_valore_finale_eur:>14,d}")
    out.append(f"  Totale IVAFE dovuta (0,2%) ..................... € {r.rw.tot_ivafe_eur:>14,.2f}")
    out.append("  (*) rigo con casella 'solo monitoraggio' barrata (IVAFE non applicata)")
    smin, smax = r.rw.sanzione_potenziale()
    out.append(
        f"  ATTENZIONE: l'omessa compilazione RW comporta sanzioni stimate tra "
        f"€ {smin:,.2f} e € {smax:,.2f} (3%-15% del valore)."
    )
    out.append("")

    # ---------------- TOTALI ----------------
    out.append(_line("="))
    out.append("  RIEPILOGO IMPOSTE")
    out.append(_line("="))
    out.append(f"  Imposta sostitutiva RT (plusvalenze) ........... € {r.rt.rt27_imposta:>14,.2f}")
    out.append(f"  Imposta sostitutiva RM (dividendi/interessi) ... € {r.rm.tot_imposta_rm:>14,.2f}")
    out.append(f"  IVAFE (RW) ..................................... € {r.rw.tot_ivafe_eur:>14,.2f}")
    out.append(f"  {'TOTALE IMPOSTE DOVUTE':<46} € {r.imposta_totale:>14,.2f}")
    out.append("")
    out.append(_line())
    out.append("  " + DISCLAIMER)
    out.append(_line())
    return "\n".join(out)


def write(results: Results, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(results))
