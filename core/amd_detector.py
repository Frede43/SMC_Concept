"""
AMD Strategy Module - Accumulation, Manipulation, Distribution
Stratégie ICT pour détecter le cycle complet des Smart Money

Concept:
1. ACCUMULATION: Smart Money accumule des positions dans un range
2. MANIPULATION: Faux breakout pour prendre la liquidité des retail
3. DISTRIBUTION: Le vrai mouvement commence dans la direction opposée

Ce cycle se répète constamment et est la base de la stratégie ICT.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from enum import Enum
from loguru import logger


class AMDPhase(Enum):
    """Les 3 phases du cycle AMD"""
    NONE = "none"
    ACCUMULATION = "accumulation"      # Range/consolidation
    MANIPULATION = "manipulation"       # Sweep/faux breakout
    DISTRIBUTION = "distribution"       # Vrai mouvement


class ManipulationType(Enum):
    """Type de manipulation détectée"""
    NONE = "none"
    HIGH_SWEEP = "high_sweep"          # Sweep du high → SELL signal
    LOW_SWEEP = "low_sweep"            # Sweep du low → BUY signal


@dataclass
class AccumulationZone:
    """Zone d'accumulation (range) détectée"""
    high: float
    low: float
    start_index: int
    end_index: int
    start_time: datetime
    duration_bars: int
    is_valid: bool = True
    
    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2
    
    @property
    def range_size(self) -> float:
        return self.high - self.low
    
    @property
    def range_percentage(self) -> float:
        """Taille du range en pourcentage du prix"""
        return (self.range_size / self.midpoint) * 100 if self.midpoint > 0 else 0


@dataclass
class ManipulationEvent:
    """Événement de manipulation (sweep)"""
    manipulation_type: ManipulationType
    accumulation_zone: AccumulationZone
    sweep_price: float
    sweep_index: int
    sweep_time: datetime
    confirmed: bool = False
    reversal_price: Optional[float] = None
    
    @property
    def expected_direction(self) -> str:
        """Direction attendue après la manipulation"""
        if self.manipulation_type == ManipulationType.HIGH_SWEEP:
            return "SELL"  # Après un sweep du high, on s'attend à une baisse
        elif self.manipulation_type == ManipulationType.LOW_SWEEP:
            return "BUY"   # Après un sweep du low, on s'attend à une hausse
        return "NEUTRAL"


@dataclass
class AMDSetup:
    """Setup AMD complet"""
    phase: AMDPhase
    accumulation: Optional[AccumulationZone] = None
    manipulation: Optional[ManipulationEvent] = None
    direction: str = "NEUTRAL"
    confidence: float = 0.0
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reasons: List[str] = field(default_factory=list)


