"""
Fair Value Gap (FVG) Detection
Détection des FVG et iFVG selon les Smart Money Concepts
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict
from enum import Enum
from loguru import logger


class FVGType(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class FVGStatus(Enum):
    FRESH = "fresh"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"


@dataclass
class FairValueGap:
    type: FVGType
    status: FVGStatus
    index: int
    high: float
    low: float
    timestamp: pd.Timestamp
    fill_percentage: float = 0.0
    is_inverse: bool = False
    is_ob_confluence: bool = False  # 🆕 Setup A+: FVG à l'intérieur/proche d'un OB
    
    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2
    
    @property
    def size(self) -> float:
        return self.high - self.low
    
    @property
    def is_a_plus_setup(self) -> bool:
        return self.is_ob_confluence
        
    def is_valid(self) -> bool:
        return self.status != FVGStatus.FILLED

# ... [La classe FVGDetector reste la même jusqu'à la fin] ...




class FVGDetector:
    """
    Détecteur de Fair Value Gaps (OPTIMISÉ).
    
    Un FVG est un déséquilibre créé par 3 bougies:
    - Bullish FVG: low de bougie 3 > high de bougie 1
    - Bearish FVG: high de bougie 3 < low de bougie 1
    """
    
    def __init__(self, min_gap_pips: float = 5, max_age_bars: int = 50,
                 fill_percentage: float = 50, pip_value: float = 0.0001):
        self.min_gap_pips = min_gap_pips
        self.max_age_bars = max_age_bars
        self.fill_percentage = fill_percentage
        self.pip_value = pip_value
        self.fvgs: List[FairValueGap] = []
        self.ifvgs: List[FairValueGap] = []
        
    def detect(self, df: pd.DataFrame) -> Tuple[List[FairValueGap], List[FairValueGap]]:
        # Fast exit if not enough data
        if len(df) < 3:
            return [], []
            
        logger.debug(f"Detecting FVGs on {len(df)} bars (Optimized)...")
        self.fvgs = []
        self.ifvgs = []
        
        # Prepare numpy arrays for speed
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        times = df.index
        
        # Calculate minimum gap size
        min_gap = self.min_gap_pips * self.pip_value
        
        # --- VECTORIZED DETECTION ---
        # Shifted arrays to align candles:
        # We want to compare candle i (3rd) with candle i-2 (1st)
        # Array Indices:
        # candle1 (i-2): 0 to N-3
        # candle2 (i-1): 1 to N-2
        # candle3 (i):   2 to N-1
        
        h1 = highs[:-2] 
        l1 = lows[:-2] 
        l3 = lows[2:]   
        h3 = highs[2:]
        
        # Calculate Gaps
        bull_gaps = l3 - h1
        bear_gaps = l1 - h3
        
        # Find indices where conditions are met
        # Note: These indices 'k' correspond to the index of candle1 (start of window)
        bull_candidates = np.where((l3 > h1) & (bull_gaps >= min_gap))[0]
        bear_candidates = np.where((h3 < l1) & (bear_gaps >= min_gap))[0]
        
        current_idx = len(df) - 1
        
        # --- PROCESS BULLISH FVGs ---
        for k in bull_candidates:
            # Indices mapping:
            # k = index of candle 1
            # k+1 = index of candle 2 (Middle of FVG) -> This is the FVG index
            # k+2 = index of candle 3
            # Future data starts at k+3
            
            fvg_idx = int(k + 1)
            
            # Skip if too old (optimization: don't process if it will be filtered anyway)
            if (current_idx - fvg_idx) > self.max_age_bars:
                continue
                
            fvg = FairValueGap(
                type=FVGType.BULLISH,
                status=FVGStatus.FRESH,
                index=fvg_idx,
                high=float(l3[k]),   # Top of gap (Low of candle 3)
                low=float(h1[k]),    # Bottom of gap (High of candle 1)
                timestamp=times[fvg_idx],
                fill_percentage=0.0
            )
            
            # Check filling efficiently
            # We look at future price action starting from candle 3+1 (k+3)
            future_lows = lows[k+3:]
            
            if len(future_lows) > 0:
                # Check for full fill (Price crossed below fvg.low)
                full_fills_mask = future_lows <= fvg.low
                
                if np.any(full_fills_mask):
                    fvg.status = FVGStatus.FILLED
                    fvg.fill_percentage = 100.0
                    
                    # Store fill index for iFVG detection
                    # First index where fill occurred relative to future_lows start
                    rel_fill_idx = np.argmax(full_fills_mask)
                    abs_fill_idx = k + 3 + rel_fill_idx
                    
                    # --- CHECK FOR iFVG (INVERSE FVG) ---
                    # Logic: FVG filled -> Price closes ABOVE midpoint later (Reclamation) -> Retest
                    # Simplified for backtest speed: 
                    # If filled, check if price later respects the zone as support
                    
                    # We need to look AFTER the fill
                    if abs_fill_idx + 1 < len(df):
                        post_fill_closes = closes[abs_fill_idx+1:]
                        post_fill_lows = lows[abs_fill_idx+1:]
                        
                        # Check for reclamation (Close > Midpoint)
                        reclamation_mask = post_fill_closes > fvg.midpoint
                        if np.any(reclamation_mask):
                            # Found a potential iFVG setup
                            idx_reclaim = np.argmax(reclamation_mask)
                            
                            # Check if it holds (Low <= fvg.high) - simple check
                            # Create iFVG at the reclamation point
                            ifvg = FairValueGap(
                                type=FVGType.BULLISH,
                                status=FVGStatus.FRESH,
                                index=int(abs_fill_idx + 1 + idx_reclaim),
                                high=fvg.high,
                                low=fvg.low,
                                timestamp=times[int(abs_fill_idx + 1 + idx_reclaim)],
                                is_inverse=True
                            )
                            self.ifvgs.append(ifvg)
                            
                else:
                    # Partial Fill Check
                    # Lowest low in future
                    min_low = np.min(future_lows)
                    if min_low < fvg.high:
                        # Calculated fill %
                        fvg_size = fvg.high - fvg.low
                        covered = fvg.high - min_low
                        pct = (covered / fvg_size) * 100
                        fvg.fill_percentage = min(100.0, pct)
                        
                        if fvg.fill_percentage >= self.fill_percentage:
                            fvg.status = FVGStatus.FILLED
                        else:
                            fvg.status = FVGStatus.PARTIALLY_FILLED
            
            self.fvgs.append(fvg)
            
        # --- PROCESS BEARISH FVGs ---
        for k in bear_candidates:
            fvg_idx = int(k + 1)
            
            if (current_idx - fvg_idx) > self.max_age_bars:
                continue
                
            fvg = FairValueGap(
                type=FVGType.BEARISH,
                status=FVGStatus.FRESH,
                index=fvg_idx,
                high=float(l1[k]),   # Top of gap (Low of candle 1)
                low=float(h3[k]),    # Bottom of gap (High of candle 3)
                timestamp=times[fvg_idx],
                fill_percentage=0.0
            )
            
            # Check filling
            future_highs = highs[k+3:]
            
            if len(future_highs) > 0:
                # Check for full fill (Price crossed above fvg.high)
                full_fills_mask = future_highs >= fvg.high
                
                if np.any(full_fills_mask):
                    fvg.status = FVGStatus.FILLED
                    fvg.fill_percentage = 100.0
                    
                    # iFVG Detection
                    rel_fill_idx = np.argmax(full_fills_mask)
                    abs_fill_idx = k + 3 + rel_fill_idx
                    
                    if abs_fill_idx + 1 < len(df):
                        post_fill_closes = closes[abs_fill_idx+1:]
                        
                        # Reclamation: Close < Midpoint
                        reclamation_mask = post_fill_closes < fvg.midpoint
                        if np.any(reclamation_mask):
                            idx_reclaim = np.argmax(reclamation_mask)
                            
                            ifvg = FairValueGap(
                                type=FVGType.BEARISH,
                                status=FVGStatus.FRESH,
                                index=int(abs_fill_idx + 1 + idx_reclaim),
                                high=fvg.high,
                                low=fvg.low,
                                timestamp=times[int(abs_fill_idx + 1 + idx_reclaim)],
                                is_inverse=True
                            )
                            self.ifvgs.append(ifvg)
                            
                else:
                    # Partial Fill
                    max_high = np.max(future_highs)
                    if max_high > fvg.low:
                        fvg_size = fvg.high - fvg.low
                        covered = max_high - fvg.low
                        pct = (covered / fvg_size) * 100
                        fvg.fill_percentage = min(100.0, pct)
                        
                        if fvg.fill_percentage >= self.fill_percentage:
                            fvg.status = FVGStatus.FILLED
                        else:
                            fvg.status = FVGStatus.PARTIALLY_FILLED
            
            self.fvgs.append(fvg)
            
        logger.debug(f"Found {len(self.fvgs)} FVGs and {len(self.ifvgs)} iFVGs")
        return self.fvgs, self.ifvgs

    def get_nearest_fvg(self, price: float, fvg_type: Optional[FVGType] = None) -> Optional[FairValueGap]:
        valid_fvgs = [f for f in self.fvgs if f.is_valid() and (fvg_type is None or f.type == fvg_type)]
        if not valid_fvgs:
            return None
        
        def distance(fvg):
            if price >= fvg.low and price <= fvg.high:
                return 0
            return min(abs(fvg.low - price), abs(fvg.high - price))
        
        return min(valid_fvgs, key=distance)
    
    def is_price_in_fvg(self, price: float) -> Tuple[bool, Optional[FairValueGap]]:
        for fvg in self.fvgs:
            if not fvg.is_valid():
                continue
            if price >= fvg.low and price <= fvg.high:
                return True, fvg
        return False, None
    
    def get_bullish_fvgs(self) -> List[FairValueGap]:
        return [f for f in self.fvgs if f.type == FVGType.BULLISH and f.is_valid()]
    
    def get_bearish_fvgs(self) -> List[FairValueGap]:
        return [f for f in self.fvgs if f.type == FVGType.BEARISH and f.is_valid()]
    
    # ==================== ENHANCED iFVG METHODS ====================
    
    def get_bullish_ifvgs(self) -> List[FairValueGap]:
        """Retourne les iFVG bullish actifs (ancien bearish FVG devenu support)."""
        return [f for f in self.ifvgs if f.type == FVGType.BULLISH and f.is_valid()]
    
    def get_bearish_ifvgs(self) -> List[FairValueGap]:
        """Retourne les iFVG bearish actifs (ancien bullish FVG devenu résistance)."""
        return [f for f in self.ifvgs if f.type == FVGType.BEARISH and f.is_valid()]
    
    def is_price_in_ifvg(self, price: float) -> Tuple[bool, Optional[FairValueGap]]:
        """Vérifie si le prix est dans un iFVG."""
        for ifvg in self.ifvgs:
            if not ifvg.is_valid():
                continue
            if price >= ifvg.low and price <= ifvg.high:
                return True, ifvg
        return False, None
    
    def get_ifvg_signal(self, current_price: float, trend: str = None) -> Tuple[str, float, str]:
        """
        Génère un signal de trading basé sur l'interaction avec un iFVG.
        """
        logger.debug(f"🔍 iFVG Signal Check: Price={current_price:.5f}, Trend={trend}, iFVGs count={len(self.ifvgs)}")
        
        in_ifvg, ifvg = self.is_price_in_ifvg(current_price)
        
        if not in_ifvg or ifvg is None:
            logger.debug(f"   ❌ Prix PAS dans un iFVG")
            return "NEUTRAL", 0.0, "Prix pas dans un iFVG"
        
        logger.debug(f"   ✅ Prix DANS iFVG {ifvg.type.value}: [{ifvg.low:.5f}-{ifvg.high:.5f}]")
        
        # iFVG Bullish (ancien bearish FVG) = Support maintenant
        if ifvg.type == FVGType.BULLISH:
            confidence = 65.0  # Réduit de 75% à 65% pour plus de flexibilité
            if trend and trend.lower() == "bullish":
                confidence = 85.0
                logger.debug(f"   🔥 iFVG Bullish + Trend Bullish = {confidence}% confidence")
            else:
                logger.debug(f"   ⚡ iFVG Bullish sans alignement = {confidence}% confidence")
            reason = f"Prix dans iFVG Bullish (Support) [{ifvg.low:.5f}-{ifvg.high:.5f}]"
            return "BUY", confidence, reason
        
        # iFVG Bearish (ancien bullish FVG) = Résistance maintenant
        elif ifvg.type == FVGType.BEARISH:
            confidence = 65.0  # Réduit de 75% à 65% pour plus de flexibilité
            if trend and trend.lower() == "bearish":
                confidence = 85.0
                logger.debug(f"   🔥 iFVG Bearish + Trend Bearish = {confidence}% confidence")
            else:
                logger.debug(f"   ⚡ iFVG Bearish sans alignement = {confidence}% confidence")
            reason = f"Prix dans iFVG Bearish (Résistance) [{ifvg.low:.5f}-{ifvg.high:.5f}]"
            return "SELL", confidence, reason
        
        return "NEUTRAL", 0.0, "iFVG type inconnu"
    
    def check_ob_confluence(self, order_blocks: List) -> None:
        """
        Vérifie la confluence entre les FVGs détectés et une liste d'Order Blocks.
        Un FVG situé près/dans un OB est un signal très fort.
        """
        if not order_blocks:
            return
            
        for fvg in self.fvgs:
            if not fvg.is_valid():
                continue
                
            # Pour chaque OB, vérifier s'il chevauche le FVG
            for ob in order_blocks:
                # Filtrer par direction (Bullish FVG doit être avec Bullish OB)
                if fvg.type.value != ob.type.value:
                    continue
                    
                # Vérification de chevauchement (Overlap)
                overlap = False
                if fvg.type == FVGType.BULLISH:
                    # Le FVG doit être au-dessus ou dans l'OB
                    # Cas 1: Chevauchement direct
                    if (fvg.low <= ob.high) and (fvg.high >= ob.low): # Overlap
                        overlap = True
                    # Cas 2: Proximité (FVG formé juste après)
                    elif abs(fvg.low - ob.high) < (ob.height * 0.5): # Très proche
                        overlap = True
                
                else: # Bearish
                    # Cas 1: Chevauchement
                    if (fvg.high >= ob.low) and (fvg.low <= ob.high):
                        overlap = True
                    # Cas 2: Proximité
                    elif abs(fvg.high - ob.low) < (ob.height * 0.5):
                        overlap = True
                        
                if overlap:
                    fvg.is_ob_confluence = True
                    break
                    
    def get_all_zones_info(self) -> Dict:
        """Retourne un résumé de toutes les zones FVG/iFVG."""
        # Calculer combien ont une confluence OB
        confluence_count = len([f for f in self.fvgs if f.is_ob_confluence])
        
        return {
            "fvg_count": len(self.fvgs),
            "bullish_fvg": len(self.get_bullish_fvgs()),
            "bearish_fvg": len(self.get_bearish_fvgs()),
            "ifvg_count": len(self.ifvgs),
            "bullish_ifvg": len(self.get_bullish_ifvgs()),
            "bearish_ifvg": len(self.get_bearish_ifvgs()),
            "a_plus_setups": confluence_count
        }
