"""Interfaccia a riga di comando di fiscoib.

Esempio:
    python -m fiscoib estratto_2025.xml --anno 2025 --out ./out

Con più file (storico pluriennale) e opzioni:
    python -m fiscoib ib_2023.xml ib_2024.xml ib_2025.xml --anno 2025 \\
        --stato IE --frontiera lordo --out ./out
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal

from .config import FiscoConfig
from .fx.ade_overrides import builtin_overrides
from .fx.rates import RatesProvider
from .pipeline import run
from .reports import quadri_facsimile, raw_export, excel_report, pdf_summary
from .warnings import CRITICAL, WARN


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fiscoib",
        description="Calcolo fiscale italiano (Quadro RW/RT/RM) da report Interactive Brokers.",
    )
    p.add_argument("input", nargs="+", help="File Flex Query XML IBKR (glob ammessi).")
    p.add_argument("--anno", "--year", type=int, required=True, dest="anno",
                   help="Anno d'imposta (es. 2025).")
    p.add_argument("--out", default="./out", help="Cartella di output (default ./out).")
    p.add_argument("--stato", default="IE",
                   help="Codice stato estero del conto per il Quadro RW (IE o US).")
    p.add_argument("--quota", type=str, default="100",
                   help="Quota di possesso %% (default 100).")
    p.add_argument("--frontiera", choices=["lordo", "netto"], default="lordo",
                   help="Base imponibile dividendi (default 'lordo', posizione AdE).")
    p.add_argument("--ivafe-cfd", action="store_true",
                   help="Applica l'IVAFE anche ai CFD (default: solo monitoraggio).")
    p.add_argument("--ivafe-otc", action="store_true",
                   help="Applica l'IVAFE anche alle azioni OTC (default: solo monitoraggio).")
    p.add_argument("--cfd-divadj", choices=["RT", "RM"], default="RT",
                   help="Trattamento dividend adjustment CFD (default RT).")
    p.add_argument("--pil", choices=["RM", "RT"], default="RM",
                   help="Trattamento Payment In Lieu of Dividends (default RM).")
    p.add_argument("--db", default=None,
                   help="Path della cache SQLite dei cambi (default <out>/rates_cache.sqlite).")
    p.add_argument("--offline", action="store_true",
                   help="Non scaricare cambi online (usa solo la cache/override).")
    p.add_argument("--overrides", default=None,
                   help="File JSON con cambi medi mensili ufficiali AdE (override).")
    p.add_argument("--no-ade-builtin", action="store_true",
                   help="Non usare la tabella cambi AdE integrata.")
    p.add_argument("--prior-losses", default=None,
                   help="File JSON {anno: importo} di minusvalenze pregresse riportabili.")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    db_path = args.db or os.path.join(args.out, "rates_cache.sqlite")

    overrides = {} if args.no_ade_builtin else builtin_overrides()
    rates = RatesProvider(db_path=db_path, ade_overrides=overrides, offline=args.offline)
    if args.overrides:
        rates.load_overrides_file(args.overrides)

    config = FiscoConfig(
        tax_year=args.anno,
        account_country=args.stato.upper(),
        ownership_pct=Decimal(args.quota),
        frontiera=args.frontiera,
        ivafe_cfd=args.ivafe_cfd,
        ivafe_otc=args.ivafe_otc,
        cfd_dividend_adjustment=args.cfd_divadj,
        pil_treatment=args.pil,
    )

    prior_losses = None
    if args.prior_losses and os.path.exists(args.prior_losses):
        with open(args.prior_losses, encoding="utf-8") as fh:
            prior_losses = {int(y): Decimal(str(v)) for y, v in json.load(fh).items()}

    try:
        results = run(args.input, config, rates, prior_losses=prior_losses)
    except Exception as exc:  # noqa: BLE001
        print(f"ERRORE: {exc}", file=sys.stderr)
        return 2

    # Output.
    facsimile_txt = quadri_facsimile.render(results)
    with open(os.path.join(args.out, "quadri_facsimile.txt"), "w", encoding="utf-8") as fh:
        fh.write(facsimile_txt)
    raw_export.write_json(results, os.path.join(args.out, "risultati.json"))
    raw_export.write_csv(results, args.out)
    try:
        excel_report.build(results, os.path.join(args.out, f"report_{args.anno}.xlsx"))
    except Exception as exc:  # noqa: BLE001
        print(f"Avviso: Excel non generato ({exc})", file=sys.stderr)
    try:
        pdf_summary.build(results, os.path.join(args.out, f"riepilogo_{args.anno}.pdf"))
    except Exception as exc:  # noqa: BLE001
        print(f"Avviso: PDF non generato ({exc})", file=sys.stderr)

    # Stampa a video il facsimile e un riepilogo warning.
    print(facsimile_txt)
    n_warn = sum(1 for w in results.warnings if w.level in (WARN, CRITICAL))
    if n_warn:
        print(f"\n>>> {n_warn} avvisi da verificare (vedi foglio 'Warning' e PDF).")
    print(f"\nOutput scritti in: {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
