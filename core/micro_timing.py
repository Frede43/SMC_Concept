"""
ICT Micro-Timing Module
=======================
Filtre les entrées selon le timing ICT précis.

Concepts ICT implémentés:
- Power of 3 (PO3): Open → High/Low → Close
- Optimal Entry Windows dans chaque killzone
- Éviter les premières 10 minutes (manipulation initiale)
- Time-Based Targets

Fenêtres optimales par session:
- London Open (08:00-10:00 GMT): Minutes 10-30 optimales
- NY Open (13:00-15:00 GMT): Minutes 10-30 optimales
- Silver Bullet (10:00-11:00 NY): Toute la fenêtre
"""

import sys
from pathlib import Path
from datetime import datetime, time, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
from loguru import logger

# Ajouter le répertoire racine au path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))


class SessionPhase(Enum):
    """Phase de la session actuelle."""
    PRE_SESSION = "pre_session"       # Avant la session
    INITIAL_CHAOS = "initial_chaos"   # 0-10 min (manipulation)
    OPTIMAL_ENTRY = "optimal_entry"   # 10-30 min (entrée idéale)
    EXPANSION = "expansion"           # 30-60 min (mouvement en cours)
    LATE_SESSION = "late_session"     # 60+ min (risque de reversal)
    POST_SESSION = "post_session"     # Après la session


class PO3Phase(Enum):
    """Power of 3 Phase (Open → Drive → Close)."""
    ACCUMULATION = "accumulation"     # 00:00-04:00 (Asian)
    MANIPULATION = "manipulation"     # 04:00-10:00 (London pre-move)
    DISTRIBUTION = "distribution"     # 10:00-16:00 (Real move)
    RETRACEMENT = "retracement"       # 16:00-00:00 (Pullback)


@dataclass
class SessionWindow:
    """Fenêtre de trading d'une session."""
    name: str
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    
    # Configuration des phases (en minutes depuis le début)
    initial_chaos_end: int = 10      # Fin du chaos initial
    optimal_entry_end: int = 30      # Fin de la fenêtre optimale
    expansion_end: int = 60          # Fin de l'expansion
    
    # Qualité de la session
    quality: str = "GOOD"  # PRIME, GOOD, AVERAGE, AVOID
    
    def get_start_time(self) -> time:
        return time(self.start_hour, self.start_minute)
    
    def get_end_time(self) -> time:
        return time(self.end_hour, self.end_minute)


@dataclass
class TimingAnalysis:
    """Résultat de l'analyse de timing."""
    current_time: datetime
    
    # Session
    session_name: str = "OFF_HOURS"
    session_phase: SessionPhase = SessionPhase.POST_SESSION
    session_quality: str = "AVOID"
    minutes_into_session: int = 0
    minutes_until_close: int = 0
    
    # Power of 3
    po3_phase: PO3Phase = PO3Phase.RETRACEMENT
    
    # Décision
    can_enter: bool = False
    entry_quality: str = "AVOID"
    reason: str = ""
    warnings: List[str] = field(default_factory=list)
    
    # Timing avancé
    asian_range_formed: bool = False
    london_opened: bool = False
    ny_opened: bool = False
    
    def to_dict(self) -> Dict:
        return {
            'current_time': self.current_time.strftime('%H:%M:%S'),
            'session': {
                'name': self.session_name,
                'phase': self.session_phase.value,
                'quality': self.session_quality,
                'minutes_in': self.minutes_into_session,
                'minutes_until_close': self.minutes_until_close
            },
            'po3_phase': self.po3_phase.value,
            'decision': {
                'can_enter': self.can_enter,
                'entry_quality': self.entry_quality,
                'reason': self.reason
            },
            'warnings': self.warnings
        }


