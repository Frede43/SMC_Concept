"""
Optimal Trade Entry (OTE)
Calcul de la zone OTE (Fibonacci 0.618-0.786) selon ICT/SMC
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple
from loguru import logger


@dataclass
class OTEZone:
    swing_high: float
    swing_low: float
    direction: str
    ote_start: float      # 0.618
    ote_end: float        # 0.786
    ote_midpoint: float   # 0.705
    
    @property
    def is_valid(self) -> bool:
        return self.swing_high > self.swing_low


class OTECalculator:
    """
    Calcul de l'Optimal Trade Entry (OTE).
    
    Zone OTE = Retracement Fibonacci entre 0.618 et 0.786
    C'est la zone optimale pour entrer dans un trade après un retracement.
    """
    
    def __init__(self, fib_start: float = 0.618, fib_end: float = 0.786):
        self.fib_start = fib_start
        self.fib_end = fib_end
        self.current_ote: Optional[OTEZone] = None
        
    def calculate(self, swing_high: float, swing_low: float, direction: str) -> OTEZone:
        """
        Calcule la zone OTE.
        
        Args:
            swing_high: Point haut du swing
            swing_low: Point bas du swing
            direction: "BUY" ou "SELL"
        """
        range_size = swing_high - swing_low
        
        if direction.upper() == "BUY":
            # Pour un achat, on mesure du haut vers le bas
            ote_start = swing_high - (range_size * self.fib_start)
            ote_end = swing_high - (range_size * self.fib_end)
            ote_midpoint = swing_high - (range_size * 0.705)
        else:
            # Pour une vente, on mesure du bas vers le haut
            ote_start = swing_low + (range_size * self.fib_start)
            ote_end = swing_low + (range_size * self.fib_end)
            ote_midpoint = swing_low + (range_size * 0.705)
        
        self.current_ote = OTEZone(
            swing_high=swing_high,
            swing_low=swing_low,
            direction=direction,
            ote_start=min(ote_start, ote_end),
            ote_end=max(ote_start, ote_end),
            ote_midpoint=ote_midpoint
        )
        
        logger.debug(f"OTE Zone: {self.current_ote.ote_start:.5f} - {self.current_ote.ote_end:.5f}")
        return self.current_ote
    
    def is_price_in_ote(self, price: float) -> bool:
        if self.current_ote is None:
            return False
        return self.current_ote.ote_start <= price <= self.current_ote.ote_end
    
    def get_entry_price(self) -> Optional[float]:
        if self.current_ote is None:
            return None
        return self.current_ote.ote_midpoint
    
    def calculate_from_df(self, df: pd.DataFrame, direction: str, lookback: int = 20) -> OTEZone:
        recent = df.tail(lookback)
        swing_high = recent['high'].max()
        swing_low = recent['low'].min()
        return self.calculate(swing_high, swing_low, direction)
