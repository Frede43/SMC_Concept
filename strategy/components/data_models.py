from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
import pandas as pd
from loguru import logger


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    NO_SIGNAL = "no_signal"


@dataclass
class TradeSignal:
    signal_type: SignalType
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    reasons: List[str]
    timestamp: pd.Timestamp
    is_secondary: bool = False  # True si signal iFVG (secondaire)
    lot_multiplier: float = 1.0  # Multiplicateur de lot (0.5 pour signaux secondaires)

    def risk_reward(self) -> float:
        """Calcule le ratio Risque/Rendement"""
        if self.stop_loss == self.entry_price:
            return 0.0
        return abs(self.take_profit - self.entry_price) / abs(self.entry_price - self.stop_loss)


@dataclass
class TradeDecision:
    """
    Bulletin de décision pour le logging et le dashboard
    Trace pourquoi un trade a été pris ou rejeté AVEC les détails.
    """

    symbol: str
    timestamp: str
    signal_type: str
    final_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    components: Dict[str, float] = field(default_factory=dict)  # Score par composant
    is_taken: bool = False
    rejection_reason: str = ""

    def log(self):
        """Log la décision de manière structurée"""
        icon = "✅" if self.is_taken else "❌"
        status = "EXECUTED" if self.is_taken else "REJECTED"

        msg = f"{icon} DECISION [{self.symbol}]: {status} | Score: {self.final_score:.1f}/100"
        if not self.is_taken:
            msg += f" | Reason: {self.rejection_reason}"

        logger.info(msg)

        # Log détaillé en DEBUG
        if self.is_taken or self.final_score > 40:
            logger.debug(f"   Details: {self.metadata}")
