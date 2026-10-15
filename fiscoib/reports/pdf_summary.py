"""PDF riepilogativo (reportlab) con totali imposte e warning."""

from __future__ import annotations

from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from ..pipeline import Results
from . import DISCLAIMER


def _eur(v) -> str:
    v = float(v) if isinstance(v, Decimal) else v
    return f"€ {v:,.2f}"


def build(results: Results, path: str) -> None:
    r = results
    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm)
    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    normal = styles["BodyText"]
    small = ParagraphStyle("small", parent=normal, fontSize=8, textColor=colors.grey)

    story = []
    story.append(Paragraph(f"Riepilogo fiscale IBKR — Anno d'imposta {r.config.tax_year}", h1))
    story.append(Paragraph(f"Conto: {r.statement.account_id or 'n/d'} — Stato estero: {r.config.account_country}", normal))
    story.append(Spacer(1, 6 * mm))

    # Tabella imposte
    data = [
        ["Voce", "Importo"],
        ["Imposta sostitutiva RT (plusvalenze)", _eur(r.rt.rt27_imposta)],
        ["Imposta sostitutiva RM (dividendi/interessi)", _eur(r.rm.tot_imposta_rm)],
        ["Imposta su plusvalenze OICR (reddito di capitale)", _eur(r.rt.oicr_imposta)],
        [
            ("IVAFE (RW) teorica — NON DOVUTA (≤ 200€)"
             if r.rw.ivafe_non_dovuta else "IVAFE (RW)"),
            _eur(r.rw.tot_ivafe_eur),
        ],
        ["TOTALE IMPOSTE DA VERSARE", _eur(r.imposta_totale)],
    ]
    t = Table(data, colWidths=[110 * mm, 50 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#DDEBF7")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 6 * mm))

    # Dettaglio sintetico
    story.append(Paragraph("Dettaglio", h2))
    det = [
        ["Quadro RT — corrispettivi (RT21)", _eur(r.rt.rt21_corrispettivi)],
        ["Quadro RT — costi (RT22)", _eur(r.rt.rt22_costi)],
        ["Quadro RT — imponibile (RT26)", _eur(r.rt.rt26_imponibile)],
        ["Minusvalenza anno da riportare", _eur(r.rt.minus_anno)],
        ["Quadro RM — base dividendi", _eur(r.rm.tot_base_dividendi)],
        ["Quadro RM — base interessi", _eur(r.rm.tot_base_interessi)],
        ["Ritenute estere (info)", _eur(r.rm.tot_wht_estera_eur)],
        ["Quadro RW — valore finale monitorato", _eur(r.rw.tot_valore_finale_eur)],
    ]
    t2 = Table(det, colWidths=[110 * mm, 50 * mm])
    t2.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(t2)
    story.append(Spacer(1, 6 * mm))

    smin, smax = r.rw.sanzione_potenziale()
    fascia = "6%–30% (conto black list)" if r.config.account_is_blacklist else "3%–15%"
    story.append(
        Paragraph(
            f"<b>Attenzione RW:</b> l'omessa/infedele dichiarazione del Quadro RW "
            f"comporta sanzioni stimate tra {_eur(smin)} e {_eur(smax)} "
            f"({fascia} del valore non dichiarato).",
            normal,
        )
    )
    if r.rw.ivafe_non_dovuta:
        story.append(
            Paragraph(
                f"<b>IVAFE:</b> imposta teorica {_eur(r.rw.tot_ivafe_eur)} ≤ 200 €: "
                f"versamento NON dovuto; resta l'obbligo di monitoraggio nel Quadro RW.",
                normal,
            )
        )
    story.append(Spacer(1, 4 * mm))

    # Warning
    crit = [w for w in r.warnings if w.level in ("WARN", "CRITICAL")]
    if crit:
        story.append(Paragraph("Avvisi da verificare", h2))
        for w in crit:
            story.append(Paragraph(f"• <b>{w.code}</b>: {w.message}", small))
        story.append(Spacer(1, 4 * mm))

    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(DISCLAIMER, small))

    doc.build(story)
