"""
Premium/Discount Zones
Calcul des zones Premium et Discount selon SMC
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Tuple, Optional
from enum import Enum
from loguru import logger


class ZoneType(Enum):
    PREMIUM = "premium"      # Au-dessus de 50% - zone de vente
    DISCOUNT = "discount"    # En dessous de 50% - zone d'achat
    EQUILIBRIUM = "equilibrium"  # Autour de 50%


@dataclass
class PDZone:
    type: ZoneType
    range_high: float
    range_low: float
    equilibrium: float
    premium_start: float
    discount_end: float
    current_zone: ZoneType
    current_percentage: float


class PremiumDiscountZones:
    """
    Calcul des zones Premium et Discount.
    
    - Premium: Zone au-dessus de 50% du range (idéal pour vendre)
    - Discount: Zone en dessous de 50% du range (idéal pour acheter)
    - Equilibrium: Point à 50% du range
    """
    
    def __init__(self, equilibrium_buffer: float = 5, pip_value: float = 0.0001):
        self.equilibrium_buffer = equilibrium_buffer  # Buffer en pips
        self.pip_value = pip_value
        self.current_zone: Optional[PDZone] = None
        
    def calculate(self, df: pd.DataFrame, swing_high: float = None, 
                  swing_low: float = None, lookback: int = 50) -> PDZone:
        """
        Calcule les zones Premium/Discount.
        
        Args:
            df: DataFrame OHLC
            swing_high: Swing high manuel (optionnel)
            swing_low: Swing low manuel (optionnel)
            lookback: Période pour trouver le range
        """
        # Déterminer le range
        if swing_high is None or swing_low is None:
            recent_data = df.tail(lookback)
            range_high = recent_data['high'].max()
            range_low = recent_data['low'].min()
        else:
            range_high = swing_high
            range_low = swing_low
        
        range_size = range_high - range_low
        equilibrium = range_low + (range_size * 0.5)
        
        buffer = self.equilibrium_buffer * self.pip_value
        premium_start = equilibrium + buffer
        discount_end = equilibrium - buffer
        
        # Déterminer la zone actuelle
        current_price = df.iloc[-1]['close']
        # Calcul du pourcentage brut (peut être hors 0-100 si prix hors range)
        raw_percentage = ((current_price - range_low) / range_size * 100) if range_size > 0 else 50
        # Pourcentage clampé pour la logique (0-100)
        current_percentage = max(0, min(100, raw_percentage))
        
        # Déterminer la zone basée sur le prix réel
        if current_price > premium_start:
            current_zone = ZoneType.PREMIUM
        elif current_price < discount_end:
            current_zone = ZoneType.DISCOUNT
        else:
            current_zone = ZoneType.EQUILIBRIUM
        
        logger.debug(f"P/D Calc: price={current_price:.5f}, range=[{range_low:.5f}-{range_high:.5f}], "
                    f"eq={equilibrium:.5f}, raw%={raw_percentage:.1f}%, zone={current_zone.value}")
        
        self.current_zone = PDZone(
            type=current_zone,
            range_high=range_high,
            range_low=range_low,
            equilibrium=equilibrium,
            premium_start=premium_start,
            discount_end=discount_end,
            current_zone=current_zone,
            current_percentage=current_percentage
        )
        
        logger.debug(f"P/D Zone: {current_zone.value} ({current_percentage:.1f}%)")
        return self.current_zone
    
    def is_in_discount(self, price: float = None) -> bool:
        if self.current_zone is None:
            return False
        price = price or self.current_zone.range_low
        return price < self.current_zone.discount_end
    
    def is_in_premium(self, price: float = None) -> bool:
        if self.current_zone is None:
            return False
        price = price or self.current_zone.range_high
        return price > self.current_zone.premium_start
    
    def get_optimal_entry_zone(self, direction: str) -> str:
        if direction.upper() == "BUY":
            return "discount"
        elif direction.upper() == "SELL":
            return "premium"
        return "any"
    
    def is_valid_entry(self, direction: str, price: float = None) -> bool:
        if self.current_zone is None:
            return True
        
        if price is None:
            zone = self.current_zone.current_zone
        else:
            if price > self.current_zone.premium_start:
                zone = ZoneType.PREMIUM
            elif price < self.current_zone.discount_end:
                zone = ZoneType.DISCOUNT
            else:
                zone = ZoneType.EQUILIBRIUM
        
        if direction.upper() == "BUY":
            return zone in [ZoneType.DISCOUNT, ZoneType.EQUILIBRIUM]
        elif direction.upper() == "SELL":
            return zone in [ZoneType.PREMIUM, ZoneType.EQUILIBRIUM]
        
        return True
    
    def get_fib_levels(self) -> dict:
        if self.current_zone is None:
            return {}
        
        range_size = self.current_zone.range_high - self.current_zone.range_low
        
        return {
            0.0: self.current_zone.range_low,
            0.236: self.current_zone.range_low + (range_size * 0.236),
            0.382: self.current_zone.range_low + (range_size * 0.382),
            0.5: self.current_zone.equilibrium,
            0.618: self.current_zone.range_low + (range_size * 0.618),
            0.786: self.current_zone.range_low + (range_size * 0.786),
            1.0: self.current_zone.range_high
        }