class AMDDetector:
    """
    Détecteur du cycle AMD (Accumulation-Manipulation-Distribution).
    
    Algorithme:
    1. Détecter les zones d'accumulation (ranges serrés avec faible volatilité)
    2. Surveiller les sweeps (manipulation) de ces ranges
    3. Confirmer le reversal et générer un signal de distribution
    
    Paramètres clés:
    - min_range_bars: Minimum de bougies pour valider un range
    - max_range_percentage: Taille max du range pour le considérer comme accumulation
    - sweep_buffer_pips: Buffer pour détecter un sweep
    """
    
    def __init__(self, 
                 min_range_bars: int = 8,
                 max_range_percentage: float = 1.5,
                 sweep_buffer_pips: float = 3.0,
                 confirmation_bars: int = 2):
        """
        Args:
            min_range_bars: Minimum de bougies pour un range valide
            max_range_percentage: Taille max du range en % du prix
            sweep_buffer_pips: Buffer en pips pour détecter un sweep
            confirmation_bars: Bougies nécessaires pour confirmer le reversal
        """
        self.min_range_bars = min_range_bars
        self.max_range_percentage = max_range_percentage
        self.sweep_buffer_pips = sweep_buffer_pips
        self.confirmation_bars = confirmation_bars
        
        # État actuel
        self.current_accumulation: Optional[AccumulationZone] = None
        self.current_manipulation: Optional[ManipulationEvent] = None
        self.current_phase: AMDPhase = AMDPhase.NONE
        
        # Historique
        self.accumulation_history: List[AccumulationZone] = []
        self.manipulation_history: List[ManipulationEvent] = []
        
        # Cache par symbole
        self._last_analyzed_symbol: str = ""
        
    def analyze(self, df: pd.DataFrame, symbol: str = "UNKNOWN") -> AMDSetup:
        """
        Analyse complète du cycle AMD.
        
        Returns:
            AMDSetup avec la phase actuelle et les détails du setup
        """
        if len(df) < self.min_range_bars * 2:
            return AMDSetup(phase=AMDPhase.NONE, reasons=["Pas assez de données"])
        
        # Reset si nouveau symbole
        if symbol != self._last_analyzed_symbol:
            self._reset_state()
            self._last_analyzed_symbol = symbol
        
        current_price = df.iloc[-1]['close']
        reasons = []
        
        # Phase 1: Chercher une accumulation (range)
        if self.current_accumulation is None:
            accumulation = self._detect_accumulation(df)
            if accumulation:
                self.current_accumulation = accumulation
                self.accumulation_history.append(accumulation)
                self.current_phase = AMDPhase.ACCUMULATION
                reasons.append(f"Range détecté: {accumulation.low:.5f} - {accumulation.high:.5f}")
                logger.info(f"📦 AMD: Accumulation détectée [{accumulation.low:.5f}-{accumulation.high:.5f}]")
        
        # Phase 2: Chercher une manipulation (sweep)
        if self.current_accumulation and self.current_manipulation is None:
            manipulation = self._detect_manipulation(df, current_price)
            if manipulation:
                self.current_manipulation = manipulation
                self.manipulation_history.append(manipulation)
                self.current_phase = AMDPhase.MANIPULATION
                reasons.append(f"Sweep {manipulation.manipulation_type.value} à {manipulation.sweep_price:.5f}")
                logger.info(f"🎭 AMD: Manipulation ({manipulation.manipulation_type.value}) détectée!")
        
        # Phase 3: Confirmer la distribution (reversal)
        if self.current_manipulation and not self.current_manipulation.confirmed:
            distribution = self._confirm_distribution(df, current_price)
            if distribution:
                self.current_manipulation.confirmed = True
                self.current_manipulation.reversal_price = current_price
                self.current_phase = AMDPhase.DISTRIBUTION
                reasons.append(f"Distribution confirmée - {distribution['direction']} signal")
                logger.info(f"🚀 AMD: Distribution confirmée - Signal {distribution['direction']}!")
                
                return AMDSetup(
                    phase=AMDPhase.DISTRIBUTION,
                    accumulation=self.current_accumulation,
                    manipulation=self.current_manipulation,
                    direction=distribution['direction'],
                    confidence=distribution['confidence'],
                    entry_price=distribution['entry'],
                    stop_loss=distribution['sl'],
                    take_profit=distribution['tp'],
                    reasons=reasons
                )
        
        # Retourner le setup actuel
        return AMDSetup(
            phase=self.current_phase,
            accumulation=self.current_accumulation,
            manipulation=self.current_manipulation,
            direction=self.current_manipulation.expected_direction if self.current_manipulation else "NEUTRAL",
            confidence=self._calculate_confidence(),
            reasons=reasons if reasons else [f"Phase: {self.current_phase.value}"]
        )
    
    def _detect_accumulation(self, df: pd.DataFrame) -> Optional[AccumulationZone]:
        """
        Détecte une zone d'accumulation (range serré).
        
        Critères:
        - Prix dans un range pendant minimum X bougies
        - Taille du range < max_range_percentage du prix
        - ATR faible comparé à la moyenne
        """
        # Analyser les dernières N bougies
        lookback = min(50, len(df) - 1)
        recent_df = df.iloc[-lookback:]
        
        # Calculer l'ATR pour mesurer la volatilité
        high_low = recent_df['high'] - recent_df['low']
        atr = high_low.rolling(window=14).mean().iloc[-1]
        avg_atr = high_low.mean()
        
        # Chercher une période de faible volatilité
        for start_idx in range(len(recent_df) - self.min_range_bars, 0, -1):
            end_idx = len(recent_df) - 1
            window = recent_df.iloc[start_idx:end_idx + 1]
            
            if len(window) < self.min_range_bars:
                continue
            
            range_high = window['high'].max()
            range_low = window['low'].min()
            range_size = range_high - range_low
            midpoint = (range_high + range_low) / 2
            range_pct = (range_size / midpoint) * 100 if midpoint > 0 else 0
            
            # Vérifier si c'est un range serré
            if range_pct <= self.max_range_percentage:
                # Vérifier que le prix actuel est sorti du range (pour chercher la manipulation)
                current_price = df.iloc[-1]['close']
                
                # Le range doit être récent mais pas actif (on cherche le sweep)
                if current_price > range_high * 1.001 or current_price < range_low * 0.999:
                    return AccumulationZone(
                        high=range_high,
                        low=range_low,
                        start_index=start_idx,
                        end_index=end_idx,
                        start_time=recent_df.index[start_idx] if isinstance(recent_df.index, pd.DatetimeIndex) else datetime.now(),
                        duration_bars=end_idx - start_idx + 1,
                        is_valid=True
                    )
        
        return None
    
    def _detect_manipulation(self, df: pd.DataFrame, current_price: float) -> Optional[ManipulationEvent]:
        """
        Détecte une manipulation (sweep du range).
        
        Un sweep = le prix dépasse le high/low du range puis commence à revenir.
        """
        if self.current_accumulation is None:
            return None
        
        acc = self.current_accumulation
        buffer = self._calculate_buffer(acc.high)
        
        recent_high = df.iloc[-5:]['high'].max()
        recent_low = df.iloc[-5:]['low'].min()
        
        # Sweep du HIGH (manipulation bearish)
        if recent_high > acc.high + buffer:
            # Le prix a dépassé le high du range
            if current_price < recent_high:  # Et commence à redescendre
                return ManipulationEvent(
                    manipulation_type=ManipulationType.HIGH_SWEEP,
                    accumulation_zone=acc,
                    sweep_price=recent_high,
                    sweep_index=len(df) - 1,
                    sweep_time=datetime.now()
                )
        
        # Sweep du LOW (manipulation bullish)
        if recent_low < acc.low - buffer:
            # Le prix a dépassé le low du range
            if current_price > recent_low:  # Et commence à remonter
                return ManipulationEvent(
                    manipulation_type=ManipulationType.LOW_SWEEP,
                    accumulation_zone=acc,
                    sweep_price=recent_low,
                    sweep_index=len(df) - 1,
                    sweep_time=datetime.now()
                )
        
        return None
    
    def _confirm_distribution(self, df: pd.DataFrame, current_price: float) -> Optional[Dict]:
        """
        Confirme le début de la distribution (vrai mouvement).
        
        Critères:
        - Le prix est revenu dans ou au-delà du range d'accumulation
        - Confirmation par X bougies dans la même direction
        """
        if self.current_manipulation is None or self.current_accumulation is None:
            return None
        
        manip = self.current_manipulation
        acc = self.current_accumulation
        
        # Pour un HIGH sweep, on attend que le prix revienne sous le high
        if manip.manipulation_type == ManipulationType.HIGH_SWEEP:
            if current_price < acc.high:
                # Confirmer avec les dernières bougies
                recent_closes = df.iloc[-self.confirmation_bars:]['close']
                if all(recent_closes.diff().dropna() < 0):  # Toutes les bougies descendent
                    # Calculer SL et TP
                    sl = manip.sweep_price + self._calculate_buffer(acc.high) * 2
                    tp = acc.low - (manip.sweep_price - acc.low)  # Extension vers le bas
                    
                    return {
                        'direction': 'SELL',
                        'confidence': 85.0,
                        'entry': current_price,
                        'sl': sl,
                        'tp': tp
                    }
        
        # Pour un LOW sweep, on attend que le prix revienne au-dessus du low
        elif manip.manipulation_type == ManipulationType.LOW_SWEEP:
            if current_price > acc.low:
                # Confirmer avec les dernières bougies
                recent_closes = df.iloc[-self.confirmation_bars:]['close']
                if all(recent_closes.diff().dropna() > 0):  # Toutes les bougies montent
                    # Calculer SL et TP
                    sl = manip.sweep_price - self._calculate_buffer(acc.low) * 2
                    tp = acc.high + (acc.high - manip.sweep_price)  # Extension vers le haut
                    
                    return {
                        'direction': 'BUY',
                        'confidence': 85.0,
                        'entry': current_price,
                        'sl': sl,
                        'tp': tp
                    }
        
        return None
    
    def _calculate_buffer(self, reference_price: float) -> float:
        """Calcule le buffer en fonction du prix (forex vs or)."""
        if reference_price > 1000:  # XAUUSD
            return self.sweep_buffer_pips * 0.1
        else:  # Forex
            return self.sweep_buffer_pips * 0.0001
    
    def _calculate_confidence(self) -> float:
        """Calcule le score de confiance du setup actuel."""
        confidence = 0.0
        
        if self.current_phase == AMDPhase.ACCUMULATION:
            confidence = 30.0
        elif self.current_phase == AMDPhase.MANIPULATION:
            confidence = 60.0
        elif self.current_phase == AMDPhase.DISTRIBUTION:
            confidence = 85.0
        
        return confidence
    
    def _reset_state(self):
        """Reset l'état pour un nouveau symbole."""
        self.current_accumulation = None
        self.current_manipulation = None
        self.current_phase = AMDPhase.NONE
        self.accumulation_history.clear()
        self.manipulation_history.clear()
        logger.debug("AMD Detector reset")
    
    def get_status(self) -> Dict:
        """Retourne le statut actuel du détecteur AMD."""
        return {
            "phase": self.current_phase.value,
            "has_accumulation": self.current_accumulation is not None,
            "has_manipulation": self.current_manipulation is not None,
            "accumulation_range": f"{self.current_accumulation.low:.5f}-{self.current_accumulation.high:.5f}" 
                if self.current_accumulation else "None",
            "manipulation_type": self.current_manipulation.manipulation_type.value 
                if self.current_manipulation else "None",
            "expected_direction": self.current_manipulation.expected_direction 
                if self.current_manipulation else "NEUTRAL"
        }
    
    def reset_daily(self):
        """Reset quotidien."""
        self._reset_state()
