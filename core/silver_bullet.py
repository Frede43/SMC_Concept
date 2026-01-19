"""
NY Silver Bullet Strategy Module
Stratégie ICT spécifique pour la session New York

La stratégie "Silver Bullet" de ICT:
- Fenêtre de trading: 10:00 - 11:00 AM New York Time (15:00-16:00 GMT en hiver)
- Cherche un FVG après un sweep de liquidité pendant cette fenêtre
- Entrée sur le FVG avec confirmation de structure

Cette stratégie a un taux de réussite élevé car elle exploite
la manipulation typique qui se produit pendant cette heure précise.
"""

import pandas as pd
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional, List, Dict, Tuple
from enum import Enum
from loguru import logger


class SilverBulletPhase(Enum):
    """Phases de la stratégie Silver Bullet"""
    WAITING = "waiting"                    # Hors fenêtre
    WINDOW_OPEN = "window_open"            # Fenêtre ouverte, cherche setup
    SWEEP_DETECTED = "sweep_detected"      # Sweep de liquidité détecté
    FVG_FORMED = "fvg_formed"              # FVG formé après sweep
    ENTRY_READY = "entry_ready"            # Prêt pour entrée
    IN_TRADE = "in_trade"                  # Trade actif
    COMPLETED = "completed"                # Trade terminé pour aujourd'hui


@dataclass
class SilverBulletSetup:
    """Configuration d'un setup Silver Bullet"""
    phase: SilverBulletPhase
    direction: str                         # "BUY" ou "SELL"
    sweep_price: float                     # Prix du sweep de liquidité
    sweep_time: datetime
    fvg_high: Optional[float] = None       # Limites du FVG
    fvg_low: Optional[float] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: float = 0.0
    reasons: List[str] = None

    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []


