"""Generazione automatica dei file JSON di input di fiscoib.

Legge gli statement IBKR e produce i modelli da completare prima dell'uso:

- ``gov_bonds.bozza.json`` — lista degli ISIN/simboli di OBBLIGAZIONI rilevate
  (cedole "Bond Interest Received" + trades su asset BOND) da cui ELIMINARE gli
  emittenti corporate prima di passarla con ``--gov-bonds``: il file causa la
  riduzione d'imposta al 12,5%, quindi uno scheletro auto-inclusivo di tutti i
  bond rischierebbe imposte più basse del dovuto. Resta il passo umano minimo.
- ``fund_gov_quota.bozza.json`` — mappa ISIN -> quota 0 degli ETF/fondi che
  contengono obbligazioni (euristica sul nome: gli equity-puri tipo MSCI World
  sono esclusi perché il pro-rata non li riguarda); le quote reali vanno copiate
  dai portali fiscali dei gestori prima di passarla con ``--fund-gov-quota``.
- ``overrides.json`` — cambi medi mensili Banca d'Italia per le valute presenti
  nello statement nell'anno d'imposta: è il file ``--overrides`` ufficiale già
  calcolato (vuole il tasso in convenzione 1 EUR = X valuta).
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from .fx.ade_overrides import builtin_overrides
from .fx.rates import RateNotAvailable, RatesProvider
from .parsing.flex_parser import load
from .parsing.models import Instrument, Statement

BOND_TX_TYPE = "Bond Interest Received"

# Asset category IBKR che identifica uno strumento obbligazionario negoziato.
BOND_ASSET = "BOND"


@dataclass
class InstrumentInfo:
    ident: str          # ISIN se disponibile, altrimenti simbolo/conid
    symbol: str
    description: str
    isin: str
    conid: str
    origin: str         # da dove è stato rilevato (debug)


def _ident_of(inst: Instrument) -> str:
    return (inst.isin or inst.symbol or inst.conid or "").strip()


def _info(inst: Instrument, origin: str) -> InstrumentInfo:
    return InstrumentInfo(
        ident=_ident_of(inst),
        symbol=(inst.symbol or "").strip(),
        description=(inst.description or "").strip(),
        isin=(inst.isin or "").strip(),
        conid=(inst.conid or "").strip(),
        origin=origin,
    )


def collect_bond_issuers(stmt: Statement) -> List[InstrumentInfo]:
    """Strumenti obbligazionari rilevati (cedole + trades su asset BOND).

    Risultato de-duplicato per ISIN/simbolo, indipendentemente dall'anno: il
    file gov-bonds viene usato per classificare le cedole di qualunque anno.
    """
    found: Dict[str, InstrumentInfo] = {}

    def add(inst: Optional[Instrument], origin: str) -> None:
        if inst is None:
            return
        ident = _ident_of(inst)
        if ident:
            found.setdefault(ident, _info(inst, origin))

    for c in stmt.cash_transactions:
        if c.tx_type == BOND_TX_TYPE and getattr(c, "instrument", None):
            add(c.instrument, "cedola Bond Interest")

    for t in stmt.trades:
        inst = getattr(t, "instrument", None)
        if inst and (inst.asset_category or "").strip().upper() == BOND_ASSET:
            add(inst, "trade asset BOND")

    return [found[k] for k in sorted(found)]


def collect_funds(stmt: Statement) -> List[InstrumentInfo]:
    """Quote OICR/ETF (is_fund) rilevate in trades, movimenti e posizioni aperte."""
    found: Dict[str, InstrumentInfo] = {}

    def add(inst: Optional[Instrument], origin: str) -> None:
        if inst is None or not inst.is_fund:
            return
        ident = _ident_of(inst)
        if ident:
            found.setdefault(ident, _info(inst, origin))

    for t in stmt.trades:
        add(t.instrument, "trade")
    for c in stmt.cash_transactions:
        add(getattr(c, "instrument", None), "movimento cash")
    for p in stmt.open_positions:
        add(getattr(p, "instrument", None), "posizione aperta")

    return [found[k] for k in sorted(found)]


# --------------------------------------------------------------------------- #
# Classificazione euristica governativi vs corporate (offline)
# --------------------------------------------------------------------------- #
# Token sovrani così come tipicamente compaiono in simbolo/descrizione IBKR.
# Euristica a favore della prudenza: solo pattern chiaramente sovrani; dubbi
# finiscono nella revisione manuale.
SOVEREIGN_TOKENS = (
    # Italia
    "BTPS", "BTP ", "CCT ", "CTOS", "BTPITALIA", "BTPGREEN", "BDCTS",
    # USA
    "TREASURY", "T-BOND", "T-BILL", "T NOTE", "USTB",
    # Germania
    "DBR ", "OBL ", "BUND", "FEDERAL REPUBLIC OF GERMANY",
    # Francia
    "OAT ", "FRTR",
    # Regno Unito
    "GILT", "UKT ",
    # Spagna
    "SPGB", "KINGDOM OF SPAIN",
    # Giappone
    "JGB ",
    # Sovranazionali (sempre assimilati)
    "EUROPEAN UNION", "EFSF", "ESM", "EIB ", "IBRD", "WORLD BANK",
)

# Paesi SICURAMENTE white list (prudente: sottoinsieme della lista AdE); issuers
# di altri paesi finiscono tra i "da verificare" e restano fuori dal file.
WHITELIST_COUNTRIES = frozenset(
    {
        "IT", "FR", "DE", "ES", "US", "GB", "JP", "AT", "BE", "NL", "PT",
        "IE", "FI", "GR", "LU", "DK", "SE", "NO", "CH", "CA",
        "EU",  # organismi UE
    }
)

# Token sovrani di paesi tipicamente NON in white list: evidenziati a parte.
NON_WHITELIST_TOKENS = (
    "TURKEY", "BRAZIL", "MEXICO", "ARGENTINA", "EGYPT", "INDONESIA",
)


def _isin_country(info: InstrumentInfo) -> str:
    return info.isin[:2].upper() if len(info.isin) >= 2 else ""


def classify_bonds(
    issuers: List[InstrumentInfo],
) -> Dict[str, List[InstrumentInfo]]:
    """Divide gli emittenti in tre gruppi (euristica, sempre da revisionare).

    - ``govies``: token sovrano + paese white list conservatore: finiscono nel
      file bozza;
    - ``non_whitelisted``: token sovrano ma paese fuori lista conservativa (es.
      emergenti): restano al 26% a meno di verifica che il paese è in white
      list AdE;
    - ``da_verificare``: nessun token sovrano riconosciuto (tipicamente
      corporate veri, ma la revisione resta obbligatoria).
    """
    groups: Dict[str, List[InstrumentInfo]] = {
        "govies": [],
        "non_whitelisted": [],
        "da_verificare": [],
    }
    for info in issuers:
        text = f"{info.symbol} {info.description}".upper()
        is_sov = any(tok in text for tok in SOVEREIGN_TOKENS)
        is_non_wl = any(tok in text for tok in NON_WHITELIST_TOKENS)
        if is_sov and not is_non_wl and _isin_country(info) in WHITELIST_COUNTRIES:
            groups["govies"].append(info)
        elif is_sov or is_non_wl:
            groups["non_whitelisted"].append(info)
        else:
            groups["da_verificare"].append(info)
    return groups


def write_gov_bonds_template(govies: List[InstrumentInfo], path: str) -> None:
    """JSON valido con i soli emittenti white-list probabili (euristica).

    I gruppi "da verificare" e "non-whitelisted" restano FUORI dal file
    (cedole al 26%: mai meno imposta del dovuto) e sono stampati a video.
    """
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([i.ident for i in govies], fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# Indici/nomi tipicamente AZIONARI puri: se presenti (e nessun token bond), il
# fondo ha quota govies = 0 e non serve nel template.
EQUITY_HINTS = (
    "MSCI", "S&P", "FTSE", "STOXX", "NASDAQ", "ACWI", "ALL-WORLD", "DAX",
    "EM IMI", "EQUITY", "DIVIDEND ARISTOCRAT", "REIT", "STOCK",
)

# Token obbligazionari tipici: se presenti, il fondo serve SEMPRE nel template
# (ha precedenza sui token azionari).
BOND_ETF_HINTS = (
    "BOND", "GOVT", "TREASUR", "AGGREGATE", "SOVEREIGN", "GILT", "CORP",
    "CREDIT", "YIELD", "INFLATION", "DURATION", "FLOATING", "IG", "MUNI",
    "TIPS", "DEBT", "FIXED INCOME", "RATE",
)


def classify_funds(
    funds: List[InstrumentInfo],
) -> Dict[str, List[InstrumentInfo]]:
    """ETF/fondi: ``bond_like`` (serve il dato pro-rata) vs ``equity_only``.

    Equity-puro → quota govies sempre 0 → escluso dal template. Incerti restano
    in ``bond_like`` (prudente: meglio un rigo in più che perdersi il pro-rata).
    """
    groups: Dict[str, List[InstrumentInfo]] = {"bond_like": [], "equity_only": []}
    for f in funds:
        text = f"{f.symbol} {f.description}".upper()
        has_bond = any(h in text for h in BOND_ETF_HINTS)
        has_equity = any(h in text for h in EQUITY_HINTS)
        if has_equity and not has_bond:
            groups["equity_only"].append(f)
        else:
            groups["bond_like"].append(f)
    return groups


def write_fund_quota_template(funds: List[InstrumentInfo], path: str) -> None:
    """Mappa ISIN -> 0.0: quota prudente (26% pieno) finché non compilata."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({f.ident: 0.0 for f in funds}, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def write_overrides(
    stmt: Statement,
    tax_year: int,
    rates: RatesProvider,
    path: str,
) -> List[str]:
    """Cambi medi mensili per le valute dello statement nell'anno d'imposta.

    Convenzione BdI/AdE 1 EUR = X valuta, stesso schema del file --overrides.
    Restituisce l'elenco delle valute senza dato (fetch fallito/offline).
    """
    currencies = {
        (v or "").strip().upper()
        for v in [
            *(getattr(t, "currency", "") for t in stmt.trades),
            *(getattr(c, "currency", "") for c in stmt.cash_transactions),
            *(getattr(p, "currency", "") for p in stmt.open_positions),
        ]
        if v
    }
    currencies.discard("EUR")

    rows = []
    missing: List[str] = []
    for ccy in sorted(currencies):
        for month in range(1, 13):
            try:
                rate = rates.monthly_rate(ccy, tax_year, month)
            except (RateNotAvailable, RuntimeError, ValueError, ConnectionError, OSError):
                rate = None
            if rate is None:
                missing.append(ccy)
                break
            rows.append(
                {
                    "currency": ccy,
                    "year": tax_year,
                    "month": month,
                    "rate": float(rate),
                }
            )

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return sorted(set(missing))


