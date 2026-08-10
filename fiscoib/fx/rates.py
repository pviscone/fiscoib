"""Tassi di cambio ufficiali con cache locale SQLite.

Due tipi di cambio, con fonti e usi diversi (cfr. piano):

- ``daily``  : cambio di riferimento GIORNALIERO Banca d'Italia/BCE.
               Usato per plusvalenze (RT) e dividendi/interessi (RM), al giorno
               della transazione / pay date.
- ``monthly``: cambio MEDIO MENSILE. Fiscalmente per il Quadro RW/IVAFE si usa il
               provvedimento mensile dell'Agenzia delle Entrate; l'API Banca
               d'Italia fornisce una media mensile usata come proxy, con
               possibilità di OVERRIDE manuale coi valori ufficiali AdE
               (``ade_overrides``).

Convenzione dei tassi Banca d'Italia: "incerto per certo", cioè
``rate`` = quante unità di valuta estera valgono 1 EUR (es. EUR/USD ≈ 1.08).
Quindi per convertire un importo in valuta estera in EUR:  ``eur = importo / rate``.

La cache scarica ONLINE solo le date/valute non ancora presenti localmente.
Per EUR il tasso è sempre 1 (nessuna conversione).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable, Dict, Optional, Tuple

from ..money import dec

BDI_BASE = "https://tassidicambio.bancaditalia.it/terzevalute-wf-web/rest/v1.0"

# Numero massimo di giorni lavorativi indietro per il fallback (festivi/weekend).
MAX_FALLBACK_DAYS = 7


class RateNotAvailable(Exception):
    """Sollevata quando un cambio non è reperibile né in cache né online."""


# Fetcher: funzione (kind, currency, ...) -> Decimal | None. Iniettabile per test.
DailyFetcher = Callable[[str, date], Optional[Decimal]]
MonthlyFetcher = Callable[[str, int, int], Optional[Decimal]]


def _default_daily_fetcher(currency: str, ref: date) -> Optional[Decimal]:
    return _bdi_fetch_daily(currency, ref)


def _default_monthly_fetcher(currency: str, year: int, month: int) -> Optional[Decimal]:
    return _bdi_fetch_monthly(currency, year, month)


def _http_get_json(url: str, params: Dict[str, str]) -> Optional[dict]:
    """GET JSON con requests; ritorna None su qualsiasi errore di rete."""
    try:
        import requests  # import locale: i test offline non lo toccano

        resp = requests.get(
            url, params=params, headers={"Accept": "application/json"}, timeout=20
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _bdi_fetch_daily(currency: str, ref: date) -> Optional[Decimal]:
    # NB: nell'API Banca d'Italia ``currencyIsoCode`` indica la valuta BASE:
    # passando EUR si ottengono i tassi "valuta estera per 1 EUR" (avgRate),
    # coerenti con i cambi ufficiali usati dall'Agenzia delle Entrate.
    data = _http_get_json(
        f"{BDI_BASE}/dailyRates",
        {"referenceDate": ref.isoformat(), "currencyIsoCode": "EUR", "lang": "en"},
    )
    return _extract_rate(data, currency)


def _bdi_fetch_monthly(currency: str, year: int, month: int) -> Optional[Decimal]:
    data = _http_get_json(
        f"{BDI_BASE}/monthlyAverageRates",
        {"year": str(year), "month": str(month), "currencyIsoCode": "EUR", "lang": "en"},
    )
    return _extract_rate(data, currency)


def _extract_rate(data: Optional[dict], currency: str) -> Optional[Decimal]:
    """Estrae il tasso della valuta ``currency`` (campo ``isoCode``) dalla
    risposta EUR-based della Banca d'Italia. ``avgRate`` = unità di valuta estera
    per 1 EUR."""
    if not data:
        return None
    rates = data.get("rates") or []
    for r in rates:
        if r.get("isoCode") == currency or r.get("currencyIsoCode") == currency:
            val = r.get("avgRate")
            if val is not None:
                try:
                    return dec(val)
                except Exception:
                    return None
    return None


class RatesProvider:
    """Fornitore di cambi con cache SQLite persistente."""

    def __init__(
        self,
        db_path: str,
        daily_fetcher: Optional[DailyFetcher] = None,
        monthly_fetcher: Optional[MonthlyFetcher] = None,
        ade_overrides: Optional[Dict[Tuple[str, int, int], Decimal]] = None,
        offline: bool = False,
    ):
        self.db_path = db_path
        self._daily_fetcher = daily_fetcher or _default_daily_fetcher
        self._monthly_fetcher = monthly_fetcher or _default_monthly_fetcher
        self._ade = ade_overrides or {}
        self.offline = offline
        self.fetch_count = 0  # per i test: verifica che la cache eviti chiamate
        self._ensure_db()

    # ------------------------------------------------------------------ #
    # Cache SQLite
    # ------------------------------------------------------------------ #
    def _ensure_db(self) -> None:
        d = os.path.dirname(self.db_path)
        if d:
            os.makedirs(d, exist_ok=True)
        con = sqlite3.connect(self.db_path)
        con.execute(
            """CREATE TABLE IF NOT EXISTS rates (
                   d TEXT NOT NULL,      -- 'YYYY-MM-DD' per daily, 'YYYY-MM' per monthly
                   currency TEXT NOT NULL,
                   kind TEXT NOT NULL,   -- 'daily' | 'monthly'
                   rate TEXT NOT NULL,
                   source TEXT,
                   PRIMARY KEY (d, currency, kind)
               )"""
        )
        con.commit()
        con.close()

    def _cache_get(self, key: str, currency: str, kind: str) -> Optional[Decimal]:
        con = sqlite3.connect(self.db_path)
        row = con.execute(
            "SELECT rate FROM rates WHERE d=? AND currency=? AND kind=?",
            (key, currency, kind),
        ).fetchone()
        con.close()
        return dec(row[0]) if row else None

    def _cache_put(self, key: str, currency: str, kind: str, rate: Decimal, source: str) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(
            "INSERT OR REPLACE INTO rates (d, currency, kind, rate, source) VALUES (?,?,?,?,?)",
            (key, currency, kind, str(rate), source),
        )
        con.commit()
        con.close()

    def preload(self, key: str, currency: str, kind: str, rate: Decimal, source: str = "manual") -> None:
        """Inserisce manualmente un tasso (usato dai test e per dati offline)."""
        self._cache_put(key, currency, kind, dec(rate), source)

    # ------------------------------------------------------------------ #
    # API pubblica
    # ------------------------------------------------------------------ #
    def daily_rate(self, currency: str, ref: date) -> Decimal:
        """Tasso giornaliero (1 EUR = X valuta). EUR -> 1."""
        currency = currency.upper()
        if currency in ("EUR", ""):
            return Decimal("1")

        # Fallback su giorni precedenti per festivi/weekend.
        for back in range(0, MAX_FALLBACK_DAYS + 1):
            d = ref - timedelta(days=back)
            key = d.isoformat()
            cached = self._cache_get(key, currency, "daily")
            if cached is not None:
                return cached
            if not self.offline:
                self.fetch_count += 1
                rate = self._daily_fetcher(currency, d)
                if rate is not None:
                    self._cache_put(key, currency, "daily", rate, "bancaditalia")
                    return rate
        raise RateNotAvailable(
            f"Cambio giornaliero non disponibile per {currency} intorno al {ref.isoformat()}. "
            f"Verifica la connessione o inserisci il tasso manualmente."
        )

    def monthly_rate(self, currency: str, year: int, month: int) -> Decimal:
        """Tasso medio mensile (1 EUR = X valuta). EUR -> 1.

        Priorità: override ufficiale AdE > cache > fetch Banca d'Italia.
        """
        currency = currency.upper()
        if currency in ("EUR", ""):
            return Decimal("1")

        override = self._ade.get((currency, year, month))
        if override is not None:
            return dec(override)

        key = f"{year:04d}-{month:02d}"
        cached = self._cache_get(key, currency, "monthly")
        if cached is not None:
            return cached
        if not self.offline:
            self.fetch_count += 1
            rate = self._monthly_fetcher(currency, year, month)
            if rate is not None:
                self._cache_put(key, currency, "monthly", rate, "bancaditalia")
                return rate
        raise RateNotAvailable(
            f"Cambio medio mensile non disponibile per {currency} {key}. "
            f"Per il Quadro RW/IVAFE usa il provvedimento AdE del mese e inseriscilo "
            f"come override."
        )

    # ------------------------------------------------------------------ #
    # Conversioni
    # ------------------------------------------------------------------ #
    def to_eur_daily(self, amount: Decimal, currency: str, ref: date) -> Decimal:
        """Converte in EUR con il cambio giornaliero (RT/RM)."""
        rate = self.daily_rate(currency, ref)
        return dec(amount) / rate

    def to_eur_monthly(self, amount: Decimal, currency: str, year: int, month: int) -> Decimal:
        """Converte in EUR con il cambio medio mensile (RW/IVAFE)."""
        rate = self.monthly_rate(currency, year, month)
        return dec(amount) / rate

    def load_overrides_file(self, path: str) -> None:
        """Carica override AdE da JSON: lista di {currency, year, month, rate}."""
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read().strip()
        if not content:
            return
        data = json.loads(content)
        for item in data:
            self._ade[(item["currency"].upper(), int(item["year"]), int(item["month"]))] = dec(
                item["rate"]
            )
