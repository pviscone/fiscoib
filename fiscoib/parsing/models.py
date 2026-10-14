"""Modelli dati normalizzati per gli eventi estratti dal Flex Query IBKR.

Ogni modello conserva il dizionario ``raw`` con TUTTI gli attributi originali del
tag XML, così nulla va perso e il resto del codice può accedere a campi non
mappati esplicitamente. I campi tipizzati sono quelli che servono ai motori di
calcolo.

Gli importi sono ``Decimal``. Gli importi monetari sono SEMPRE nella valuta
originale dello strumento (mai nella base currency IBKR, che non è fiscalmente
valida): la conversione in EUR avviene nei motori con i cambi ufficiali italiani.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, Optional

from ..money import dec


# --------------------------------------------------------------------------- #
# Categorie di asset IBKR (attributo assetCategory)
# --------------------------------------------------------------------------- #
STOCK = "STK"
CFD = "CFD"
FXCFD = "FXCFD"
CASH_FX = "CASH"  # operazioni forex spot
OPTION = "OPT"
FUTURE = "FUT"
BOND = "BOND"


@dataclass
class Instrument:
    """Identità di uno strumento finanziario."""

    conid: str
    symbol: str
    description: str = ""
    asset_category: str = ""
    isin: str = ""
    listing_exchange: str = ""
    currency: str = ""
    multiplier: Decimal = Decimal("1")
    sub_category: str = ""  # es. COMMON, ADR, ETF (subCategory IBKR)

    @property
    def is_cfd(self) -> bool:
        return self.asset_category in (CFD, FXCFD)

    @property
    def is_stock(self) -> bool:
        return self.asset_category == STOCK

    @property
    def is_fund(self) -> bool:
        """Quota di OICR/ETF estero.

        Euristica: ``subCategory`` IBKR == 'ETF' oppure ``assetCategory`` in
        FUND/ETF/MUTUAL FUND. Le quote OICR producono redditi di capitale
        (art. 44 c.1 lett. g TUIR), non plusvalenze da redditi diversi.
        """
        if (self.sub_category or "").strip().upper() == "ETF":
            return True
        return (self.asset_category or "").strip().upper() in {"FUND", "ETF", "MUTUAL FUND"}

    @property
    def is_otc(self) -> bool:
        """Azione trattata OTC / non su mercato regolamentato.

        Euristica sul listing exchange (PINK, OTC, OTCBB, EXPM, GREY...).
        """
        le = (self.listing_exchange or "").upper()
        return self.is_stock and le in {"PINK", "OTC", "OTCBB", "OTCMKTS", "EXPM", "GREY", "OTCQB", "OTCQX", ""}

    def key(self) -> str:
        """Chiave stabile per aggregare i lotti dello stesso strumento."""
        return self.conid or f"{self.symbol}|{self.currency}|{self.asset_category}"


@dataclass
class Trade:
    """Una esecuzione (o frazione) di compravendita."""

    instrument: Instrument
    trade_id: str
    transaction_id: str
    trade_date: date
    settle_date: Optional[date]
    buy_sell: str            # BUY / SELL (eventuali CANCEL* già filtrati a monte)
    open_close: str          # O / C / C;O / ""
    quantity: Decimal        # sempre positiva; il segno è dato da buy_sell
    price: Decimal           # prezzo unitario in valuta strumento
    proceeds: Decimal        # ricavi (positivo su vendita, negativo su acquisto)
    commission: Decimal      # commissione IBKR (di norma negativa)
    commission_currency: str
    taxes: Decimal           # imposte di transazione (es. stamp duty)
    currency: str
    notes: str = ""
    fx_rate_to_base: Decimal = Decimal("0")  # SOLO reference, non fiscale
    raw: Dict[str, str] = field(default_factory=dict)

    @property
    def is_buy(self) -> bool:
        return self.buy_sell.upper().startswith("BUY")

    @property
    def signed_quantity(self) -> Decimal:
        return self.quantity if self.is_buy else -self.quantity

    @property
    def abs_commission(self) -> Decimal:
        return abs(self.commission)

    @property
    def abs_taxes(self) -> Decimal:
        return abs(self.taxes)


@dataclass
class CashTransaction:
    """Movimento di cassa: dividendo, ritenuta, interesse, fee, PIL..."""

    instrument: Optional[Instrument]
    transaction_id: str
    tx_type: str        # es. "Dividends", "Withholding Tax", "Broker Interest Received"
    when: date          # data di pagamento / accredito (pay date)
    amount: Decimal     # positivo=incasso, negativo=addebito, in valuta
    currency: str
    description: str = ""
    fx_rate_to_base: Decimal = Decimal("0")
    raw: Dict[str, str] = field(default_factory=dict)


@dataclass
class OpenPosition:
    """Posizione aperta a una data di report (tipicamente 31/12)."""

    instrument: Instrument
    report_date: date
    quantity: Decimal        # con segno (positivo=long, negativo=short)
    mark_price: Decimal      # prezzo di mercato in valuta strumento
    position_value: Decimal  # quantity*mark*multiplier in valuta strumento
    cost_basis_money: Decimal
    currency: str
    side: str = ""
    open_datetime: Optional[date] = None
    raw: Dict[str, str] = field(default_factory=dict)


@dataclass
class CashReportRow:
    """Riga del Cash Report per una valuta (saldi inizio/fine periodo)."""

    currency: str
    from_date: Optional[date]
    to_date: Optional[date]
    starting_cash: Decimal
    ending_cash: Decimal
    ending_settled_cash: Decimal
    raw: Dict[str, str] = field(default_factory=dict)


@dataclass
class CorporateAction:
    """Operazione societaria (split, merge, spin-off, symbol change...)."""

    instrument: Instrument
    transaction_id: str
    when: date
    # Codici ufficiali IBKR: OR,BC,BM,CD,HD,HI,CC,CA,CO,CS,CI,CP,DW,DI,ED,
    # FA,FS,GV,IC,FI,TC,PC,RS,PI,SO,SD,RI,SR,TM,TI,UE,TO.
    # Rilevanti qui: TC=merger, SO=spin-off, FS/RS=forward/reverse split.
    ca_type: str
    description: str
    quantity: Decimal   # variazione di quantità (con segno)
    value: Decimal
    currency: str
    raw: Dict[str, str] = field(default_factory=dict)


@dataclass
class Statement:
    """Contenitore di tutti gli eventi estratti da uno o più file Flex."""

    account_id: str = ""
    base_currency: str = ""
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    trades: list = field(default_factory=list)              # list[Trade]
    cash_transactions: list = field(default_factory=list)   # list[CashTransaction]
    open_positions: list = field(default_factory=list)      # list[OpenPosition]
    cash_report: list = field(default_factory=list)         # list[CashReportRow]
    corporate_actions: list = field(default_factory=list)   # list[CorporateAction]

    def merge(self, other: "Statement") -> None:
        """Unisce un altro Statement in questo (per gestire più file)."""
        if not self.account_id:
            self.account_id = other.account_id
        if not self.base_currency:
            self.base_currency = other.base_currency
        self.trades.extend(other.trades)
        self.cash_transactions.extend(other.cash_transactions)
        self.open_positions.extend(other.open_positions)
        self.cash_report.extend(other.cash_report)
        self.corporate_actions.extend(other.corporate_actions)
        # Il periodo complessivo è l'unione degli intervalli.
        dates_from = [d for d in (self.from_date, other.from_date) if d]
        dates_to = [d for d in (self.to_date, other.to_date) if d]
        if dates_from:
            self.from_date = min(dates_from)
        if dates_to:
            self.to_date = max(dates_to)
