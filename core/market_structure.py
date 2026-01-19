"""
Market Structure Analysis
Détection des BOS (Break of Structure), CHoCH (Change of Character),
et identification des Swing Highs/Lows
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Optional, Tuple
from enum import Enum
from loguru import logger


class Trend(Enum):
    """Direction de la tendance"""
    BULLISH = "bullish"
    BEARISH = "bearish"
    RANGING = "ranging"


class StructureType(Enum):
    """Type de structure"""
    BOS = "bos"         # Break of Structure (continuation)
    CHOCH = "choch"     # Change of Character (reversal)
    HH = "hh"           # Higher High
    HL = "hl"           # Higher Low
    LH = "lh"           # Lower High
    LL = "ll"           # Lower Low


@dataclass
class SwingPoint:
    """Point de swing (high ou low)"""
    index: int
    price: float
    timestamp: pd.Timestamp
    is_high: bool
    confirmed: bool = False
    broken: bool = False
    
    def __repr__(self):
        swing_type = "High" if self.is_high else "Low"
        return f"Swing{swing_type}(idx={self.index}, price={self.price:.5f})"


@dataclass
class StructureBreak:
    """Cassure de structure (BOS ou CHoCH)"""
    type: StructureType
    direction: Trend
    break_index: int
    break_price: float
    swing_index: int
    swing_price: float
    timestamp: pd.Timestamp
    
    def __repr__(self):
        return f"{self.type.value.upper()}({self.direction.value}, idx={self.break_index}, price={self.break_price:.5f})"


class MarketStructure:
    """
    Analyse de la structure de marché selon les Smart Money Concepts.
    
    Détecte:
    - Swing Highs et Swing Lows
    - BOS (Break of Structure) - continuation de tendance
    - CHoCH (Change of Character) - changement de tendance
    - Tendance actuelle (HH/HL pour bullish, LH/LL pour bearish)
    """
    
    def __init__(self, swing_strength: int = 5, min_impulse_pips: float = 10.0, displacement_multiplier: float = 1.2):
        """
        Initialise le détecteur de structure de marché.
        
        Args:
            swing_strength: Nombre de bougies de chaque côté pour confirmer un swing
            min_impulse_pips: Impulsion minimum en pips pour valider un BOS
            displacement_multiplier: Multiplicateur d'ATR pour valider un déplacement impulsif
        """
        self.swing_strength = swing_strength
        self.min_impulse_pips = min_impulse_pips
        self.displacement_multiplier = displacement_multiplier
        self.swing_highs: List[SwingPoint] = []
        self.swing_lows: List[SwingPoint] = []
        self.structure_breaks: List[StructureBreak] = []
        self.current_trend = Trend.RANGING

    def _is_displaced(self, df: pd.DataFrame, index: int) -> bool:
        """Compatibilité legacy pour smc_strategy.py"""
        if index < 0 or index >= len(df): return False
        if index < 10: return True
        
        candle = df.iloc[index]
        body_size = abs(candle['close'] - candle['open'])
        
        # Moyenne du range (High-Low) des 10 dernières bougies
        avg_range = (df['high'] - df['low']).iloc[index-10:index].mean()
        
        if avg_range == 0: return True
        
        return body_size > (avg_range * self.displacement_multiplier)

    def _is_displaced_numpy(self, index: int, closes: np.ndarray, opens: np.ndarray, highs: np.ndarray, lows: np.ndarray) -> bool:
        """Version optimisée Numpy de _is_displaced (sans DataFrame overhead)."""
        if index < 10: return True
        
        body_size = abs(closes[index] - opens[index])
        
        # Moyenne du range (High-Low) des 10 dernières bougies
        # Slice numpy: [index-10 : index]
        ranges = highs[index-10:index] - lows[index-10:index]
        avg_range = np.mean(ranges)
        
        if avg_range == 0: return True
        
        return body_size > (avg_range * self.displacement_multiplier)

    def analyze(self, df: pd.DataFrame) -> dict:
        """
        Analyse complète de la structure de marché.
        
        Args:
            df: DataFrame avec colonnes OHLC (open, high, low, close)
            
        Returns:
            Dict contenant les swing points, BOS/CHoCH et tendance
        """
        # Reset des listes
        self.swing_highs = []
        self.swing_lows = []
        self.structure_breaks = []
        
        # Étape 1: Identifier les Swing Highs et Lows
        self._find_swing_points(df)
        
        # Étape 2: Identifier les BOS et CHoCH
        self._identify_structure_breaks(df)
        
        # Étape 3: Déterminer la tendance actuelle
        self._determine_trend()
        
        return {
            'swing_highs': self.swing_highs,
            'swing_lows': self.swing_lows,
            'structure_breaks': self.structure_breaks,
            'current_trend': self.current_trend,
            'last_hh': self._get_last_swing(is_high=True, is_higher=True),
            'last_hl': self._get_last_swing(is_high=False, is_higher=True),
            'last_lh': self._get_last_swing(is_high=True, is_higher=False),
            'last_ll': self._get_last_swing(is_high=False, is_higher=False),
        }

    def _find_swing_points(self, df: pd.DataFrame) -> None:
        """Identifie les points de swing (highs et lows) - OPTIMISÉ NUMPY."""
        # Extraction one-shot des numpy arrays
        highs = df['high'].values
        lows = df['low'].values
        n = self.swing_strength
        length = len(highs)
        timestamps = df.index
        
        # Boucle optimisée sur index uniquement (pas d'iloc)
        # On peut utiliser une fenêtre glissante virtuelle
        
        for i in range(n, length - n):
            # Optimisation: Vérification rapide avant boucle
            # Check neighbors immediately adjacent first (statistiquement élimine 80% des cas)
            if highs[i] <= highs[i-1] or highs[i] <= highs[i+1]:
                is_swing_high = False
            else:
                # Full verification
                is_swing_high = True
                current_high = highs[i]
                for j in range(2, n + 1):
                    if highs[i - j] >= current_high or highs[i + j] >= current_high:
                        is_swing_high = False
                        break
            
            if is_swing_high:
                self.swing_highs.append(SwingPoint(i, float(current_high), timestamps[i], True, True))
            
            # Check Low
            if lows[i] >= lows[i-1] or lows[i] >= lows[i+1]:
                is_swing_low = False
            else:
                is_swing_low = True
                current_low = lows[i]
                for j in range(2, n + 1):
                    if lows[i - j] <= current_low or lows[i + j] <= current_low:
                        is_swing_low = False
                        break
            
            if is_swing_low:
                self.swing_lows.append(SwingPoint(i, float(current_low), timestamps[i], False, True))
        
        logger.debug(f"Found {len(self.swing_highs)} swing highs and {len(self.swing_lows)} swing lows")
    
    def _identify_structure_breaks(self, df: pd.DataFrame) -> None:
        """Identifie les Break of Structure (BOS) et Change of Character (CHoCH) - OPTIMISÉ NUMPY."""
        
        # Combiner et trier tous les swings par index
        if not self.swing_highs and not self.swing_lows:
            return
            
        all_swings = sorted(
            self.swing_highs + self.swing_lows,
            key=lambda x: x.index
        )
        
        if len(all_swings) < 3:
            return
            
        # Extraction Numpy pour accès rapide
        closes = df['close'].values
        opens = df['open'].values
        highs = df['high'].values
        lows = df['low'].values
        timestamps = df.index
        length = len(closes)
        
        last_valid_high: Optional[SwingPoint] = None
        last_valid_low: Optional[SwingPoint] = None
        internal_trend = Trend.RANGING
        
        # Pour éviter de re-checker des barres déjà passées
        # On ne check que devant le swing
        
        for i, current_swing in enumerate(all_swings):
            # Chercher les cassures à partir de l'index du swing + 1
            # Mais on s'arrête si on trouve une cassure
            
            start_idx = current_swing.index + 1
            if start_idx >= length:
                continue
                
            for bar_idx in range(start_idx, length):
                close_price = closes[bar_idx]
                
                # Vérifier cassure de swing high
                if current_swing.is_high and not current_swing.broken:
                    if close_price > current_swing.price:
                        # Filtre de déplacement (Numpy version)
                        if not self._is_displaced_numpy(bar_idx, closes, opens, highs, lows):
                            continue
                            
                        current_swing.broken = True
                        
                        if internal_trend == Trend.BULLISH:
                            structure_type = StructureType.BOS
                        elif internal_trend == Trend.BEARISH:
                            structure_type = StructureType.CHOCH
                        else:
                            structure_type = StructureType.BOS
                        
                        self.structure_breaks.append(StructureBreak(
                            type=structure_type,
                            direction=Trend.BULLISH,
                            break_index=bar_idx,
                            break_price=float(close_price),
                            swing_index=current_swing.index,
                            swing_price=current_swing.price,
                            timestamp=timestamps[bar_idx]
                        ))
                        
                        if structure_type == StructureType.CHOCH:
                            internal_trend = Trend.BULLISH
                        break
                
                # Vérifier cassure de swing low
                elif not current_swing.is_high and not current_swing.broken:
                    if close_price < current_swing.price:
                        # Filtre de déplacement (Numpy version)
                        if not self._is_displaced_numpy(bar_idx, closes, opens, highs, lows):
                            continue
                            
                        current_swing.broken = True
                        
                        if internal_trend == Trend.BEARISH:
                            structure_type = StructureType.BOS
                        elif internal_trend == Trend.BULLISH:
                            structure_type = StructureType.CHOCH
                        else:
                            structure_type = StructureType.BOS
                        
                        self.structure_breaks.append(StructureBreak(
                            type=structure_type,
                            direction=Trend.BEARISH,
                            break_index=bar_idx,
                            break_price=float(close_price),
                            swing_index=current_swing.index,
                            swing_price=current_swing.price,
                            timestamp=timestamps[bar_idx]
                        ))
                        
                        if structure_type == StructureType.CHOCH:
                            internal_trend = Trend.BEARISH
                        break
        
        logger.debug(f"Found {len(self.structure_breaks)} structure breaks")
    
    def _determine_trend(self) -> None:
        """Détermine la tendance actuelle basée sur la structure."""
        if not self.structure_breaks:
            self.current_trend = Trend.RANGING
            return
        
        # Regarder les 3 derniers breaks
        recent_breaks = self.structure_breaks[-3:] if len(self.structure_breaks) >= 3 else self.structure_breaks
        
        bullish_count = sum(1 for b in recent_breaks if b.direction == Trend.BULLISH)
        bearish_count = sum(1 for b in recent_breaks if b.direction == Trend.BEARISH)
        
        # Le dernier CHoCH détermine la tendance
        for break_ in reversed(self.structure_breaks):
            if break_.type == StructureType.CHOCH:
                self.current_trend = break_.direction
                return
        
        # Sinon, la majorité des BOS
        if bullish_count > bearish_count:
            self.current_trend = Trend.BULLISH
        elif bearish_count > bullish_count:
            self.current_trend = Trend.BEARISH
        else:
            self.current_trend = Trend.RANGING
    
    def _get_last_swing(self, is_high: bool, is_higher: bool) -> Optional[SwingPoint]:
        """Récupère le dernier swing d'un type spécifique."""
        swings = self.swing_highs if is_high else self.swing_lows
        
        if len(swings) < 2:
            return swings[-1] if swings else None
        
        for i in range(len(swings) - 1, 0, -1):
            if is_higher:
                if swings[i].price > swings[i-1].price:
                    return swings[i]
            else:
                if swings[i].price < swings[i-1].price:
                    return swings[i]
        
        return swings[-1] if swings else None
    
    def get_bias(self) -> str:
        """Retourne le biais de trading basé sur la structure."""
        if self.current_trend == Trend.BULLISH:
            return "BUY"
        elif self.current_trend == Trend.BEARISH:
            return "SELL"
        else:
            return "NEUTRAL"
    
    def get_last_bos(self, direction: Optional[Trend] = None) -> Optional[StructureBreak]:
        """Récupère le dernier BOS, optionnellement filtré par direction."""
        for break_ in reversed(self.structure_breaks):
            if break_.type == StructureType.BOS:
                if direction is None or break_.direction == direction:
                    return break_
        return None
    
    def get_last_choch(self) -> Optional[StructureBreak]:
        """Récupère le dernier CHoCH."""
        for break_ in reversed(self.structure_breaks):
            if break_.type == StructureType.CHOCH:
                return break_
        return None
    
    def get_structure_for_visualization(self) -> List[dict]:
        """Retourne les données de structure pour la visualisation."""
        viz_data = []
        
        for sh in self.swing_highs:
            viz_data.append({
                'type': 'swing_high',
                'index': sh.index,
                'price': sh.price,
                'broken': sh.broken
            })
        
        for sl in self.swing_lows:
            viz_data.append({
                'type': 'swing_low',
                'index': sl.index,
                'price': sl.price,
                'broken': sl.broken
            })
        
        for sb in self.structure_breaks:
            viz_data.append({
                'type': sb.type.value,
                'direction': sb.direction.value,
                'break_index': sb.break_index,
                'break_price': sb.break_price,
                'swing_index': sb.swing_index,
                'swing_price': sb.swing_price
            })
        
        return viz_data
