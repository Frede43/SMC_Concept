"""
Breaker Block Detection
Détection des Breaker Blocks (Order Blocks cassés qui deviennent des zones de support/résistance)
"""

import pandas as pd
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum
from loguru import logger


class BreakerType(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class BreakerStatus(Enum):
    ACTIVE = "active"
    TESTED = "tested"
    INVALIDATED = "invalidated"


@dataclass
class BreakerBlock:
    type: BreakerType
    status: BreakerStatus
    index: int
    high: float
    low: float
    original_ob_index: int
    timestamp: pd.Timestamp
    tests_count: int = 0
    
    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2
    
    def is_valid(self) -> bool:
        return self.status != BreakerStatus.INVALIDATED


class BreakerBlockDetector:
    """
    Détecteur de Breaker Blocks.
    
    Un Breaker Block est un ancien Order Block qui a été cassé (mitigé/invalidé).
    Il devient alors une zone de support/résistance inversée.
    
    - Bullish OB cassé -> Bearish Breaker (résistance)
    - Bearish OB cassé -> Bullish Breaker (support)
    """
    
    def __init__(self, max_age_bars: int = 100):
        self.max_age_bars = max_age_bars
        self.breaker_blocks: List[BreakerBlock] = []
        
    def detect_from_broken_obs(self, df: pd.DataFrame, 
                                broken_obs: List) -> List[BreakerBlock]:
        """
        Convertit les Order Blocks cassés en Breaker Blocks.
        
        Args:
            df: DataFrame OHLC
            broken_obs: Liste des Order Blocks invalidés
        """
        logger.debug(f"Detecting breaker blocks from {len(broken_obs)} broken OBs")
        self.breaker_blocks = []
        
        for ob in broken_obs:
            # Un OB bullish cassé devient un Breaker bearish
            # Un OB bearish cassé devient un Breaker bullish
            ob_type = ob.type.value if hasattr(ob.type, 'value') else ob.type
            
            if ob_type == "bullish":
                breaker_type = BreakerType.BEARISH
            else:
                breaker_type = BreakerType.BULLISH
            
            breaker = BreakerBlock(
                type=breaker_type,
                status=BreakerStatus.ACTIVE,
                index=ob.index,
                high=ob.high,
                low=ob.low,
                original_ob_index=ob.index,
                timestamp=ob.timestamp if hasattr(ob, 'timestamp') else pd.Timestamp.now()
            )
            self.breaker_blocks.append(breaker)
        
        # Mettre à jour les statuts
        self._update_status(df)
        
        # Filtrer les vieux breakers
        current_idx = len(df) - 1
        self.breaker_blocks = [
            bb for bb in self.breaker_blocks
            if (current_idx - bb.index) <= self.max_age_bars and bb.is_valid()
        ]
        
        logger.debug(f"Found {len(self.breaker_blocks)} active breaker blocks")
        return self.breaker_blocks
    
    def _update_status(self, df: pd.DataFrame) -> None:
        for bb in self.breaker_blocks:
            if bb.status == BreakerStatus.INVALIDATED:
                continue
            
            for i in range(bb.index + 1, len(df)):
                bar = df.iloc[i]
                
                if bb.type == BreakerType.BULLISH:
                    # Bullish breaker: support, invalidé si cassé vers le bas
                    if bar['close'] < bb.low:
                        bb.status = BreakerStatus.INVALIDATED
                        break
                    if bar['low'] <= bb.high and bar['low'] >= bb.low:
                        bb.status = BreakerStatus.TESTED
                        bb.tests_count += 1
                        
                else:  # BEARISH
                    # Bearish breaker: résistance, invalidé si cassé vers le haut
                    if bar['close'] > bb.high:
                        bb.status = BreakerStatus.INVALIDATED
                        break
                    if bar['high'] >= bb.low and bar['high'] <= bb.high:
                        bb.status = BreakerStatus.TESTED
                        bb.tests_count += 1
    
    def get_nearest_breaker(self, price: float, 
                           breaker_type: Optional[BreakerType] = None) -> Optional[BreakerBlock]:
        valid = [bb for bb in self.breaker_blocks 
                 if bb.is_valid() and (breaker_type is None or bb.type == breaker_type)]
        
        if not valid:
            return None
        
        def distance(bb):
            if price >= bb.low and price <= bb.high:
                return 0
            return min(abs(bb.low - price), abs(bb.high - price))
        
        return min(valid, key=distance)
    
    def is_price_in_breaker(self, price: float) -> tuple:
        for bb in self.breaker_blocks:
            if bb.is_valid() and bb.low <= price <= bb.high:
                return True, bb
        return False, None
