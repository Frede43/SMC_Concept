from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union
import logging
import pandas as pd

logger = logging.getLogger(__name__)

class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"
    STRONG_BUY = "STRONG_BUY"
    STRONG_SELL = "STRONG_SELL"
    WAIT = "WAIT"
    NO_SIGNAL = "NO_SIGNAL"

@dataclass
class TradeSignal:
    signal_type: SignalType
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    reasons: List[str]
    timestamp: Optional[Any] = None
    is_secondary: bool = False
    lot_multiplier: float = 1.0
    symbol: Optional[str] = None
    
    @property
    def risk_reward(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        if risk == 0:
            return 0.0
        return abs(self.take_profit - self.entry_price) / risk
    
@dataclass
class TradeDecision:
    symbol: str
    timestamp: str
    signal_type: str = "NONE"
    final_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    components: Dict[str, Any] = field(default_factory=dict)
    rejection_reason: Optional[str] = None
    should_trade: bool = False
    signal: Optional[TradeSignal] = None
    
    def log(self):
        """Logs the decision details."""
        if self.rejection_reason:
            logger.info(f"🚫 Trade Rejected for {self.symbol}: {self.rejection_reason}")
        else:
            logger.info(f"✅ Trade Accepted for {self.symbol}: {self.signal_type} (Score: {self.final_score})")
