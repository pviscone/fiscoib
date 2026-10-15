"""Orchestrazione: dal file Flex ai risultati dei tre quadri."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from decimal import Decimal

from .config import FiscoConfig
from .engines.capital_gains import RTResult, compute_rt
from .engines.income import RMResult, compute_rm
from .engines.lots import build_closures
from .engines.monitoring import RWResult, compute_rw
from .fx.rates import RatesProvider
from .parsing.flex_parser import load
from .parsing.models import Statement
from .prorata import FundGovQuotas
from .warnings import WarningCollector


@dataclass
class Results:
    statement: Statement
    config: FiscoConfig
    rt: RTResult
    rm: RMResult
    rw: RWResult
    warnings: WarningCollector

    @property
    def imposta_totale(self) -> Decimal:
        """Totale imposte DA VERSARE: l'IVAFE ≤ 200€ non è dovuta (resta dovuto
        il solo monitoraggio RW); l'imposta sui gain OICR (reddito di capitale)
        è versata con il RM (codice 1242) ma è esposta separatamente."""
        return (
            self.rt.rt27_imposta
            + self.rm.tot_imposta_rm
            + self.rt.oicr_imposta
            + self.rw.ivafe_da_versare
        )


def run(
    statement_or_paths,
    config: FiscoConfig,
    rates: RatesProvider,
    prior_losses: Optional[Dict[int, Decimal]] = None,
    warnings: Optional[WarningCollector] = None,
    gov_bonds: Optional[set] = None,
    fund_gov_quotas: Optional[FundGovQuotas] = None,
) -> Results:
    """Esegue l'intera pipeline.

    ``statement_or_paths`` può essere una lista di path (glob ammessi) o uno
    ``Statement`` già caricato (utile nei test).
    """
    warnings = warnings or WarningCollector()

    if isinstance(statement_or_paths, Statement):
        statement = statement_or_paths
    else:
        paths = (
            statement_or_paths
            if isinstance(statement_or_paths, (list, tuple))
            else [statement_or_paths]
        )
        statement = load(list(paths), warnings=warnings)

    # 1) LIFO -> chiusure realizzate (su tutto lo storico).
    closures, _book = build_closures(
        statement.trades, statement.corporate_actions, warnings
    )

    # 2) Redditi di capitale (RM) + componenti c-quater per RT.
    rm_kwargs = {"gov_bonds": gov_bonds} if gov_bonds else {}
    if fund_gov_quotas is not None:
        rm_kwargs["fund_gov_quotas"] = fund_gov_quotas
    rm = compute_rm(statement.cash_transactions, rates, config, warnings, **rm_kwargs)

    # 3) Plusvalenze (RT), includendo eventuali dividend adjustment CFD / PIL→RT.
    rt = compute_rt(
        closures,
        rates,
        config,
        prior_losses=prior_losses,
        extra_components=rm.cquater_components,
        warnings=warnings,
        fund_gov_quotas=fund_gov_quotas,
    )

    # 4) Monitoraggio RW / IVAFE.
    rw = compute_rw(statement, rates, config, warnings)

    return Results(statement=statement, config=config, rt=rt, rm=rm, rw=rw, warnings=warnings)