class NYSilverBulletStrategy:
    """
    Stratégie NY Silver Bullet selon ICT.
    
    La fenêtre Silver Bullet est de 10:00 à 11:00 AM heure de New York.
    Pendant cette heure:
    1. Chercher un sweep de liquidité (PDH, PDL, ou swing high/low)
    2. Attendre la formation d'un FVG dans la direction opposée au sweep
    3. Entrer quand le prix revient dans le FVG
    4. Stop loss au-delà du sweep, take profit au niveau opposé
    """
    
    # Fenêtre Silver Bullet en GMT (ajuster pour l'heure d'été/hiver NY)
    # 10:00 AM NY = 15:00 GMT (hiver) ou 14:00 GMT (été)
    WINDOW_START_GMT = time(14, 0)    # 10:00 AM NY (été)
    WINDOW_END_GMT = time(15, 0)      # 11:00 AM NY (été)
    
    # Alternative: fenêtre Silver Bullet de l'après-midi (2:00-3:00 PM NY)
    PM_WINDOW_START_GMT = time(18, 0)
    PM_WINDOW_END_GMT = time(19, 0)
    
    def __init__(self, 
                 timezone_offset: int = 2,
                 use_pm_window: bool = False,
                 min_sweep_pips: float = 5.0,
                 fvg_detector = None,
                 pdl_detector = None):
        """
        Args:
            timezone_offset: Décalage par rapport à GMT
            use_pm_window: Utiliser aussi la fenêtre PM (2-3 PM NY)
            min_sweep_pips: Minimum de pips pour considérer un sweep
            fvg_detector: Instance de FVGDetector (optionnel)
            pdl_detector: Instance de PreviousDayLiquidityDetector (optionnel)
        """
        self.timezone_offset = timezone_offset
        self.use_pm_window = use_pm_window
        self.min_sweep_pips = min_sweep_pips
        self.fvg_detector = fvg_detector
        self.pdl_detector = pdl_detector
        
        # État du jour
        self.current_setup: Optional[SilverBulletSetup] = None
        self.daily_trades: int = 0
        self.max_daily_trades: int = 2  # Max 2 trades par jour avec cette stratégie
        self.last_reset_date: Optional[datetime] = None
        
        # Historique des sweeps détectés
        self.daily_sweeps: List[Dict] = []
        
    def is_in_window(self, current_time: datetime = None) -> Tuple[bool, str]:
        """
        Vérifie si on est dans la fenêtre Silver Bullet.
        
        Returns:
            (is_in_window, window_name)
        """
        if current_time is None:
            current_time = datetime.now()
        
        # Convertir en GMT
        gmt_time = current_time - timedelta(hours=self.timezone_offset)
        current_time_only = gmt_time.time()
        
        # Fenêtre AM (10:00-11:00 NY)
        if self.WINDOW_START_GMT <= current_time_only < self.WINDOW_END_GMT:
            return True, "AM Silver Bullet (10:00-11:00 NY)"
        
        # Fenêtre PM (2:00-3:00 NY) si activée
        if self.use_pm_window:
            if self.PM_WINDOW_START_GMT <= current_time_only < self.PM_WINDOW_END_GMT:
                return True, "PM Silver Bullet (14:00-15:00 NY)"
        
        return False, "Hors fenêtre Silver Bullet"
    
    def check_for_sweep(self, df: pd.DataFrame, 
                        swing_highs: List = None,
                        swing_lows: List = None,
                        pdh: float = None,
                        pdl: float = None) -> Optional[Dict]:
        """
        Cherche un sweep de liquidité pendant la fenêtre.
        
        Returns:
            Dict avec les détails du sweep ou None
        """
        if len(df) < 10:
            return None
        
        current_price = df.iloc[-1]['close']
        recent_high = df.iloc[-5:]['high'].max()
        recent_low = df.iloc[-5:]['low'].min()
        
        # Calculer le buffer en fonction du prix
        if current_price > 1000:  # XAUUSD
            buffer = self.min_sweep_pips * 0.1
        else:  # Forex
            buffer = self.min_sweep_pips * 0.0001
        
        sweep = None
        
        # Check PDH sweep
        if pdh is not None:
            if recent_high > pdh + buffer and current_price < pdh:
                sweep = {
                    "type": "PDH_SWEEP",
                    "level": pdh,
                    "sweep_price": recent_high,
                    "direction": "SELL",  # Après PDH sweep, on vend
                    "time": datetime.now()
                }
                logger.info(f"🎯 Silver Bullet: PDH Sweep détecté! {recent_high:.5f} > PDH {pdh:.5f}")
        
        # Check PDL sweep
        if pdl is not None and sweep is None:
            if recent_low < pdl - buffer and current_price > pdl:
                sweep = {
                    "type": "PDL_SWEEP",
                    "level": pdl,
                    "sweep_price": recent_low,
                    "direction": "BUY",  # Après PDL sweep, on achète
                    "time": datetime.now()
                }
                logger.info(f"🎯 Silver Bullet: PDL Sweep détecté! {recent_low:.5f} < PDL {pdl:.5f}")
        
        # Check swing high sweep
        if swing_highs and sweep is None:
            for sh in swing_highs[-3:]:  # Derniers 3 swing highs
                sh_price = sh.price if hasattr(sh, 'price') else sh
                if recent_high > sh_price + buffer and current_price < sh_price:
                    sweep = {
                        "type": "SWING_HIGH_SWEEP",
                        "level": sh_price,
                        "sweep_price": recent_high,
                        "direction": "SELL",
                        "time": datetime.now()
                    }
                    logger.info(f"🎯 Silver Bullet: Swing High Sweep! {recent_high:.5f} > SH {sh_price:.5f}")
                    break
        
        # Check swing low sweep
        if swing_lows and sweep is None:
            for sl in swing_lows[-3:]:  # Derniers 3 swing lows
                sl_price = sl.price if hasattr(sl, 'price') else sl
                if recent_low < sl_price - buffer and current_price > sl_price:
                    sweep = {
                        "type": "SWING_LOW_SWEEP",
                        "level": sl_price,
                        "sweep_price": recent_low,
                        "direction": "BUY",
                        "time": datetime.now()
                    }
                    logger.info(f"🎯 Silver Bullet: Swing Low Sweep! {recent_low:.5f} < SL {sl_price:.5f}")
                    break
        
        if sweep:
            self.daily_sweeps.append(sweep)
        
        return sweep
    
    def check_for_fvg(self, df: pd.DataFrame, 
                      expected_direction: str) -> Optional[Dict]:
        """
        Cherche un FVG dans la direction attendue après un sweep.
        
        Args:
            df: DataFrame OHLC
            expected_direction: "BUY" ou "SELL"
        """
        if self.fvg_detector is None:
            return None
        
        # Détecter les FVG récents
        fvgs, ifvgs = self.fvg_detector.detect(df)
        
        # Chercher le FVG le plus récent dans la bonne direction
        target_type = "bullish" if expected_direction == "BUY" else "bearish"
        
        recent_fvgs = [f for f in fvgs[-5:] if f.type.value == target_type]
        
        if recent_fvgs:
            fvg = recent_fvgs[-1]  # Le plus récent
            return {
                "type": fvg.type.value,
                "high": fvg.high,
                "low": fvg.low,
                "midpoint": fvg.midpoint,
                "index": fvg.index
            }
        
        return None
    
    def analyze(self, df: pd.DataFrame,
                structure: Dict = None,
                pdh: float = None,
                pdl: float = None) -> SilverBulletSetup:
        """
        Analyse complète pour la stratégie Silver Bullet.
        
        Returns:
            SilverBulletSetup avec le statut actuel
        """
        # Reset quotidien
        self._check_daily_reset()
        
        # Vérifier si on est dans la fenêtre
        in_window, window_name = self.is_in_window()
        
        if not in_window:
            return SilverBulletSetup(
                phase=SilverBulletPhase.WAITING,
                direction="NEUTRAL",
                sweep_price=0.0,
                sweep_time=datetime.now(),
                reasons=[f"⏳ {window_name}"]
            )
        
        # Vérifier si on a déjà atteint le max de trades
        if self.daily_trades >= self.max_daily_trades:
            return SilverBulletSetup(
                phase=SilverBulletPhase.COMPLETED,
                direction="NEUTRAL",
                sweep_price=0.0,
                sweep_time=datetime.now(),
                reasons=[f"Max trades quotidiens atteint ({self.max_daily_trades})"]
            )
        
        current_price = df.iloc[-1]['close']
        reasons = [f"📍 Dans fenêtre: {window_name}"]
        
        # Étape 1: Chercher un sweep
        swing_highs = structure.get('swing_highs', []) if structure else []
        swing_lows = structure.get('swing_lows', []) if structure else []
        
        sweep = self.check_for_sweep(df, swing_highs, swing_lows, pdh, pdl)
        
        if sweep is None:
            # Vérifier les sweeps récents (dernières 15 minutes)
            recent_sweep = self._get_recent_sweep()
            if recent_sweep:
                sweep = recent_sweep
            else:
                return SilverBulletSetup(
                    phase=SilverBulletPhase.WINDOW_OPEN,
                    direction="NEUTRAL",
                    sweep_price=0.0,
                    sweep_time=datetime.now(),
                    reasons=reasons + ["🔍 Recherche de sweep de liquidité..."]
                )
        
        reasons.append(f"✅ Sweep détecté: {sweep['type']} à {sweep['level']:.5f}")
        
        # Étape 2: Chercher un FVG
        fvg = self.check_for_fvg(df, sweep['direction'])
        
        if fvg is None:
            return SilverBulletSetup(
                phase=SilverBulletPhase.SWEEP_DETECTED,
                direction=sweep['direction'],
                sweep_price=sweep['sweep_price'],
                sweep_time=sweep['time'],
                reasons=reasons + ["🔍 Attente FVG après sweep..."]
            )
        
        reasons.append(f"✅ FVG détecté: {fvg['type']} [{fvg['low']:.5f}-{fvg['high']:.5f}]")
        
        # Étape 3: Vérifier si le prix est dans le FVG (entrée)
        in_fvg = fvg['low'] <= current_price <= fvg['high']
        
        # Calculer SL et TP
        if sweep['direction'] == "BUY":
            stop_loss = sweep['sweep_price'] - (self.min_sweep_pips * 0.0001 * 10)
            take_profit = fvg['high'] + ((fvg['high'] - sweep['sweep_price']) * 2)
        else:
            stop_loss = sweep['sweep_price'] + (self.min_sweep_pips * 0.0001 * 10)
            take_profit = fvg['low'] - ((sweep['sweep_price'] - fvg['low']) * 2)
        
        if in_fvg:
            reasons.append(f"🎯 Prix dans FVG! Entrée {sweep['direction']} prête")
            
            setup = SilverBulletSetup(
                phase=SilverBulletPhase.ENTRY_READY,
                direction=sweep['direction'],
                sweep_price=sweep['sweep_price'],
                sweep_time=sweep['time'],
                fvg_high=fvg['high'],
                fvg_low=fvg['low'],
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=85.0,
                reasons=reasons
            )
            
            self.current_setup = setup
            return setup
        else:
            reasons.append(f"⏳ Attente entrée dans FVG [{fvg['low']:.5f}-{fvg['high']:.5f}]")
            
            return SilverBulletSetup(
                phase=SilverBulletPhase.FVG_FORMED,
                direction=sweep['direction'],
                sweep_price=sweep['sweep_price'],
                sweep_time=sweep['time'],
                fvg_high=fvg['high'],
                fvg_low=fvg['low'],
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=70.0,
                reasons=reasons
            )
    
    def _get_recent_sweep(self, max_age_minutes: int = 15) -> Optional[Dict]:
        """Retourne le sweep le plus récent si récent."""
        if not self.daily_sweeps:
            return None
        
        cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
        
        for sweep in reversed(self.daily_sweeps):
            if sweep['time'] > cutoff:
                return sweep
        
        return None
    
    def _check_daily_reset(self):
        """Reset les données si nouveau jour."""
        today = datetime.now().date()
        
        if self.last_reset_date != today:
            self.daily_trades = 0
            self.daily_sweeps.clear()
            self.current_setup = None
            self.last_reset_date = today
            logger.debug("🔄 Silver Bullet: Reset quotidien")
    
    def record_trade(self):
        """Enregistre qu'un trade a été pris."""
        self.daily_trades += 1
        if self.current_setup:
            self.current_setup.phase = SilverBulletPhase.IN_TRADE
    
    def get_status(self) -> Dict:
        """Retourne le statut actuel de la stratégie."""
        in_window, window_name = self.is_in_window()
        
        return {
            "in_window": in_window,
            "window_name": window_name,
            "daily_trades": self.daily_trades,
            "max_trades": self.max_daily_trades,
            "sweeps_today": len(self.daily_sweeps),
            "current_phase": self.current_setup.phase.value if self.current_setup else "none"
        }
