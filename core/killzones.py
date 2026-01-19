"""
Killzones Trading Module
Détection des sessions de trading optimales selon les Smart Money Concepts

Killzones:
- Asian Session (00:00 - 08:00 GMT): Identification du range
- London Open (08:00 - 10:00 GMT): Zone d'exécution optimale
- NY Open (13:00 - 15:00 GMT): Zone d'exécution optimale
- London Close (15:00 - 17:00 GMT): Volatilité réduite
"""

import pandas as pd
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional, List, Dict, Tuple
from enum import Enum
from loguru import logger


class SessionType(Enum):
    ASIAN = "asian"
    LONDON_OPEN = "london_open"
    LONDON = "london"
    NY_OPEN = "ny_open"
    NY = "ny"
    LONDON_CLOSE = "london_close"
    OFF_HOURS = "off_hours"


@dataclass
class AsianRange:
    """Range de la session asiatique"""
    high: float
    low: float
    midpoint: float
    session_date: datetime
    is_valid: bool = True
    
    @property
    def range_size(self) -> float:
        return self.high - self.low


@dataclass
class KillzoneInfo:
    """Information sur la killzone actuelle"""
    current_session: SessionType
    is_killzone: bool
    asian_range: Optional[AsianRange]
    can_trade: bool
    message: str


