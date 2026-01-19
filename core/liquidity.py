"""
Liquidity Detection
Détection des zones de liquidité et des sweeps selon SMC
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Optional, Tuple
from enum import Enum
from loguru import logger


class LiquidityType(Enum):
    BUY_SIDE = "buy_side"    # Liquidité au-dessus (stop loss des shorts)
    SELL_SIDE = "sell_side"  # Liquidité en dessous (stop loss des longs)


class LiquidityStatus(Enum):
    UNTOUCHED = "untouched"
    SWEPT = "swept"
    PARTIAL_SWEEP = "partial_sweep"


@dataclass
class LiquidityZone:
    type: LiquidityType
    status: LiquidityStatus
    level: float
    index: int
    timestamp: pd.Timestamp
    touch_count: int = 0
    is_equal_level: bool = False
    swept_index: Optional[int] = None
    
    def is_valid(self) -> bool:
        return self.status == LiquidityStatus.UNTOUCHED


@dataclass
class LiquiditySweep:
    type: LiquidityType
    liquidity_level: float
    sweep_index: int
    sweep_high: float
    sweep_low: float
    close_price: float
    timestamp: pd.Timestamp
    is_confirmed: bool = False


class LiquidityDetector:
    """
    Détecteur de liquidité selon les Smart Money Concepts.
    
    Identifie:
    - Equal Highs / Equal Lows (niveaux à liquidité)
    - Liquidity Sweeps (chasse de liquidité)
    - Buy-side / Sell-side liquidity
    """
    
    def __init__(self, equal_level_pips: float = 3, sweep_confirmation_bars: int = 3,
                 pip_value: float = 0.0001, lookback: int = 20):
        self.equal_level_pips = equal_level_pips
        self.sweep_confirmation_bars = sweep_confirmation_bars
        self.pip_value = pip_value
        self.lookback = lookback
        self.liquidity_zones: List[LiquidityZone] = []
        self.sweeps: List[LiquiditySweep] = []
        
    def detect(self, df: pd.DataFrame, swing_highs: List = None, 
               swing_lows: List = None, pip_value: float = None) -> Tuple[List[LiquidityZone], List[LiquiditySweep]]:
        logger.debug(f"Detecting liquidity on {len(df)} bars")
        self.liquidity_zones = []
        self.sweeps = []
        
        # Utiliser le pip value dynamique s'il est fourni (pour supporter JPY/Crypto/Gold)
        current_pip = pip_value if pip_value is not None else self.pip_value
        tolerance = self.equal_level_pips * current_pip
        
        # Détecter Equal Highs (buy-side liquidity)
        self._detect_equal_levels(df, is_high=True, tolerance=tolerance)
        
        # Détecter Equal Lows (sell-side liquidity)
        self._detect_equal_levels(df, is_high=False, tolerance=tolerance)
        
        # Utiliser les swing points si fournis
        if swing_highs:
            for sh in swing_highs:
                zone = LiquidityZone(
                    type=LiquidityType.BUY_SIDE,
                    status=LiquidityStatus.UNTOUCHED,
                    level=sh.price if hasattr(sh, 'price') else sh['price'],
                    index=sh.index if hasattr(sh, 'index') else sh['index'],
                    timestamp=pd.Timestamp.now()
                )
                self.liquidity_zones.append(zone)
        
        if swing_lows:
            for sl in swing_lows:
                zone = LiquidityZone(
                    type=LiquidityType.SELL_SIDE,
                    status=LiquidityStatus.UNTOUCHED,
                    level=sl.price if hasattr(sl, 'price') else sl['price'],
                    index=sl.index if hasattr(sl, 'index') else sl['index'],
                    timestamp=pd.Timestamp.now()
                )
                self.liquidity_zones.append(zone)
        
        # Détecter les sweeps
        self._detect_sweeps(df)
        
        logger.debug(f"Found {len(self.liquidity_zones)} liquidity zones and {len(self.sweeps)} sweeps")
        return self.liquidity_zones, self.sweeps
    
    def _detect_equal_levels(self, df: pd.DataFrame, is_high: bool, tolerance: float) -> None:
        price_col = 'high' if is_high else 'low'
        liquidity_type = LiquidityType.BUY_SIDE if is_high else LiquidityType.SELL_SIDE
        
        # ⚡ OPTIMISATION: Conversion en Numpy array pour éviter 20,000 appels à iloc
        prices = df[price_col].values
        n = len(prices)
        
        for i in range(self.lookback, n):
            current_price = prices[i]
            # Fenêtre glissante sur numpy array (Ultra rapide)
            window = prices[i - self.lookback : i]
            
            # Vectorized numpy comparison
            # Compter combien de prix dans la fenêtre sont proches du prix actuel
            similar_mask = np.abs(window - current_price) <= tolerance
            similar_count = np.sum(similar_mask)
            
            if similar_count >= 2:
                zone = LiquidityZone(
                    type=liquidity_type,
                    status=LiquidityStatus.UNTOUCHED,
                    level=float(current_price),
                    index=i,
                    timestamp=df.index[i],
                    touch_count=int(similar_count),
                    is_equal_level=True
                )
                
                # Éviter les doublons (avec tolérance)
                is_duplicate = False
                for z in self.liquidity_zones:
                    if z.type == liquidity_type and abs(z.level - zone.level) <= tolerance:
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    self.liquidity_zones.append(zone)
    
    def _detect_sweeps(self, df: pd.DataFrame) -> None:
        # Optimisation: Convertir colonnes en numpy une seule fois
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        n = len(df)
        
        for zone in self.liquidity_zones:
            if zone.status != LiquidityStatus.UNTOUCHED:
                continue
            
            # Commencer la recherche APRES la création de la zone
            start_idx = zone.index + 1
            if start_idx >= n:
                continue
                
            # Slicing numpy à partir de start_idx
            # On cherche le PREMIER événement de sweep, donc on garde la boucle mais sur arrays
            
            for i in range(start_idx, n):
                h, l, c = highs[i], lows[i], closes[i]
                
                if zone.type == LiquidityType.BUY_SIDE:
                    # Sweep si le prix dépasse le niveau (mèche) puis clôture en dessous
                    if h > zone.level and c < zone.level:
                        sweep = LiquiditySweep(
                            type=zone.type,
                            liquidity_level=zone.level,
                            sweep_index=i,
                            sweep_high=float(h),
                            sweep_low=float(l),
                            close_price=float(c),
                            timestamp=df.index[i],
                            is_confirmed=True
                        )
                        self.sweeps.append(sweep)
                        zone.status = LiquidityStatus.SWEPT
                        zone.swept_index = i
                        break
                        
                else:  # SELL_SIDE
                    if l < zone.level and c > zone.level:
                        sweep = LiquiditySweep(
                            type=zone.type,
                            liquidity_level=zone.level,
                            sweep_index=i,
                            sweep_high=float(h),
                            sweep_low=float(l),
                            close_price=float(c),
                            timestamp=df.index[i],
                            is_confirmed=True
                        )
                        self.sweeps.append(sweep)
                        zone.status = LiquidityStatus.SWEPT
                        zone.swept_index = i
                        break
    
    def get_recent_sweep(self, direction: Optional[str] = None) -> Optional[LiquiditySweep]:
        if not self.sweeps:
            return None
        
        if direction:
            liq_type = LiquidityType.SELL_SIDE if direction.upper() == "BUY" else LiquidityType.BUY_SIDE
            filtered = [s for s in self.sweeps if s.type == liq_type]
            return filtered[-1] if filtered else None
        
        return self.sweeps[-1]
    
    def get_nearest_liquidity(self, price: float, direction: Optional[str] = None) -> Optional[LiquidityZone]:
        valid_zones = [z for z in self.liquidity_zones if z.is_valid()]
        
        if direction:
            liq_type = LiquidityType.BUY_SIDE if direction.upper() == "BUY" else LiquidityType.SELL_SIDE
            valid_zones = [z for z in valid_zones if z.type == liq_type]
        
        if not valid_zones:
            return None
        
        return min(valid_zones, key=lambda z: abs(z.level - price))
