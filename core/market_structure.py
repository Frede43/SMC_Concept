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
        """Vérifie si la bougie à 'index' montre un déplacement impulsif (corps large)."""
        if index < 10: return True
        
        candle = df.iloc[index]
        body_size = abs(candle['close'] - candle['open'])
        
        # Moyenne du range (High-Low) des 10 dernières bougies
        avg_range = (df['high'] - df['low']).iloc[index-10:index].mean()
        
        if avg_range == 0: return True
        
        # ICT Displacement: Le corps doit être significatif par rapport au range moyen
        return body_size > (avg_range * self.displacement_multiplier)
        
    def analyze(self, df: pd.DataFrame) -> dict:
        """
        Analyse complète de la structure de marché.
        
        Args:
            df: DataFrame avec colonnes OHLC (open, high, low, close)
            
        Returns:
            Dict contenant les swing points, BOS/CHoCH et tendance
        """
        logger.debug(f"Analyzing market structure on {len(df)} bars")
        
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
        """Identifie les points de swing (highs et lows)."""
        n = self.swing_strength
        
        for i in range(n, len(df) - n):
            # Vérifier Swing High
            is_swing_high = True
            current_high = df.iloc[i]['high']
            
            for j in range(1, n + 1):
                if df.iloc[i - j]['high'] >= current_high or df.iloc[i + j]['high'] >= current_high:
                    is_swing_high = False
                    break
            
            if is_swing_high:
                swing = SwingPoint(
                    index=i,
                    price=current_high,
                    timestamp=df.index[i] if isinstance(df.index, pd.DatetimeIndex) else pd.Timestamp.now(),
                    is_high=True,
                    confirmed=True
                )
                self.swing_highs.append(swing)
            
            # Vérifier Swing Low
            is_swing_low = True
            current_low = df.iloc[i]['low']
            
            for j in range(1, n + 1):
                if df.iloc[i - j]['low'] <= current_low or df.iloc[i + j]['low'] <= current_low:
                    is_swing_low = False
                    break
            
            if is_swing_low:
                swing = SwingPoint(
                    index=i,
                    price=current_low,
                    timestamp=df.index[i] if isinstance(df.index, pd.DatetimeIndex) else pd.Timestamp.now(),
                    is_high=False,
                    confirmed=True
                )
                self.swing_lows.append(swing)
        
        logger.debug(f"Found {len(self.swing_highs)} swing highs and {len(self.swing_lows)} swing lows")
    
    def _identify_structure_breaks(self, df: pd.DataFrame) -> None:
        """Identifie les Break of Structure (BOS) et Change of Character (CHoCH)."""
        
        # Combiner et trier tous les swings par index
        all_swings = sorted(
            self.swing_highs + self.swing_lows,
            key=lambda x: x.index
        )
        
        if len(all_swings) < 3:
            return
        
        # Variables pour suivre la structure
        last_valid_high: Optional[SwingPoint] = None
        last_valid_low: Optional[SwingPoint] = None
        internal_trend = Trend.RANGING
        
        for i, current_swing in enumerate(all_swings):
            # Chercher les cassures
            for bar_idx in range(current_swing.index + 1, len(df)):
                bar = df.iloc[bar_idx]
                
                # Vérifier cassure de swing high (potentiel BOS bullish ou CHoCH)
                if current_swing.is_high and not current_swing.broken:
                    if bar['close'] > current_swing.price:
                        # Filtre de déplacement: la cassure doit être impulsive (ICT)
                        if not self._is_displaced(df, bar_idx):
                            continue
                            
                        current_swing.broken = True
                        
                        # Déterminer si c'est un BOS ou CHoCH
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
                            break_price=bar['close'],
                            swing_index=current_swing.index,
                            swing_price=current_swing.price,
                            timestamp=df.index[bar_idx] if isinstance(df.index, pd.DatetimeIndex) else pd.Timestamp.now()
                        ))
                        
                        if structure_type == StructureType.CHOCH:
                            internal_trend = Trend.BULLISH
                            logger.info(f"⚡ CHoCH BULLISH Detected @ {bar['close']:.5f} (Time: {bar_idx})")
                        break
                
                # Vérifier cassure de swing low (potentiel BOS bearish ou CHoCH)
                elif not current_swing.is_high and not current_swing.broken:
                    if bar['close'] < current_swing.price:
                        # Filtre de déplacement: la cassure doit être impulsive (ICT)
                        if not self._is_displaced(df, bar_idx):
                            continue
                            
                        current_swing.broken = True
                        
                        # Déterminer si c'est un BOS ou CHoCH
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
                            break_price=bar['close'],
                            swing_index=current_swing.index,
                            swing_price=current_swing.price,
                            timestamp=df.index[bar_idx] if isinstance(df.index, pd.DatetimeIndex) else pd.Timestamp.now()
                        ))
                        
                        if structure_type == StructureType.CHOCH:
                            internal_trend = Trend.BEARISH
                            logger.info(f"⚡ CHoCH BEARISH Detected @ {bar['close']:.5f} (Time: {bar_idx})")
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
