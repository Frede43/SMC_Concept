"""
Order Block Detection
Détection des Order Blocks selon les Smart Money Concepts
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Optional, Tuple
from enum import Enum
from loguru import logger


class OBType(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class OBStatus(Enum):
    FRESH = "fresh"
    TESTED = "tested"
    MITIGATED = "mitigated"
    INVALIDATED = "invalidated"


@dataclass
class OrderBlock:
    type: OBType
    status: OBStatus
    index: int
    high: float
    low: float
    open_price: float
    close_price: float
    timestamp: pd.Timestamp
    impulse_strength: float = 0.0
    tests_count: int = 0
    volume: float = 0.0
    
    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2
    
    @property
    def height(self) -> float:
        return self.high - self.low
    
    @property
    def body_high(self) -> float:
        return max(self.open_price, self.close_price)
    
    @property
    def body_low(self) -> float:
        return min(self.open_price, self.close_price)

    @property
    def top(self) -> float:
        return self.high

    @property
    def bottom(self) -> float:
        return self.low
    
    def is_valid(self) -> bool:
        return self.status in [OBStatus.FRESH, OBStatus.TESTED]


class OrderBlockDetector:
    # 🆕 DYNAMIC IMBALANCE RATIOS PAR TIMEFRAME
    # Recommandation Expert: Adapter le ratio selon la volatilité du TF
    IMBALANCE_RATIOS = {
        "M1": 1.8,   # Très strict sur scalping
        "M5": 1.6,
        "M15": 1.5,  # Standard
        "M30": 1.4,
        "H1": 1.3,   # 🆕 Plus flexible sur swing
        "H4": 1.2,   # 🆕 Encore plus flexible
        "D1": 1.1    # 🆕 Minimal sur daily
    }
    
    def __init__(self, max_age_bars: int = 50, min_imbalance_ratio: float = None, 
                 use_mitigation: bool = True, pip_value: float = 0.0001, 
                 timeframe: str = "M15"):
        """
        Args:
            max_age_bars: Âge maximum d'un OB en nombre de barres
            min_imbalance_ratio: Ratio minimum (si None, auto-détecté par TF)
            use_mitigation: Tracker le statut des OBs
            pip_value: Valeur d'un pip
            timeframe: 🆕 Timeframe pour adapter le ratio automatiquement
        """
        self.max_age_bars = max_age_bars
        self.use_mitigation = use_mitigation
        self.pip_value = pip_value
        self.timeframe = timeframe
        self.order_blocks: List[OrderBlock] = []
        
        # 🆕 Auto-détection du ratio basé sur le timeframe
        if min_imbalance_ratio is None:
            self.min_imbalance_ratio = self.IMBALANCE_RATIOS.get(timeframe, 1.5)
            logger.info(f"🎯 OB Ratio auto-adapté: {self.min_imbalance_ratio} pour {timeframe}")
        else:
            self.min_imbalance_ratio = min_imbalance_ratio
            logger.info(f"🎯 OB Ratio manuel: {self.min_imbalance_ratio}")
        
    def detect(self, df: pd.DataFrame, structure_breaks: List = None) -> List[OrderBlock]:
        logger.debug(f"Detecting order blocks on {len(df)} bars")
        self.order_blocks = []
        
        for i in range(3, len(df) - 1):
            bullish_ob = self._check_bullish_ob(df, i)
            if bullish_ob:
                self.order_blocks.append(bullish_ob)
            
            bearish_ob = self._check_bearish_ob(df, i)
            if bearish_ob:
                self.order_blocks.append(bearish_ob)
        
        if self.use_mitigation:
            self._update_ob_status(df)
        
        current_idx = len(df) - 1
        self.order_blocks = [
            ob for ob in self.order_blocks 
            if (current_idx - ob.index) <= self.max_age_bars and ob.status != OBStatus.INVALIDATED
        ]
        
        logger.debug(f"Found {len(self.order_blocks)} valid order blocks")
        return self.order_blocks
    
    def _check_bullish_ob(self, df: pd.DataFrame, idx: int) -> Optional[OrderBlock]:
        current = df.iloc[idx]
        prev = df.iloc[idx - 1]
        
        if prev['close'] >= prev['open']:
            return None
        if current['close'] <= current['open']:
            return None
        
        prev_body = abs(prev['close'] - prev['open'])
        current_body = abs(current['close'] - current['open'])
        
        if prev_body == 0 or current_body / prev_body < self.min_imbalance_ratio:
            return None
        if current['close'] < prev['high']:
            return None
        
        return OrderBlock(
            type=OBType.BULLISH, status=OBStatus.FRESH, index=idx - 1,
            high=prev['high'], low=prev['low'], open_price=prev['open'],
            close_price=prev['close'], impulse_strength=current_body / prev_body,
            timestamp=df.index[idx - 1] if isinstance(df.index, pd.DatetimeIndex) else pd.Timestamp.now(),
            volume=prev.get('volume', 0)
        )
    
    def _check_bearish_ob(self, df: pd.DataFrame, idx: int) -> Optional[OrderBlock]:
        current = df.iloc[idx]
        prev = df.iloc[idx - 1]
        
        if prev['close'] <= prev['open']:
            return None
        if current['close'] >= current['open']:
            return None
        
        prev_body = abs(prev['close'] - prev['open'])
        current_body = abs(current['close'] - current['open'])
        
        if prev_body == 0 or current_body / prev_body < self.min_imbalance_ratio:
            return None
        if current['close'] > prev['low']:
            return None
        
        return OrderBlock(
            type=OBType.BEARISH, status=OBStatus.FRESH, index=idx - 1,
            high=prev['high'], low=prev['low'], open_price=prev['open'],
            close_price=prev['close'], impulse_strength=current_body / prev_body,
            timestamp=df.index[idx - 1] if isinstance(df.index, pd.DatetimeIndex) else pd.Timestamp.now(),
            volume=prev.get('volume', 0)
        )
    
    def _update_ob_status(self, df: pd.DataFrame) -> None:
        for ob in self.order_blocks:
            if ob.status == OBStatus.INVALIDATED:
                continue
            
            for i in range(ob.index + 2, len(df)):
                bar = df.iloc[i]
                
                if ob.type == OBType.BULLISH:
                    if bar['close'] < ob.low:
                        ob.status = OBStatus.INVALIDATED
                        break
                    if bar['low'] <= ob.high and bar['low'] >= ob.low:
                        ob.status = OBStatus.TESTED
                        ob.tests_count += 1
                else:
                    if bar['close'] > ob.high:
                        ob.status = OBStatus.INVALIDATED
                        break
                    if bar['high'] >= ob.low and bar['high'] <= ob.high:
                        ob.status = OBStatus.TESTED
                        ob.tests_count += 1
    
    def get_nearest_ob(self, current_price: float, ob_type: Optional[OBType] = None) -> Optional[OrderBlock]:
        valid_obs = [ob for ob in self.order_blocks if ob.is_valid() and (ob_type is None or ob.type == ob_type)]
        if not valid_obs:
            return None
        
        def distance(ob):
            if current_price >= ob.low and current_price <= ob.high:
                return 0
            return min(abs(ob.low - current_price), abs(ob.high - current_price))
        
        return min(valid_obs, key=distance)
    
    def get_bullish_obs(self) -> List[OrderBlock]:
        return [ob for ob in self.order_blocks if ob.type == OBType.BULLISH and ob.is_valid()]
    
    def get_bearish_obs(self) -> List[OrderBlock]:
        return [ob for ob in self.order_blocks if ob.type == OBType.BEARISH and ob.is_valid()]
    
    def is_price_in_ob(self, price: float, ob_type: Optional[OBType] = None) -> Tuple[bool, Optional[OrderBlock]]:
        for ob in self.order_blocks:
            if not ob.is_valid():
                continue
            if ob_type and ob.type != ob_type:
                continue
            if price >= ob.low and price <= ob.high:
                return True, ob
        return False, None
