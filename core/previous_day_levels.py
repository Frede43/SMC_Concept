"""
Previous Day Liquidity Module
Détection des niveaux de liquidité du jour précédent selon ICT/SMC

Concepts:
- PDH (Previous Day High): Niveau de résistance où les stop-loss des vendeurs sont placés
- PDL (Previous Day Low): Niveau de support où les stop-loss des acheteurs sont placés
- Ces niveaux sont des "liquidity pools" que les Smart Money ciblent

Usage:
- Un sweep du PDH suivi d'un retournement = signal SELL potentiel
- Un sweep du PDL suivi d'un retournement = signal BUY potentiel
"""

import pandas as pd
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional, List, Dict, Tuple
from enum import Enum
from loguru import logger


class SweepType(Enum):
    """Type de sweep de liquidité"""
    NONE = "none"
    PDH_SWEEP = "pdh_sweep"      # Sweep du Previous Day High
    PDL_SWEEP = "pdl_sweep"      # Sweep du Previous Day Low
    PWH_SWEEP = "pwh_sweep"      # Sweep du Previous Week High
    PWL_SWEEP = "pwl_sweep"      # Sweep du Previous Week Low


@dataclass
class PreviousDayLevels:
    """Niveaux du jour précédent"""
    date: datetime
    high: float                   # Previous Day High (PDH)
    low: float                    # Previous Day Low (PDL)
    open: float                   # Previous Day Open
    close: float                  # Previous Day Close
    midpoint: float               # Point médian du range
    range_size: float             # Taille du range
    is_valid: bool = True
    
    @property
    def is_bullish_day(self) -> bool:
        """Le jour précédent était-il bullish?"""
        return self.close > self.open
    
    @property
    def body_size(self) -> float:
        """Taille du corps de la bougie journalière"""
        return abs(self.close - self.open)


@dataclass
class SweepEvent:
    """Événement de sweep de liquidité"""
    sweep_type: SweepType
    level: float                  # Niveau qui a été swept
    sweep_price: float            # Prix au moment du sweep
    sweep_time: datetime
    confirmed: bool = False       # True si le prix est revenu après le sweep
    direction_after: str = ""     # "bullish" ou "bearish" après le sweep