# --------------------------------------------------------------------------- #
def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m fiscoib.build_inputs",
        description=(
            "Genera i modelli JSON di input di fiscoib dagli statement IBKR: "
            "gov_bonds.bozza.json, fund_gov_quota.bozza.json e overrides.json."
        ),
    )
    p.add_argument("input", nargs="+", help="File Flex Query XML IBKR (glob ammessi).")
    p.add_argument("--anno", "--year", type=int, required=True, dest="anno",
                   help="Anno d'imposta (serve per overrides.json).")
    p.add_argument("--out", default=".", help="Cartella di output (default: corrente).")
    p.add_argument("--db", default=None,
                   help="Path della cache SQLite dei cambi (default <out>/rates_cache.sqlite).")
    p.add_argument("--offline", action="store_true",
                   help="Non scaricare cambi online (usa solo cache/override integrate).")
    return p


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    stmt = load(list(args.input))

    bonds = collect_bond_issuers(stmt)
    funds = collect_funds(stmt)

    bond_groups = classify_bonds(bonds)
    fund_groups = classify_funds(funds)
    gov_path = os.path.join(args.out, "gov_bonds.bozza.json")
    quota_path = os.path.join(args.out, "fund_gov_quota.bozza.json")
    write_gov_bonds_template(bond_groups["govies"], gov_path)
    write_fund_quota_template(fund_groups["bond_like"], quota_path)

    db_path = args.db or os.path.join(args.out, "rates_cache.sqlite")
    rates = RatesProvider(db_path=db_path, ade_overrides=builtin_overrides(),
                          offline=args.offline)
    overrides_path = os.path.join(args.out, "overrides.json")
    missing_ccy = write_overrides(stmt, args.anno, rates, overrides_path)

    # ------------------------- Riepilogo interattivo ----------------------- #
    print(f"Letti {len(stmt.trades)} trades e {len(stmt.cash_transactions)} movimenti cash.")
    print()

    print("=== gov_bonds.bozza.json ===")
    if not bonds:
        print("  Nessuna obbligazione rilevata: usa --gov-bonds solo se compri bond diretti.")
    for i in bond_groups["govies"]:
        print(
            f"  [govy?]   {i.ident:<16} {i.description[:40]:<42} (da: {i.origin})"
        )
    for i in bond_groups["non_whitelisted"]:
        print(
            f"  [paese?]  {i.ident:<16} {i.description[:40]:<42} "
            f"(paese ISIN {_isin_country(i) or '?'}: verificare white list AdE)"
        )
    for i in bond_groups["da_verificare"]:
        print(
            f"  [corp?]   {i.ident:<16} {i.description[:40]:<42} (presunto corporate: fuori dal file)"
        )
    if bonds:
        print(
            "  >> Il file contiene solo il gruppo [govy?] (euristica offline: token\n"
            "     sovrani + paese ISIN white list conservatore). REVISIONA SEMPRE:\n"
            "     aggiungi a mano i governativi non riconosciuti e verifica i [paese?]\n"
            "     contro la white list AdE; i [corp?] restano al 26% come da default.\n"
            "     Pronto dopo revisione: rinomina gov_bonds.bozza.json -> gov_bonds.json."
        )
    print()

    print("=== fund_gov_quota.bozza.json ===")
    if not funds:
        print("  Nessun ETF/fondo rilevato.")
    for f in fund_groups["bond_like"]:
        print(
            f"  [bond?]    {f.ident:<16} {f.description[:40]:<42} (da: {f.origin})"
        )
    for f in fund_groups["equity_only"]:
        print(
            f"  [azionario]{f.ident:<16} {f.description[:40]:<42} (escluso: quota govies = 0)"
        )
    if funds:
        print(
            "  >> Nel file solo i fondi [bond?] (euristica su nome: equity-puri esclusi;\n"
            "     gli incerti restano). Compila ogni quota con la MEDIA di titoli di Stato\n"
            "     white list dal portale fiscale del gestore (iShares, Vanguard, ...).\n"
            "     Quote a 0.0 = 26% pieno. Per-anno usa {\"ISIN\": {\"2024\": 0.58}}."
        )
    print()

    print("=== overrides.json ===")
    print("  Cambi medi mensili Banca d'Italia pronti per --overrides.")
    if missing_ccy:
        print(f"  !! Valute senza dato ({', '.join(missing_ccy)}): "+
              ("attiva la rete (togli --offline) o compila a mano."))
    print()
    print(f"File scritti in: {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
