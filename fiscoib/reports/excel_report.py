"""Report Excel dettagliato (openpyxl) con fogli per RT, RM, RW, cambi e warning."""

from __future__ import annotations

from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from ..pipeline import Results
from . import DISCLAIMER

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=13)
EUR = "#,##0.00"


def _num(v):
    return float(v) if isinstance(v, Decimal) else v


def _header(ws, row, headers):
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=row, column=c, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")


def _autosize(ws):
    for col in ws.columns:
        length = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(length + 2, 45)


def build(results: Results, path: str) -> None:
    r = results
    wb = Workbook()

    # -------- Riepilogo --------
    ws = wb.active
    ws.title = "Riepilogo"
    ws["A1"] = f"Riepilogo fiscale IBKR — Anno d'imposta {r.config.tax_year}"
    ws["A1"].font = TITLE_FONT
    ws["A3"] = "Conto"; ws["B3"] = r.statement.account_id
    ws["A4"] = "Frontiera dividendi"; ws["B4"] = r.config.frontiera
    rows = [
        ("Imposta sostitutiva RT (plusvalenze)", r.rt.rt27_imposta),
        ("Imposta sostitutiva RM (dividendi/interessi)", r.rm.tot_imposta_rm),
        ("IVAFE (RW) teorica", r.rw.tot_ivafe_eur),
        ("IVAFE da versare", r.rw.ivafe_da_versare),
        ("TOTALE IMPOSTE DA VERSARE", r.imposta_totale),
        ("Minusvalenza dell'anno da riportare", r.rt.minus_anno),
        ("Ritenute estere subite (info)", r.rm.tot_wht_estera_eur),
        ("Credito teorico rimborso (info)", r.rm.tot_credito_teorico_eur),
    ]
    for i, (label, val) in enumerate(rows, start=6):
        ws.cell(row=i, column=1, value=label)
        c = ws.cell(row=i, column=2, value=_num(val))
        c.number_format = EUR
        if label.startswith("TOTALE"):
            ws.cell(row=i, column=1).font = Font(bold=True)
            c.font = Font(bold=True)
    ws.cell(row=6 + len(rows) + 1, column=1, value=DISCLAIMER).alignment = Alignment(wrap_text=True)
    _autosize(ws)

    # -------- Plusvalenze RT --------
    ws = wb.create_sheet("Plusvalenze_RT")
    _header(ws, 1, ["Titolo", "Asset", "Long", "Qtà", "Valuta", "Apertura", "Chiusura",
                    "Corrispettivo €", "Costo €", "Commissioni €", "Plus/Minus €",
                    "Cambio apert.", "Cambio chius."])
    for i, row in enumerate(r.rt.rows, start=2):
        ws.append([]) if False else None
        vals = [row.symbol, row.asset_category, "L" if row.is_long else "S", _num(row.qty),
                row.currency, str(row.open_date), str(row.close_date),
                _num(row.corrispettivo_eur), _num(row.costo_eur), _num(row.commissioni_eur),
                _num(row.plus_minus_eur), _num(row.rate_open), _num(row.rate_close)]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=i, column=c, value=v)
            if c in (8, 9, 10, 11):
                cell.number_format = EUR
    _autosize(ws)

    # -------- Dividendi/Interessi RM --------
    ws = wb.create_sheet("Dividendi_Interessi_RM")
    _header(ws, 1, ["Titolo", "Stato", "Stato AdE", "Alq.", "Pay date", "Valuta",
                    "Lordo ccy", "Ritenuta ccy",
                    "Cambio", "Lordo €", "Ritenuta €", "Base imp. €", "Imposta €", "Credito teor. €"])
    ridx = 2
    for d in r.rm.dividends:
        vals = [d.symbol, d.country, getattr(d, "country_ade", ""),
                float(getattr(d, "aliquota", 0.26)), str(d.pay_date), d.currency, _num(d.gross_ccy),
                _num(d.wht_ccy), _num(d.rate), _num(d.gross_eur), _num(d.wht_eur),
                _num(d.base_imponibile_eur), _num(d.imposta_eur), _num(d.credito_teorico_eur)]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=ridx, column=c, value=v)
            if c in (7, 8, 10, 11, 12, 13, 14):
                cell.number_format = EUR
            elif c == 4:
                cell.number_format = "0.0%"
        ridx += 1
    ridx += 1
    ws.cell(row=ridx, column=1, value="INTERESSI").font = Font(bold=True)
    ridx += 1
    _header(ws, ridx, ["Descrizione", "Stato", "Data", "Valuta", "Importo ccy", "Cambio",
                       "Base €", "Imposta €", "Codice"])
    ridx += 1
    for it in r.rm.interests:
        vals = [it.description, it.country, str(it.when), it.currency, _num(it.amount_ccy),
                _num(it.rate), _num(it.base_eur), _num(it.imposta_eur), it.codice_reddito]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=ridx, column=c, value=v)
            if c in (5, 7, 8):
                cell.number_format = EUR
        ridx += 1
    _autosize(ws)

    # -------- Monitoraggio RW/IVAFE --------
    ws = wb.create_sheet("Monitoraggio_RW_IVAFE")
    _header(ws, 1, ["Descrizione", "Cod. bene", "Stato", "Stato AdE", "Cod. valoriz.",
                    "Valore iniz. €",
                    "Valore fin. €", "Giorni", "Quota %", "IVAFE applic.", "Aliquota",
                    "IVAFE €", "Solo monit."])
    for i, w in enumerate(r.rw.rows, start=2):
        vals = [w.descrizione, w.codice_bene, w.stato_estero,
                getattr(w, "stato_estero_ade", w.stato_estero), w.codice_valorizzazione,
                w.valore_iniziale_eur, w.valore_finale_eur, w.giorni, _num(w.quota_pct),
                "Sì" if w.ivafe_applicata else "No", _num(w.ivafe_aliquota), _num(w.ivafe_eur),
                "Sì" if w.solo_monitoraggio else ""]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=i, column=c, value=v)
            if c in (6, 7, 12):
                cell.number_format = EUR
    last = len(r.rw.rows) + 3
    ws.cell(row=last, column=1, value="TOTALE").font = Font(bold=True)
    ws.cell(row=last, column=7, value=r.rw.tot_valore_finale_eur).number_format = EUR
    tot = ws.cell(row=last, column=12, value=_num(r.rw.tot_ivafe_eur))
    tot.number_format = EUR
    tot.font = Font(bold=True)
    if r.rw.ivafe_non_dovuta:
        ws.cell(
            row=last + 1, column=1,
            value=f"IVAFE {r.rw.tot_ivafe_eur:.2f} € ≤ 200 €: VERSAMENTO NON DOVUTO "
                  f"(solo obbligo dichiarativo RW) [art. 19 c.20 DL 201/2011]",
        ).font = Font(bold=True)
    _autosize(ws)

    # -------- Cambi usati --------
    ws = wb.create_sheet("Warning")
    _header(ws, 1, ["Livello", "Codice", "Messaggio"])
    for i, warn in enumerate(r.warnings, start=2):
        ws.cell(row=i, column=1, value=warn.level)
        ws.cell(row=i, column=2, value=warn.code)
        ws.cell(row=i, column=3, value=warn.message).alignment = Alignment(wrap_text=True)
    ws.column_dimensions["C"].width = 90
    _autosize(ws)

    wb.save(path)