class ICTMicroTiming:
    """
    Système de micro-timing ICT pour optimiser les entrées.
    
    Implémente:
    - Fenêtres optimales par session
    - Power of 3 journalier
    - Évitement de la manipulation initiale
    - Score de qualité d'entrée
    """
    
    # Définition des sessions (horaires GMT)
    SESSIONS = {
        'asian': SessionWindow(
            name='Asian',
            start_hour=0, start_minute=0,
            end_hour=8, end_minute=0,
            quality='AVOID'  # Pas de trading, juste observation
        ),
        'london_open': SessionWindow(
            name='London Open',
            start_hour=8, start_minute=0,
            end_hour=10, end_minute=0,
            initial_chaos_end=10,
            optimal_entry_end=30,
            quality='PRIME'
        ),
        'london': SessionWindow(
            name='London',
            start_hour=10, start_minute=0,
            end_hour=12, end_minute=0,
            quality='GOOD'
        ),
        'london_lunch': SessionWindow(
            name='London Lunch',
            start_hour=12, start_minute=0,
            end_hour=13, end_minute=0,
            quality='AVOID'  # Lunch = faible volume
        ),
        'ny_open': SessionWindow(
            name='NY Open',
            start_hour=13, start_minute=0,
            end_hour=15, end_minute=0,
            initial_chaos_end=10,
            optimal_entry_end=30,
            quality='PRIME'
        ),
        'ny': SessionWindow(
            name='NY',
            start_hour=15, start_minute=0,
            end_hour=17, end_minute=0,
            quality='GOOD'
        ),
        'london_close': SessionWindow(
            name='London Close',
            start_hour=17, start_minute=0,
            end_hour=18, end_minute=0,
            quality='AVERAGE'
        ),
        'ny_close': SessionWindow(
            name='NY Close',
            start_hour=20, start_minute=0,
            end_hour=22, end_minute=0,
            quality='AVOID'
        )
    }
    
    # Power of 3 horaires (GMT)
    PO3_SCHEDULE = {
        PO3Phase.ACCUMULATION: (0, 4),    # 00:00-04:00
        PO3Phase.MANIPULATION: (4, 10),   # 04:00-10:00
        PO3Phase.DISTRIBUTION: (10, 16),  # 10:00-16:00
        PO3Phase.RETRACEMENT: (16, 24)    # 16:00-00:00
    }
    
    def __init__(self, timezone_offset: int = 0, config: Dict = None):
        """
        Args:
            timezone_offset: Décalage horaire par rapport à GMT
            config: Configuration optionnelle
        """
        self.timezone_offset = timezone_offset
        self.config = config or {}
        
        # Configuration
        self.avoid_initial_chaos = self.config.get('avoid_initial_chaos', True)
        self.prefer_optimal_window = self.config.get('prefer_optimal_window', True)
        self.allow_late_entry = self.config.get('allow_late_entry', False)
        
        logger.info(f"⏰ ICT MicroTiming initialized: TZ offset={timezone_offset}")
    
    def analyze(self, current_time: datetime = None) -> TimingAnalysis:
        """
        Analyse le timing actuel et retourne les recommandations.
        
        Args:
            current_time: Heure à analyser (défaut: maintenant)
            
        Returns:
            TimingAnalysis avec toutes les informations
        """
        if current_time is None:
            current_time = datetime.now()
        
        # Convertir en GMT pour l'analyse
        gmt_time = current_time - timedelta(hours=self.timezone_offset)
        gmt_hour = gmt_time.hour
        gmt_minute = gmt_time.minute
        
        analysis = TimingAnalysis(current_time=current_time)
        
        # 1. Déterminer la session actuelle
        self._determine_session(analysis, gmt_hour, gmt_minute)
        
        # 2. Déterminer la phase Power of 3
        self._determine_po3_phase(analysis, gmt_hour)
        
        # 3. Déterminer la phase dans la session
        self._determine_session_phase(analysis, gmt_hour, gmt_minute)
        
        # 4. Évaluer si l'entrée est permise
        self._evaluate_entry(analysis)
        
        # 5. Ajouter des informations contextuelles
        analysis.asian_range_formed = gmt_hour >= 8
        analysis.london_opened = gmt_hour >= 8
        analysis.ny_opened = gmt_hour >= 13
        
        return analysis
    
    def _determine_session(self, analysis: TimingAnalysis, hour: int, minute: int):
        """Détermine quelle session est active."""
        current_minutes = hour * 60 + minute
        
        for session_key, session in self.SESSIONS.items():
            start_minutes = session.start_hour * 60 + session.start_minute
            end_minutes = session.end_hour * 60 + session.end_minute
            
            if start_minutes <= current_minutes < end_minutes:
                analysis.session_name = session.name
                analysis.session_quality = session.quality
                analysis.minutes_into_session = current_minutes - start_minutes
                analysis.minutes_until_close = end_minutes - current_minutes
                return
        
        # Hors sessions
        analysis.session_name = "OFF_HOURS"
        analysis.session_quality = "AVOID"
    
    def _determine_po3_phase(self, analysis: TimingAnalysis, hour: int):
        """Détermine la phase Power of 3."""
        for phase, (start, end) in self.PO3_SCHEDULE.items():
            if start <= hour < end:
                analysis.po3_phase = phase
                return
        
        analysis.po3_phase = PO3Phase.RETRACEMENT
    
    def _determine_session_phase(self, analysis: TimingAnalysis, hour: int, minute: int):
        """Détermine la phase dans la session actuelle."""
        # Trouver la session active
        session = None
        for s in self.SESSIONS.values():
            if s.name == analysis.session_name:
                session = s
                break
        
        if session is None or analysis.session_quality == "AVOID":
            analysis.session_phase = SessionPhase.POST_SESSION
            return
        
        mins = analysis.minutes_into_session
        
        if mins < 0:
            analysis.session_phase = SessionPhase.PRE_SESSION
        elif mins < session.initial_chaos_end:
            analysis.session_phase = SessionPhase.INITIAL_CHAOS
        elif mins < session.optimal_entry_end:
            analysis.session_phase = SessionPhase.OPTIMAL_ENTRY
        elif mins < session.expansion_end:
            analysis.session_phase = SessionPhase.EXPANSION
        else:
            analysis.session_phase = SessionPhase.LATE_SESSION
    
    def _evaluate_entry(self, analysis: TimingAnalysis):
        """Évalue si l'entrée est autorisée et avec quelle qualité."""
        phase = analysis.session_phase
        quality = analysis.session_quality
        
        # Sessions à éviter
        if quality == "AVOID":
            analysis.can_enter = False
            analysis.entry_quality = "AVOID"
            analysis.reason = f"Session {analysis.session_name} non recommandée pour trading"
            return
        
        # Phase de chaos initial
        if phase == SessionPhase.INITIAL_CHAOS:
            if self.avoid_initial_chaos:
                analysis.can_enter = False
                analysis.entry_quality = "WAIT"
                analysis.reason = f"Premières {analysis.minutes_into_session} min - Attendre fin du chaos"
                analysis.warnings.append("⏳ Phase de manipulation initiale en cours")
            else:
                analysis.can_enter = True
                analysis.entry_quality = "RISKY"
                analysis.reason = "Entrée possible mais risquée (chaos initial)"
            return
        
        # Fenêtre optimale
        if phase == SessionPhase.OPTIMAL_ENTRY:
            analysis.can_enter = True
            analysis.entry_quality = "OPTIMAL"
            analysis.reason = f"✅ Fenêtre optimale (minute {analysis.minutes_into_session})"
            return
        
        # Phase d'expansion
        if phase == SessionPhase.EXPANSION:
            analysis.can_enter = True
            analysis.entry_quality = "GOOD"
            analysis.reason = f"Phase d'expansion (minute {analysis.minutes_into_session})"
            analysis.warnings.append("⚠️ Entrée tardive - mouvement peut être avancé")
            return
        
        # Late session
        if phase == SessionPhase.LATE_SESSION:
            if self.allow_late_entry:
                analysis.can_enter = True
                analysis.entry_quality = "RISKY"
                analysis.reason = "Entrée tardive autorisée mais risquée"
                analysis.warnings.append("⚠️ Fin de session - risque de reversal")
            else:
                analysis.can_enter = False
                analysis.entry_quality = "AVOID"
                analysis.reason = "Fin de session - éviter les nouvelles entrées"
            return
        
        # Hors session
        analysis.can_enter = False
        analysis.entry_quality = "AVOID"
        analysis.reason = "Hors session de trading"
    
    def is_optimal_entry_time(self, current_time: datetime = None) -> Tuple[bool, str]:
        """
        Vérifie rapidement si c'est un bon moment pour entrer.
        
        Returns:
            (can_enter, reason)
        """
        analysis = self.analyze(current_time)
        return analysis.can_enter, analysis.reason
    
    def get_next_optimal_window(self, current_time: datetime = None) -> Optional[datetime]:
        """
        Retourne le prochain moment optimal pour trader.
        
        Returns:
            Datetime de la prochaine fenêtre optimale, ou None si aujourd'hui
        """
        if current_time is None:
            current_time = datetime.now()
        
        # Convertir en GMT
        gmt_time = current_time - timedelta(hours=self.timezone_offset)
        gmt_hour = gmt_time.hour
        
        # Sessions PRIME avec leurs heures de début optimales (après chaos)
        optimal_times = [
            (8, 10),   # London Open + 10 min
            (13, 10),  # NY Open + 10 min
        ]
        
        for start_hour, offset_min in optimal_times:
            optimal_hour = start_hour
            optimal_min = offset_min
            
            # Si c'est dans le futur aujourd'hui
            if gmt_hour < optimal_hour or (gmt_hour == optimal_hour and gmt_time.minute < optimal_min):
                next_window = current_time.replace(
                    hour=(optimal_hour + self.timezone_offset) % 24,
                    minute=optimal_min,
                    second=0, microsecond=0
                )
                return next_window
        
        # Sinon, demain London Open
        tomorrow = current_time + timedelta(days=1)
        return tomorrow.replace(
            hour=(8 + self.timezone_offset) % 24,
            minute=10,
            second=0, microsecond=0
        )
    
    def get_session_quality_score(self, current_time: datetime = None) -> int:
        """
        Retourne un score de qualité de 0 à 100.
        
        Returns:
            Score de qualité
        """
        analysis = self.analyze(current_time)
        
        # Score de base par qualité de session
        quality_scores = {
            "PRIME": 80,
            "GOOD": 60,
            "AVERAGE": 40,
            "AVOID": 10
        }
        
        base_score = quality_scores.get(analysis.session_quality, 0)
        
        # Bonus/Malus par phase
        phase_modifiers = {
            SessionPhase.OPTIMAL_ENTRY: 20,
            SessionPhase.EXPANSION: 10,
            SessionPhase.INITIAL_CHAOS: -20,
            SessionPhase.LATE_SESSION: -10,
            SessionPhase.PRE_SESSION: -30,
            SessionPhase.POST_SESSION: -40
        }
        
        modifier = phase_modifiers.get(analysis.session_phase, 0)
        
        # Bonus PO3 Distribution
        if analysis.po3_phase == PO3Phase.DISTRIBUTION:
            modifier += 10
        
        return max(0, min(100, base_score + modifier))
    
    def print_status(self, current_time: datetime = None):
        """Affiche le status actuel de manière formatée."""
        analysis = self.analyze(current_time)
        
        print("\n" + "=" * 50)
        print("⏰ ICT MICRO-TIMING STATUS")
        print("=" * 50)
        print(f"  Current Time: {analysis.current_time.strftime('%H:%M:%S')}")
        print(f"  Session: {analysis.session_name} ({analysis.session_quality})")
        print(f"  Phase: {analysis.session_phase.value}")
        print(f"  PO3: {analysis.po3_phase.value}")
        print(f"  Minutes in Session: {analysis.minutes_into_session}")
        print(f"\n  Can Enter: {'✅ YES' if analysis.can_enter else '❌ NO'}")
        print(f"  Entry Quality: {analysis.entry_quality}")
        print(f"  Reason: {analysis.reason}")
        
        if analysis.warnings:
            print("\n  ⚠️ Warnings:")
            for w in analysis.warnings:
                print(f"     {w}")
        
        print(f"\n  Quality Score: {self.get_session_quality_score(current_time)}/100")
        print("=" * 50 + "\n")


# ============================================
# SCRIPT DE TEST
# ============================================
if __name__ == "__main__":
    # Test du système de timing
    timing = ICTMicroTiming(timezone_offset=2)  # UTC+2
    
    # Test avec différentes heures
    test_times = [
        datetime(2024, 12, 28, 7, 0),   # Asian
        datetime(2024, 12, 28, 10, 5),  # London Open - Chaos
        datetime(2024, 12, 28, 10, 25), # London Open - Optimal
        datetime(2024, 12, 28, 12, 0),  # London
        datetime(2024, 12, 28, 15, 15), # NY Open - Optimal
        datetime(2024, 12, 28, 18, 0),  # Late session
    ]
    
    for t in test_times:
        print(f"\n{'='*60}")
        print(f"Testing: {t.strftime('%Y-%m-%d %H:%M')}")
        timing.print_status(t)
        
        can_enter, reason = timing.is_optimal_entry_time(t)
        score = timing.get_session_quality_score(t)
        print(f"Quick check: can_enter={can_enter}, score={score}")
