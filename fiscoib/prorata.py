"""Pro-rata titoli di Stato white list per quote OICR (ETF/fondi).

Regola (art. 2, comma 1-quater, D.L. 138/2011; Circolare AdE 19/E/2014):
i risultati di gestione di un OICR maturano, per la quota media di titoli di
Stato italiani ed equiparati "white list" detenuti nel portafoglio del fondo,
l'aliquota ridotta del 12,5% anziché il 26%. L'aliquota effettiva è quindi:

    aliquota_eff = 26% - 13,5% x quota_media_govies

dove la quota media è riferita al periodo di possesso dell'investitore. Il
dato non è negli statement IBKR: i gestori (iShares, Vanguard, ...) lo
pubblicano sui propri portali fiscali; qui è un input dell'utente in JSON.

Formato atteso (chiave = ISIN, simbolo o conid IBKR — uno qualsiasi basta):

    {
      "IE00B4L5Y983": 0.575,                     // quota costante (scorciatoia)
      "IE00B3RBWM25": {"2023": 0.55, "2024": 0.58}  // quota media per anno
    }

Convenzioni prudenti:
- anni non presenti nella mappa contribuiscono con quota 0 (aliquota piena
  26% sulla relativa frazione di periodo);
- strumento assente dal file: aliquota piena 26% + warning PRORATA_DA_CLASSIFICARE;
- per gli ETF (costo medio ponderato) il "periodo di possesso" è [primo acquisto,
  vendita]: con posizioni aggregate a medio ponderato è l'approssimazione
  disponibile e più difendibile;
- per le distribuzioni, il cui periodo di maturazione non è noto, si usa la
  quota media dell'anno solare di pagamento.

Default 0 + warning => mai meno imposta del dovuto in caso di dato mancante.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, FrozenSet, Optional, Tuple

from .money import ZERO

# Aliquota ridotta titoli di Stato e assimilati white list (D.P.R. 795/1979;
# D.Lgs. 239/1996). Parametro normativo stabile.
ALIQUOTA_WHITE_LIST = Decimal("0.125")

# Codici warning emessi dai motori che usano il prorata.
CODE_PRORATA_MANCANTE = "PRORATA_DA_CLASSIFICARE"
CODE_PRORATA_ANNI_PARZIALI = "PRORATA_ANNI_PARZIALI"


def effective_rate(base: Decimal, quota: Decimal) -> Decimal:
    """Aliquota effettiva con pro-rata titoli di Stato.

    ``base`` è l'aliquota ordinaria (26%), ``quota`` la quota media di titoli di
    Stato white list nel periodo: la differenza (base - 12,5%) è abbuonata in
    proporzione alla quota.
    """
    return base - (base - ALIQUOTA_WHITE_LIST) * quota


@dataclass(frozen=True)
class QuotaInfo:
    """Esito del calcolo della quota media su un periodo."""

    quota: Decimal
    missing_years: Tuple[int, ...] = ()


class FundGovQuotas:
    """Quote medie di titoli di Stato white list per fondo, con lookup
    per ISIN/simbolo/conid e media pesata sui giorni di possesso."""

    def __init__(self, data: Dict[str, Dict[int, Decimal]]):
        # data: ident.upper() -> {anno: quota in [0,1]}
        self.data = data
        self.idents: FrozenSet[str] = frozenset(data)

    # ------------------------------------------------------------------ #
    @classmethod
    def from_json_dict(cls, data) -> "FundGovQuotas":
        if not isinstance(data, dict):
            raise ValueError(
                "il file deve contenere un oggetto JSON {ISIN/simbolo: quota}"
            )
        parsed: Dict[str, Dict[int, Decimal]] = {}

        def to_quota(v, what: str) -> Decimal:
            try:
                q = Decimal(str(v).strip())
            except (InvalidOperation, AttributeError):
                raise ValueError(f"quota non valida per {what}: {v!r}") from None
            if not (Decimal("0") <= q <= Decimal("1")):
                raise ValueError(
                    f"quota fuori range [0, 1] per {what}: {v!r} (es. 0.575 = 57,5%)"
                )
            return q

        for ident, value in data.items():
            key = str(ident).strip().upper()
            if not key:
                raise ValueError(f"identificativo vuoto nel file prorata: {ident!r}")
            if isinstance(value, dict):
                years: Dict[int, Decimal] = {}
                for y, q in value.items():
                    ys = str(y).strip()
                    if not (ys.isdigit() and len(ys) == 4):
                        raise ValueError(f"anno non valido per {key}: {y!r}")
                    years[int(ys)] = to_quota(q, f"{key}/{ys}")
                parsed[key] = years
            else:
                # Scorciatoia: quota costante, estesa a tutti gli anni dal
                # periodo di possesso (anno corrente ± ampio buffer).
                q = to_quota(value, key)
                now = _dt.date.today().year
                parsed[key] = {y: q for y in range(now - 50, now + 2)}
        return cls(parsed)

    @classmethod
    def load(cls, path: str) -> "FundGovQuotas":
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return cls.from_json_dict(data)

    # ------------------------------------------------------------------ #
    def lookup(self, *idents: str) -> Optional[Dict[int, Decimal]]:
        """Restituisce la mappa anno->quota del primo identificativo presente."""
        for ident in idents:
            if ident and str(ident).strip().upper() in self.data:
                return self.data[str(ident).strip().upper()]
        return None

    def average_quota(
        self,
        idents,
        d_start: _dt.date,
        d_end: _dt.date,
    ) -> Optional[QuotaInfo]:
        """Quota media pesata sui giorni di possesso di ogni anno solare.

        ``idents``: sequenza di identificativi candidati (isin, simbolo, conid).
        Gli anni non coperti dal file pesano 0 (scelta prudente) e sono
        restituiti in ``missing_years``. Anni fuori dai dati del gestore ma
        coperti dalla scorciatoia costante non sono mai "missing".
        """
        if d_start is None or d_end is None or d_end < d_start:
            return None
        year_map = self.lookup(*[str(i) for i in idents if i])
        if year_map is None:
            return None

        tot_days = Decimal("0")
        weighted = ZERO
        missing = []
        for y in range(d_start.year, d_end.year + 1):
            a = max(d_start, _dt.date(y, 1, 1))
            b = min(d_end, _dt.date(y, 12, 31))
            days = Decimal((b - a).days + 1)  # convenzione inclusiva del repo
            tot_days += days
            if y in year_map:
                weighted += days * year_map[y]
            else:
                missing.append(y)

        if tot_days == 0:
            return QuotaInfo(ZERO, tuple(missing))
        return QuotaInfo(weighted / tot_days, tuple(missing))