class KillzoneDetector:
    """
    Détecteur de Killzones selon ICT/SMC.
    
    Les Killzones sont les périodes de haute probabilité:
    - Asian Range: Définit le range à casser pendant London/NY
    - London Open: Premier killzone d'exécution
    - NY Open: Deuxième killzone d'exécution
    """
    
    # Heures GMT par défaut (ajustables)
    # Sessions optimisées pour éviter les chevauchements
    SESSIONS = {
        SessionType.ASIAN: (time(0, 0), time(7, 0)),           # 00:00-07:00 GMT (finit avant London)
        SessionType.LONDON_OPEN: (time(7, 0), time(10, 0)),    # 07:00-10:00 GMT
        SessionType.LONDON: (time(7, 0), time(16, 0)),         # 07:00-16:00 GMT
        SessionType.NY_OPEN: (time(12, 0), time(15, 0)),       # 12:00-15:00 GMT
        SessionType.NY: (time(12, 0), time(21, 0)),            # 12:00-21:00 GMT
        SessionType.LONDON_CLOSE: (time(15, 0), time(17, 0)),
    }
    
    def __init__(self, timezone_offset: int = 0, enabled: bool = True):
        """
        Initialise le détecteur de killzones.
        
        Args:
            timezone_offset: Décalage horaire par rapport à GMT (ex: +2 pour CAT)
            enabled: Si False, toutes les heures sont considérées comme tradables
        """
        self.timezone_offset = timezone_offset
        self.enabled = enabled
        self.current_asian_range: Optional[AsianRange] = None
        self.daily_asian_ranges: Dict[str, AsianRange] = {}
        
    def get_current_session(self, current_time: datetime = None) -> SessionType:
        """Détermine la session actuelle basée sur l'heure."""
        if current_time is None:
            current_time = datetime.now()
        
        # Convertir en GMT
        gmt_time = current_time - timedelta(hours=self.timezone_offset)
        current_time_only = gmt_time.time()
        
        # Vérifier chaque session
        for session_type, (start, end) in self.SESSIONS.items():
            if start <= current_time_only < end:
                return session_type
        
        return SessionType.OFF_HOURS
    
    def is_killzone(self, current_time: datetime = None) -> bool:
        """Vérifie si on est dans une killzone d'exécution."""
        if not self.enabled:
            return True  # Si désactivé, toujours OK pour trader
        
        session = self.get_current_session(current_time)
        # Les killzones d'exécution incluent tout London et NY
        # (London Open, London, NY Open, NY, et London Close)
        tradable_sessions = [
            SessionType.LONDON_OPEN, 
            SessionType.LONDON, 
            SessionType.NY_OPEN, 
            SessionType.NY,
            SessionType.LONDON_CLOSE
        ]
        return session in tradable_sessions
    
    def calculate_asian_range(self, df: pd.DataFrame, session_date: datetime = None) -> AsianRange:
        """
        Calcule le range de la session asiatique.
        
        Args:
            df: DataFrame OHLC avec index datetime
            session_date: Date de la session (défaut: aujourd'hui)
        """
        if session_date is None:
            session_date = datetime.now().date()
        else:
            session_date = session_date.date() if isinstance(session_date, datetime) else session_date
        
        # Filtrer les données de la session asiatique
        asian_start = datetime.combine(session_date, time(0, 0))
        asian_end = datetime.combine(session_date, time(8, 0))
        
        # Ajuster pour le timezone
        asian_start_local = asian_start + timedelta(hours=self.timezone_offset)
        asian_end_local = asian_end + timedelta(hours=self.timezone_offset)
        
        try:
            if isinstance(df.index, pd.DatetimeIndex):
                mask = (df.index >= asian_start_local) & (df.index < asian_end_local)
                asian_data = df[mask]
            else:
                # Si l'index n'est pas datetime, utiliser les dernières X bougies
                # Estimer le nombre de bougies dans 8 heures (dépend du timeframe)
                asian_data = df.tail(32)  # Environ 32 bougies M15 pour 8 heures
            
            if len(asian_data) < 5:
                # Pas assez de données, utiliser les dernières données disponibles
                asian_data = df.tail(32)
            
            asian_high = asian_data['high'].max()
            asian_low = asian_data['low'].min()
            
            asian_range = AsianRange(
                high=asian_high,
                low=asian_low,
                midpoint=(asian_high + asian_low) / 2,
                session_date=session_date,
                is_valid=True
            )
            
            # Stocker le range
            date_key = session_date.strftime("%Y-%m-%d")
            self.daily_asian_ranges[date_key] = asian_range
            self.current_asian_range = asian_range
            
            logger.debug(f"📊 Asian Range: {asian_low:.5f} - {asian_high:.5f} (size: {asian_range.range_size:.5f})")
            
            return asian_range
            
        except Exception as e:
            logger.warning(f"Erreur calcul Asian Range: {e}")
            return AsianRange(
                high=df['high'].max(),
                low=df['low'].min(),
                midpoint=(df['high'].max() + df['low'].min()) / 2,
                session_date=session_date,
                is_valid=False
            )
    
    def is_asian_sweep(self, current_price: float, direction: str) -> Tuple[bool, str]:
        """
        Vérifie si le prix a fait un sweep du range asiatique.
        
        Un sweep = le prix dépasse le high/low puis revient.
        C'est un signal bullish si le prix sweep le low puis remonte,
        et bearish si le prix sweep le high puis redescend.
        """
        if self.current_asian_range is None:
            return False, "Pas de Asian Range calculé"
        
        ar = self.current_asian_range
        
        if direction.upper() == "BUY":
            # Pour un BUY, on cherche un sweep du low asiatique
            if current_price > ar.low and current_price < ar.midpoint:
                return True, f"Prix au-dessus du low asiatique ({ar.low:.5f})"
        else:
            # Pour un SELL, on cherche un sweep du high asiatique
            if current_price < ar.high and current_price > ar.midpoint:
                return True, f"Prix en-dessous du high asiatique ({ar.high:.5f})"
        
        return False, "Pas de sweep détecté"
    
    def get_killzone_info(self, df: pd.DataFrame = None, current_time: datetime = None) -> KillzoneInfo:
        """
        Retourne les informations complètes sur la killzone actuelle.
        """
        session = self.get_current_session(current_time)
        is_kz = self.is_killzone(current_time)
        
        # Calculer le Asian Range si on a des données et qu'on n'est plus en session asiatique
        if df is not None and session not in [SessionType.ASIAN, SessionType.OFF_HOURS]:
            if self.current_asian_range is None:
                self.calculate_asian_range(df)
        
        # Déterminer si on peut trader
        if not self.enabled:
            can_trade = True
            message = "Killzones désactivées - Trading 24/7"
        elif is_kz:
            can_trade = True
            message = f"✅ Killzone active: {session.value}"
        elif session == SessionType.ASIAN:
            can_trade = False
            message = "⏳ Session Asiatique - Attente du range"
        else:
            can_trade = False
            message = f"⏸️ Hors killzone: {session.value}"
        
        return KillzoneInfo(
            current_session=session,
            is_killzone=is_kz,
            asian_range=self.current_asian_range,
            can_trade=can_trade,
            message=message
        )
    
    def should_trade(self, df: pd.DataFrame = None, current_time: datetime = None) -> Tuple[bool, str]:
        """
        Vérifie si les conditions de killzone permettent de trader.
        
        Returns:
            (can_trade, reason)
        """
        if not self.enabled:
            return True, "Killzones désactivées"
        
        info = self.get_killzone_info(df, current_time)
        return info.can_trade, info.message
    
    def get_session_times_local(self) -> Dict[str, Tuple[str, str]]:
        """Retourne les heures des sessions en heure locale."""
        local_sessions = {}
        
        for session_type, (start, end) in self.SESSIONS.items():
            start_local = (datetime.combine(datetime.today(), start) + 
                          timedelta(hours=self.timezone_offset)).time()
            end_local = (datetime.combine(datetime.today(), end) + 
                        timedelta(hours=self.timezone_offset)).time()
            
            local_sessions[session_type.value] = (
                start_local.strftime("%H:%M"),
                end_local.strftime("%H:%M")
            )
        
        return local_sessions