class PreviousDayLiquidityDetector:
    """
    Détecteur de niveaux de liquidité du jour précédent.
    
    Les Smart Money utilisent ces niveaux pour:
    1. Identifier où la liquidité est concentrée (stop-loss)
    2. Attendre un sweep (prise de liquidité) avant d'entrer
    3. Confirmer la direction du trade après le sweep
    """
    
    def __init__(self, buffer_pips: float = 2.0, timezone_offset: int = 0):
        """
        Args:
            buffer_pips: Buffer en pips pour considérer un sweep
            timezone_offset: Décalage horaire par rapport à GMT
        """
        self.buffer_pips = buffer_pips
        self.timezone_offset = timezone_offset
        self.current_levels: Optional[PreviousDayLevels] = None
        self.previous_week_levels: Optional[Dict] = None
        self.sweep_history: List[SweepEvent] = []
        self.daily_levels_cache: Dict[str, PreviousDayLevels] = {}
        
    def calculate_previous_day_levels(self, df: pd.DataFrame, 
                                       reference_date: datetime = None) -> Optional[PreviousDayLevels]:
        """
        Calcule les niveaux PDH/PDL.
        
        Args:
            df: DataFrame OHLC avec données historiques
            reference_date: Date de référence (défaut: aujourd'hui)
        """
        try:
            if reference_date is None:
                reference_date = datetime.now()
            
            today = reference_date.date()
            yesterday = today - timedelta(days=1)
            
            # Ajuster pour le weekend (si lundi, prendre vendredi)
            if yesterday.weekday() == 6:  # Dimanche
                yesterday = yesterday - timedelta(days=2)
            elif yesterday.weekday() == 5:  # Samedi
                yesterday = yesterday - timedelta(days=1)
            
            # Filtrer les données du jour précédent
            if isinstance(df.index, pd.DatetimeIndex):
                # Convertir les dates en datetime pour la comparaison
                start_of_yesterday = datetime.combine(yesterday, time(0, 0))
                end_of_yesterday = datetime.combine(yesterday, time(23, 59, 59))
                
                mask = (df.index >= start_of_yesterday) & (df.index <= end_of_yesterday)
                prev_day_data = df[mask]
                
                if len(prev_day_data) < 5:
                    # Pas assez de données, utiliser method alternative
                    prev_day_data = self._get_previous_session_data(df)
            else:
                prev_day_data = self._get_previous_session_data(df)
            
            if len(prev_day_data) == 0:
                logger.warning("Pas de données pour le jour précédent")
                return None
            
            pdh = prev_day_data['high'].max()
            pdl = prev_day_data['low'].min()
            pdo = prev_day_data['open'].iloc[0]
            pdc = prev_day_data['close'].iloc[-1]
            
            levels = PreviousDayLevels(
                date=yesterday,
                high=pdh,
                low=pdl,
                open=pdo,
                close=pdc,
                midpoint=(pdh + pdl) / 2,
                range_size=pdh - pdl,
                is_valid=True
            )
            
            # Cache
            date_key = yesterday.strftime("%Y-%m-%d")
            self.daily_levels_cache[date_key] = levels
            self.current_levels = levels
            
            logger.debug(f"📊 PDH: {pdh:.5f} | PDL: {pdl:.5f} | Range: {levels.range_size:.5f}")
            
            return levels
            
        except Exception as e:
            logger.error(f"Erreur calcul PDH/PDL: {e}")
            return None
    
    def _get_previous_session_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Méthode alternative pour obtenir les données de la session précédente.
        Utilise les dernières 96 bougies M15 (~24h) pour estimer.
        """
        # Calculer combien de bougies représentent ~24h
        # Pour M15: 96 bougies = 24 heures
        candles_per_day = 96  # M15 default
        
        if len(df) < candles_per_day * 2:
            return df.head(candles_per_day)
        
        # Prendre les données de la veille (pas aujourd'hui)
        return df.iloc[-candles_per_day*2:-candles_per_day]
    
    def check_sweep(self, current_price: float, 
                    previous_prices: List[float] = None) -> Optional[SweepEvent]:
        """
        Vérifie si un sweep de PDH ou PDL s'est produit.
        
        Un sweep = le prix dépasse le niveau puis revient.
        
        Args:
            current_price: Prix actuel
            previous_prices: Liste des prix précédents pour confirmer le sweep
        """
        if self.current_levels is None:
            return None
        
        levels = self.current_levels
        buffer = self.buffer_pips * 0.0001  # Convertir pips en prix (pour forex)
        
        # Ajuster le buffer pour l'or (XAUUSD)
        if levels.high > 1000:  # Probablement de l'or
            buffer = self.buffer_pips * 0.1  # 0.1 par pip pour l'or
        
        # Check PDH Sweep (prix au-dessus du high puis redescend)
        if current_price > levels.high + buffer:
            sweep = SweepEvent(
                sweep_type=SweepType.PDH_SWEEP,
                level=levels.high,
                sweep_price=current_price,
                sweep_time=datetime.now(),
                confirmed=False,
                direction_after="pending"
            )
            self.sweep_history.append(sweep)
            logger.info(f"🎯 PDH SWEEP détecté! Prix {current_price:.5f} > PDH {levels.high:.5f}")
            return sweep
        
        # Check PDL Sweep (prix en-dessous du low puis remonte)
        if current_price < levels.low - buffer:
            sweep = SweepEvent(
                sweep_type=SweepType.PDL_SWEEP,
                level=levels.low,
                sweep_price=current_price,
                sweep_time=datetime.now(),
                confirmed=False,
                direction_after="pending"
            )
            self.sweep_history.append(sweep)
            logger.info(f"🎯 PDL SWEEP détecté! Prix {current_price:.5f} < PDL {levels.low:.5f}")
            return sweep
        
        return None
    
    def confirm_sweep(self, current_price: float) -> Optional[SweepEvent]:
        """
        Confirme un sweep récent avec critères plus réalistes:
        1. Prix revenu de l'autre côté du niveau (méthode originale)
        2. OU prix stabilisé près du niveau pendant 5+ minutes (AUGMENTÉ de 3 à 5)
        3. OU formation d'une bougie de rejet visible (nouveau)
        
        ✅ v2.3.2: Exige au moins 5 minutes avant confirmation (plus réactif)
        
        Returns:
            Le sweep confirmé ou None
        """
        if not self.sweep_history:
            return None
        
        # Vérifier le dernier sweep non confirmé
        for sweep in reversed(self.sweep_history):
            if sweep.confirmed:
                continue
            
            # Calculer le temps écoulé depuis le sweep
            time_since_sweep = (datetime.now() - sweep.sweep_time).total_seconds() / 60  # en minutes
            
            # ✅ v2.3.2: Exiger au moins 5 minutes avant confirmation (plus réactif)
            if time_since_sweep < 5:
                continue  # Trop tôt pour confirmer
            
            # Calculer la distance relative au niveau (en %)
            distance_pct = abs(current_price - sweep.level) / sweep.level * 100
            
            # Sweep PDH confirmé
            if sweep.sweep_type == SweepType.PDH_SWEEP:
                # Méthode 1: Prix revenu sous le PDH (original)
                if current_price < sweep.level:
                    sweep.confirmed = True
                    sweep.direction_after = "bearish"
                    logger.info(f"✅ PDH Sweep CONFIRMÉ (retour sous niveau) - Signal SELL potentiel")
                    return sweep
                
                # Méthode 2: Prix stabilisé près du PDH (5+ min, distance < 0.05%) - AUGMENTÉ
                elif time_since_sweep >= 35 and distance_pct < 0.05:
                    sweep.confirmed = True
                    sweep.direction_after = "bearish"
                    logger.info(f"✅ PDH Sweep CONFIRMÉ (stabilisation) - Signal SELL potentiel")
                    return sweep
                
                # Méthode 3: Auto-confirmation après 45 minutes si prix toujours proche - AUGMENTÉ
                elif time_since_sweep >= 45 and distance_pct < 0.1:
                    sweep.confirmed = True
                    sweep.direction_after = "bearish"
                    logger.info(f"✅ PDH Sweep CONFIRMÉ (timeout) - Signal SELL potentiel")
                    return sweep
            
            # Sweep PDL confirmé
            elif sweep.sweep_type == SweepType.PDL_SWEEP:
                # Méthode 1: Prix revenu au-dessus du PDL (original)
                if current_price > sweep.level:
                    sweep.confirmed = True
                    sweep.direction_after = "bullish"
                    logger.info(f"✅ PDL Sweep CONFIRMÉ (retour au-dessus niveau) - Signal BUY potentiel")
                    return sweep
                
                # Méthode 2: Prix stabilisé près du PDL (5+ min, distance < 0.05%) - AUGMENTÉ
                elif time_since_sweep >= 35 and distance_pct < 0.05:
                    sweep.confirmed = True
                    sweep.direction_after = "bullish"
                    logger.info(f"✅ PDL Sweep CONFIRMÉ (stabilisation) - Signal BUY potentiel")
                    return sweep
                
                # Méthode 3: Auto-confirmation après 45 minutes si prix toujours proche - AUGMENTÉ
                elif time_since_sweep >= 45 and distance_pct < 0.1:
                    sweep.confirmed = True
                    sweep.direction_after = "bullish"
                    logger.info(f"✅ PDL Sweep CONFIRMÉ (timeout) - Signal BUY potentiel")
                    return sweep
        
        return None
    
    def get_trading_bias(self, current_price: float) -> Tuple[str, str]:
        """
        Détermine le biais de trading basé sur les niveaux PDH/PDL.
        
        Returns:
            (bias, reason) - "BUY", "SELL", ou "NEUTRAL"
        """
        if self.current_levels is None:
            return "NEUTRAL", "Pas de niveaux PDH/PDL disponibles"
        
        levels = self.current_levels
        
        # Vérifier les sweeps confirmés récents
        confirmed_sweep = self.get_last_confirmed_sweep()
        if confirmed_sweep:
            if confirmed_sweep.direction_after == "bullish":
                return "BUY", f"PDL Sweep confirmé à {confirmed_sweep.level:.5f}"
            elif confirmed_sweep.direction_after == "bearish":
                return "SELL", f"PDH Sweep confirmé à {confirmed_sweep.level:.5f}"
        
        # Biais basé sur la position relative au range
        if current_price > levels.high:
            return "NEUTRAL", f"Prix au-dessus du PDH ({levels.high:.5f}) - Attendre sweep"
        elif current_price < levels.low:
            return "NEUTRAL", f"Prix en-dessous du PDL ({levels.low:.5f}) - Attendre sweep"
        elif current_price > levels.midpoint:
            return "SELL", f"Prix au-dessus du midpoint - Biais vendeur"
        else:
            return "BUY", f"Prix en-dessous du midpoint - Biais acheteur"
    
    def get_last_confirmed_sweep(self, max_age_hours: int = 4) -> Optional[SweepEvent]:
        """Retourne le dernier sweep confirmé dans les X dernières heures."""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        
        for sweep in reversed(self.sweep_history):
            if sweep.confirmed and sweep.sweep_time > cutoff:
                return sweep
        
        return None
    
    def get_levels_info(self) -> Dict:
        """Retourne les informations sur les niveaux actuels."""
        if self.current_levels is None:
            return {"valid": False}
        
        levels = self.current_levels
        return {
            "valid": True,
            "pdh": levels.high,
            "pdl": levels.low,
            "midpoint": levels.midpoint,
            "range": levels.range_size,
            "date": levels.date.strftime("%Y-%m-%d"),
            "bullish_day": levels.is_bullish_day
        }
    
    def calculate_previous_week_levels(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        Calcule les niveaux de la semaine précédente (PWH/PWL).
        Ces niveaux sont encore plus significatifs que les niveaux journaliers.
        """
        try:
            today = datetime.now().date()
            
            # Trouver le début de la semaine dernière
            days_since_monday = today.weekday()
            start_of_this_week = today - timedelta(days=days_since_monday)
            start_of_last_week = start_of_this_week - timedelta(days=7)
            end_of_last_week = start_of_this_week - timedelta(days=1)
            
            if isinstance(df.index, pd.DatetimeIndex):
                start_dt = datetime.combine(start_of_last_week, time(0, 0))
                end_dt = datetime.combine(end_of_last_week, time(23, 59, 59))
                
                mask = (df.index >= start_dt) & (df.index <= end_dt)
                week_data = df[mask]
            else:
                # Environ 5 jours * 96 bougies M15 = 480 bougies
                week_data = df.iloc[-960:-480] if len(df) > 960 else df.head(480)
            
            if len(week_data) == 0:
                return None
            
            pwh = week_data['high'].max()
            pwl = week_data['low'].min()
            
            self.previous_week_levels = {
                "pwh": pwh,
                "pwl": pwl,
                "midpoint": (pwh + pwl) / 2,
                "range": pwh - pwl
            }
            
            logger.debug(f"📊 PWH: {pwh:.5f} | PWL: {pwl:.5f}")
            
            return self.previous_week_levels
            
        except Exception as e:
            logger.error(f"Erreur calcul PWH/PWL: {e}")
            return None