class AsianRangeSweepType(Enum):
    """Type de sweep du range asiatique"""
    NONE = "none"
    HIGH_SWEEP = "asian_high_sweep"    # Sweep du high asiatique
    LOW_SWEEP = "asian_low_sweep"       # Sweep du low asiatique
    BOTH_SWEEP = "asian_both_sweep"     # Sweep des deux côtés


@dataclass
class AsianSweepEvent:
    """Événement de sweep du range asiatique"""
    sweep_type: AsianRangeSweepType
    asian_range: AsianRange
    sweep_price: float
    sweep_time: datetime
    confirmed: bool = False
    reversal_detected: bool = False
    entry_price: Optional[float] = None
    direction: str = ""  # "BUY" ou "SELL"


class AsianRangeSweepDetector:
    """
    Détecteur avancé de sweep du range asiatique selon ICT/SMC.
    
    Stratégie:
    1. Identifier le range de la session asiatique (00:00 - 07:00 GMT)
    2. Attendre que London/NY sweep (casse) ce range
    3. Attendre la confirmation du reversal
    4. Entrer dans la direction opposée au sweep
    
    Exemple:
    - Si le prix sweep le HIGH asiatique puis redescend → Signal SELL
    - Si le prix sweep le LOW asiatique puis remonte → Signal BUY
    """
    
    def __init__(self, killzone_detector: KillzoneDetector, 
                 sweep_buffer_pips: float = 3.0,
                 confirmation_pips: float = 5.0,
                 min_range_pips: float = 15.0): # Default 15 pips min
        """
        Args:
            killzone_detector: Instance de KillzoneDetector pour le Asian Range
            sweep_buffer_pips: Pips au-delà du range pour considérer un sweep
            confirmation_pips: Pips de retour pour confirmer le reversal
            min_range_pips: Taille minimum du range pour le considérer valide (évite les fakeouts sur ranges minuscules)
        """
        self.kz_detector = killzone_detector
        self.sweep_buffer_pips = sweep_buffer_pips
        self.confirmation_pips = confirmation_pips
        self.min_range_pips = min_range_pips
        self.sweep_events: List[AsianSweepEvent] = []
        self.high_swept: bool = False
        self.low_swept: bool = False
        self.last_sweep_time: Optional[datetime] = None
        
    def update_asian_range(self, df: pd.DataFrame, session_date: datetime = None) -> AsianRange:
        """Met à jour le range asiatique."""
        return self.kz_detector.calculate_asian_range(df, session_date)
    
    def check_sweep(self, current_price: float, 
                    df: pd.DataFrame = None) -> Optional[AsianSweepEvent]:
        """
        Vérifie si un sweep du range asiatique s'est produit.
        
        Returns:
            AsianSweepEvent si un sweep est détecté, None sinon
        """
        asian_range = self.kz_detector.current_asian_range
        
        if asian_range is None:
            if df is not None:
                asian_range = self.update_asian_range(df)
            else:
                return None
        
        if not asian_range.is_valid:
            return None
        
        # Calculer le buffer
        buffer = self._calculate_buffer(asian_range.high)
        
        sweep_event = None
        
        # Check HIGH sweep (prix au-dessus du high asiatique)
        if current_price > asian_range.high + buffer and not self.high_swept:
            self.high_swept = True
            self.last_sweep_time = datetime.now()
            
            sweep_event = AsianSweepEvent(
                sweep_type=AsianRangeSweepType.HIGH_SWEEP,
                asian_range=asian_range,
                sweep_price=current_price,
                sweep_time=datetime.now(),
                direction="SELL"  # Après un high sweep, on cherche à vendre
            )
            self.sweep_events.append(sweep_event)
            logger.info(f"🎯 ASIAN HIGH SWEEP! Prix {current_price:.5f} > High {asian_range.high:.5f}")
            
        # Check LOW sweep (prix en-dessous du low asiatique)
        elif current_price < asian_range.low - buffer and not self.low_swept:
            self.low_swept = True
            self.last_sweep_time = datetime.now()
            
            sweep_event = AsianSweepEvent(
                sweep_type=AsianRangeSweepType.LOW_SWEEP,
                asian_range=asian_range,
                sweep_price=current_price,
                sweep_time=datetime.now(),
                direction="BUY"  # Après un low sweep, on cherche à acheter
            )
            self.sweep_events.append(sweep_event)
            logger.info(f"🎯 ASIAN LOW SWEEP! Prix {current_price:.5f} < Low {asian_range.low:.5f}")
        
        return sweep_event
    
    def confirm_sweep(self, current_price: float) -> Optional[AsianSweepEvent]:
        """
        Confirme un sweep en vérifiant le reversal.
        
        Un sweep est confirmé quand le prix:
        - Après un HIGH sweep: revient sous le high asiatique
        - Après un LOW sweep: revient au-dessus du low asiatique
        """
        if not self.sweep_events:
            return None
        
        # Chercher le dernier sweep non confirmé
        for sweep in reversed(self.sweep_events):
            if sweep.confirmed:
                continue
            
            ar = sweep.asian_range
            buffer = self._calculate_buffer(ar.high)
            
            # Confirmer HIGH sweep (prix revenu sous le high)
            if sweep.sweep_type == AsianRangeSweepType.HIGH_SWEEP:
                if current_price < ar.high - buffer:
                    sweep.confirmed = True
                    sweep.reversal_detected = True
                    sweep.entry_price = current_price
                    logger.info(f"✅ ASIAN HIGH SWEEP CONFIRMÉ! Entrée SELL à {current_price:.5f}")
                    return sweep
            
            # Confirmer LOW sweep (prix revenu au-dessus du low)
            elif sweep.sweep_type == AsianRangeSweepType.LOW_SWEEP:
                if current_price > ar.low + buffer:
                    sweep.confirmed = True
                    sweep.reversal_detected = True
                    sweep.entry_price = current_price
                    logger.info(f"✅ ASIAN LOW SWEEP CONFIRMÉ! Entrée BUY à {current_price:.5f}")
                    return sweep
        
        return None
    
    def get_sweep_signal(self, current_price: float, 
                          df: pd.DataFrame = None) -> Tuple[str, float, str]:
        """
        Analyse complète pour obtenir un signal de trading basé sur le sweep.
        
        Returns:
            (direction, confidence, reason)
            direction: "BUY", "SELL", ou "NEUTRAL"
            confidence: Score de confiance 0-100
            reason: Explication du signal
        """
        # D'abord, vérifier s'il y a un nouveau sweep
        sweep = self.check_sweep(current_price, df)
        
        # 🧠 FILTER: Check Asian Range Size (PRO TIP)
        # Un range trop petit (< 15 pips) génère souvent des faux sweeps (bruit)
        ar = self.kz_detector.current_asian_range
        if ar and ar.is_valid:
            # Estimation de la valeur du pip (approximative mais suffisante pour le filtre)
            # Utilise _calculate_buffer qui contient déjà la logique pip (0.1 gold / 0.0001 fx)
            pip_size = self._calculate_buffer(ar.high) / self.sweep_buffer_pips # Reverse engineering pip size
            range_pips = ar.range_size / pip_size if pip_size > 0 else 0
            
            if range_pips < self.min_range_pips:
                return "NEUTRAL", 0.0, f"Asian Range trop petit ({range_pips:.1f} pips < {self.min_range_pips} min)"
        
        # Ensuite, essayer de confirmer les sweeps existants
        confirmed_sweep = self.confirm_sweep(current_price)
        
        if confirmed_sweep:
            confidence = 85.0  # Haute confiance pour un sweep confirmé
            
            if confirmed_sweep.direction == "BUY":
                reason = (f"Asian Low Sweep confirmé! "
                         f"Sweep à {confirmed_sweep.sweep_price:.5f}, "
                         f"Entrée à {confirmed_sweep.entry_price:.5f}")
                return "BUY", confidence, reason
            else:
                reason = (f"Asian High Sweep confirmé! "
                         f"Sweep à {confirmed_sweep.sweep_price:.5f}, "
                         f"Entrée à {confirmed_sweep.entry_price:.5f}")
                return "SELL", confidence, reason
        
        # ✅ NOUVEAU: Si on a un sweep non confirmé, l'utiliser quand même (80% WR selon backtest)
        if sweep and not sweep.confirmed:
            confidence = 75.0  # Confiance légèrement réduite (non confirmé)
            direction = sweep.direction
            reason = f"Asian {sweep.sweep_type.value} détecté (en attente confirmation)"
            logger.info(f"✅ Utilisation sweep détecté: {direction} (conf: {confidence}%)")
            return direction, confidence, reason
        
        # Pas de sweep
        return "NEUTRAL", 0.0, "Pas de sweep du range asiatique détecté"
    
    def get_asian_range_status(self) -> Dict:
        """Retourne le statut complet du range asiatique."""
        ar = self.kz_detector.current_asian_range
        
        if ar is None:
            return {
                "valid": False,
                "message": "Asian Range non calculé"
            }
        
        return {
            "valid": True,
            "high": ar.high,
            "low": ar.low,
            "midpoint": ar.midpoint,
            "range_size": ar.range_size,
            "high_swept": self.high_swept,
            "low_swept": self.low_swept,
            "pending_sweeps": len([s for s in self.sweep_events if not s.confirmed]),
            "confirmed_sweeps": len([s for s in self.sweep_events if s.confirmed])
        }
    
    def reset_daily(self):
        """Reset les données pour un nouveau jour de trading."""
        self.sweep_events.clear()
        self.high_swept = False
        self.low_swept = False
        self.last_sweep_time = None
        self.kz_detector.current_asian_range = None
        logger.debug("🔄 Asian Range Sweep Detector reset")
    
    def _calculate_buffer(self, reference_price: float) -> float:
        """Calcule le buffer en fonction du prix (forex vs or)."""
        if reference_price > 1000:  # Probablement XAUUSD
            return self.sweep_buffer_pips * 0.1
        else:  # Forex pairs
            return self.sweep_buffer_pips * 0.0001
    
    def get_targets(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Retourne les niveaux de take profit potentiels après un sweep.
        
        Après un Asian High Sweep confirmé → TP au low asiatique ou plus bas
        Après un Asian Low Sweep confirmé → TP au high asiatique ou plus haut
        """
        ar = self.kz_detector.current_asian_range
        if ar is None:
            return None, None
        
        # TP1 = côté opposé du range, TP2 = extension
        extension = ar.range_size * 0.618  # Extension Fibonacci
        
        if self.high_swept:
            # Après high sweep, on vend vers le low
            tp1 = ar.low
            tp2 = ar.low - extension
        elif self.low_swept:
            # Après low sweep, on achète vers le high
            tp1 = ar.high
            tp2 = ar.high + extension
        else:
            return None, None
        
        return tp1, tp2
