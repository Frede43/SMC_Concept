"""
Anti-Tilt System & Advanced Position Sizing
============================================
Système avancé de gestion du risque qui ajuste automatiquement la taille
des positions en fonction de:
- Drawdown actuel (réduction progressive du risque)
- Performance récente (Kelly Criterion adaptatif)
- Conditions de marché (volatilité)
- État psychologique (séries de pertes)

Protège le capital mathématiquement ET psychologiquement.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from loguru import logger
from collections import deque

# Ajouter le répertoire racine au path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))


@dataclass
class PositionSizeResult:
    """Résultat du calcul de taille de position."""
    base_risk_percent: float
    adjusted_risk_percent: float
    adjustment_factor: float
    lot_size: float
    reason: str
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            'base_risk': f"{self.base_risk_percent:.2f}%",
            'adjusted_risk': f"{self.adjusted_risk_percent:.2f}%",
            'adjustment_factor': f"{self.adjustment_factor:.2f}",
            'lot_size': self.lot_size,
            'reason': self.reason,
            'warnings': self.warnings
        }


@dataclass
class TradingState:
    """État actuel du système de trading."""
    current_equity: float = 0.0
    peak_equity: float = 0.0
    current_drawdown_pct: float = 0.0
    
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    trades_today: int = 0
    
    # Performance récente (sliding window)
    recent_trades_pnl: float = 0.0
    recent_win_rate: float = 0.0
    recent_avg_win: float = 0.0
    recent_avg_loss: float = 0.0
    
    # Kelly Criterion
    kelly_optimal: float = 0.0
    kelly_adjusted: float = 0.0
    
    # État de risque
    risk_level: str = "NORMAL"  # NORMAL, REDUCED, MINIMAL, STOPPED
    risk_multiplier: float = 1.0
    
    # Timestamps
    last_trade_time: Optional[datetime] = None
    last_loss_time: Optional[datetime] = None
    locked_until: Optional[datetime] = None  # Trading bloqué jusqu'à


class AntiTiltSystem:
    """
    Système Anti-Tilt avancé.
    
    Réduit automatiquement le risque pendant les périodes difficiles
    pour préserver le capital et la santé mentale du trader.
    
    Paliers de protection:
    - 5% DD → Risque réduit à 75%
    - 10% DD → Risque réduit à 50%
    - 15% DD → Risque réduit à 25%
    - 20% DD → STOP TRADING (lock 24h ou reset manuel)
    
    Protection contre les séries de pertes:
    - 3 pertes consécutives → Pause 30 min
    - 5 pertes consécutives → Pause 2h
    - 7 pertes consécutives → STOP TRADING
    """
    
    # Paliers de réduction du risque basés sur le drawdown
    DRAWDOWN_LEVELS = {
        5: 0.75,   # -5% DD → risque à 75%
        10: 0.50,  # -10% DD → risque à 50%
        15: 0.25,  # -15% DD → risque à 25%
        20: 0.0,   # -20% DD → STOP TRADING
    }
    
    # Paliers basés sur les pertes consécutives
    LOSS_STREAK_ACTIONS = {
        3: ("PAUSE", 30),    # 3 pertes → pause 30 min
        5: ("PAUSE", 120),   # 5 pertes → pause 2h
        7: ("STOP", 0),      # 7 pertes → stop trading
    }
    
    def __init__(self, config: Dict = None):
        """
        Args:
            config: Configuration optionnelle
        """
        self.config = config or {}
        
        # Configuration
        self.base_risk_percent = self.config.get('base_risk_percent', 1.0)
        self.max_daily_loss_percent = self.config.get('max_daily_loss_percent', 3.0)
        self.max_daily_trades = self.config.get('max_daily_trades', 5)
        
        # Kelly Criterion settings
        self.use_kelly = self.config.get('use_kelly', True)
        self.kelly_fraction = self.config.get('kelly_fraction', 0.25)  # Quart-Kelly
        self.kelly_lookback = self.config.get('kelly_lookback', 20)  # 20 derniers trades
        
        # État
        self.state = TradingState()
        
        # Historique des trades (sliding window)
        self.trade_history: deque = deque(maxlen=100)
        
        # Date du dernier reset quotidien
        self.last_daily_reset: Optional[datetime] = None
        
        logger.info(f"🛡️ AntiTilt System initialized: Base risk={self.base_risk_percent}%")
    
    def update_equity(self, current_equity: float, trade_pnl: float = None, 
                      is_win: bool = None) -> TradingState:
        """
        Met à jour l'état avec la nouvelle équité.
        
        Args:
            current_equity: Équité actuelle
            trade_pnl: PnL du dernier trade (si applicable)
            is_win: Si le trade était gagnant
            
        Returns:
            État mis à jour
        """
        # Vérifier reset quotidien
        self._check_daily_reset()
        
        # Mettre à jour l'équité
        self.state.current_equity = current_equity
        if current_equity > self.state.peak_equity:
            self.state.peak_equity = current_equity
        
        # Calculer le drawdown
        if self.state.peak_equity > 0:
            self.state.current_drawdown_pct = (
                (self.state.peak_equity - current_equity) / self.state.peak_equity * 100
            )
        
        # Si un trade a été enregistré
        if trade_pnl is not None:
            self._record_trade(trade_pnl, is_win)
        
        # Calculer le Kelly Criterion
        if self.use_kelly and len(self.trade_history) >= 10:
            self._calculate_kelly()
        
        # Déterminer le niveau de risque
        self._evaluate_risk_level()
        
        return self.state
    
    def _record_trade(self, pnl: float, is_win: bool = None):
        """Enregistre un trade dans l'historique."""
        if is_win is None:
            is_win = pnl > 0
        
        # Ajouter à l'historique
        self.trade_history.append({
            'pnl': pnl,
            'is_win': is_win,
            'time': datetime.now()
        })
        
        self.state.trades_today += 1
        self.state.last_trade_time = datetime.now()
        
        # Mettre à jour les séries
        if is_win:
            self.state.consecutive_wins += 1
            self.state.consecutive_losses = 0
        else:
            self.state.consecutive_losses += 1
            self.state.consecutive_wins = 0
            self.state.last_loss_time = datetime.now()
            
            # Vérifier si on doit activer une pause
            self._check_loss_streak_action()
        
        # Mettre à jour les statistiques récentes
        self._update_recent_stats()
        
        logger.info(f"📊 Trade recorded: PnL=${pnl:.2f}, "
                   f"ConsecWins={self.state.consecutive_wins}, "
                   f"ConsecLosses={self.state.consecutive_losses}")
    
    def _check_loss_streak_action(self):
        """Vérifie si une action est requise après une série de pertes."""
        losses = self.state.consecutive_losses
        
        for streak_count, (action, duration) in self.LOSS_STREAK_ACTIONS.items():
            if losses >= streak_count:
                if action == "PAUSE":
                    self.state.locked_until = datetime.now() + timedelta(minutes=duration)
                    logger.warning(f"⏸️ PAUSE activée: {losses} pertes consécutives. "
                                   f"Trading bloqué jusqu'à {self.state.locked_until.strftime('%H:%M')}")
                elif action == "STOP":
                    self.state.risk_level = "STOPPED"
                    logger.critical(f"🛑 STOP TRADING: {losses} pertes consécutives! "
                                    f"Reset manuel requis.")
    
    def _update_recent_stats(self):
        """Met à jour les statistiques récentes."""
        if not self.trade_history:
            return
        
        # Prendre les N derniers trades
        recent = list(self.trade_history)[-self.kelly_lookback:]
        
        wins = [t for t in recent if t['is_win']]
        losses = [t for t in recent if not t['is_win']]
        
        self.state.recent_win_rate = len(wins) / len(recent) if recent else 0
        self.state.recent_avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
        self.state.recent_avg_loss = np.mean([t['pnl'] for t in losses]) if losses else 0
        self.state.recent_trades_pnl = sum(t['pnl'] for t in recent)
    
    def _calculate_kelly(self):
        """Calcule le Kelly Criterion optimal."""
        if self.state.recent_avg_loss == 0:
            return
        
        W = self.state.recent_win_rate
        R = abs(self.state.recent_avg_win / self.state.recent_avg_loss) if self.state.recent_avg_loss != 0 else 0
        
        # Formule Kelly: f* = W - (1-W)/R
        if R > 0:
            kelly = W - ((1 - W) / R)
        else:
            kelly = 0
        
        # Kelly peut être négatif si pas d'edge
        self.state.kelly_optimal = max(0, kelly) * 100  # En pourcentage
        
        # Appliquer la fraction de Kelly
        self.state.kelly_adjusted = self.state.kelly_optimal * self.kelly_fraction
        
        # Plafonner à 5% maximum
        self.state.kelly_adjusted = min(self.state.kelly_adjusted, 5.0)
        
        logger.debug(f"📊 Kelly: Optimal={self.state.kelly_optimal:.2f}%, "
                    f"Adjusted={self.state.kelly_adjusted:.2f}%")
    
    def _evaluate_risk_level(self):
        """Évalue le niveau de risque actuel."""
        dd = self.state.current_drawdown_pct
        
        # Vérifier si trading est déjà stoppé
        if self.state.risk_level == "STOPPED":
            self.state.risk_multiplier = 0.0
            return
        
        # Vérifier si on est en pause
        if self.state.locked_until and datetime.now() < self.state.locked_until:
            self.state.risk_level = "PAUSED"
            self.state.risk_multiplier = 0.0
            return
        else:
            self.state.locked_until = None
        
        # Déterminer le multiplicateur basé sur le drawdown
        multiplier = 1.0
        for dd_level, mult in sorted(self.DRAWDOWN_LEVELS.items()):
            if dd >= dd_level:
                multiplier = mult
        
        self.state.risk_multiplier = multiplier
        
        # Déterminer le niveau de risque
        if multiplier >= 1.0:
            self.state.risk_level = "NORMAL"
        elif multiplier >= 0.5:
            self.state.risk_level = "REDUCED"
        elif multiplier > 0:
            self.state.risk_level = "MINIMAL"
        else:
            self.state.risk_level = "STOPPED"
            logger.critical(f"🛑 TRADING STOPPÉ: Drawdown {dd:.1f}% >= 20%. Reset manuel requis.")
    
    def get_adjusted_risk(self) -> PositionSizeResult:
        """
        Calcule le risque ajusté en fonction de l'état actuel.
        
        Returns:
            PositionSizeResult avec le risque ajusté
        """
        warnings = []
        
        # Risque de base
        if self.use_kelly and self.state.kelly_adjusted > 0:
            base_risk = self.state.kelly_adjusted
            reason = f"Kelly Criterion ({self.kelly_fraction*100:.0f}%)"
        else:
            base_risk = self.base_risk_percent
            reason = "Fixed Risk"
        
        # Appliquer le multiplicateur de drawdown
        adjusted_risk = base_risk * self.state.risk_multiplier
        
        # Ajouter les avertissements
        if self.state.risk_level == "STOPPED":
            warnings.append("🛑 TRADING STOPPÉ - Reset manuel requis")
            adjusted_risk = 0
        elif self.state.risk_level == "PAUSED":
            warnings.append(f"⏸️ PAUSE jusqu'à {self.state.locked_until.strftime('%H:%M')}")
            adjusted_risk = 0
        elif self.state.risk_level == "MINIMAL":
            warnings.append(f"⚠️ Risque MINIMAL (DD: {self.state.current_drawdown_pct:.1f}%)")
        elif self.state.risk_level == "REDUCED":
            warnings.append(f"⚠️ Risque RÉDUIT (DD: {self.state.current_drawdown_pct:.1f}%)")
        
        # Avertissement si beaucoup de trades aujourd'hui
        if self.state.trades_today >= self.max_daily_trades:
            warnings.append(f"📊 Limite quotidienne atteinte ({self.state.trades_today} trades)")
            adjusted_risk = 0
        
        # Avertissement si série de pertes
        if self.state.consecutive_losses >= 2:
            warnings.append(f"⚠️ {self.state.consecutive_losses} pertes consécutives")
        
        return PositionSizeResult(
            base_risk_percent=base_risk,
            adjusted_risk_percent=adjusted_risk,
            adjustment_factor=self.state.risk_multiplier,
            lot_size=0,  # Sera calculé par le RiskManager
            reason=reason,
            warnings=warnings
        )
    
    def can_trade(self) -> Tuple[bool, str]:
        """
        Vérifie si le trading est autorisé.
        
        Returns:
            (can_trade, reason)
        """
        if self.state.risk_level == "STOPPED":
            return False, "🛑 Trading stoppé (drawdown ou pertes consécutives)"
        
        if self.state.risk_level == "PAUSED":
            remaining = (self.state.locked_until - datetime.now()).total_seconds() / 60
            return False, f"⏸️ En pause ({remaining:.0f} min restantes)"
        
        if self.state.trades_today >= self.max_daily_trades:
            return False, f"📊 Limite quotidienne ({self.max_daily_trades} trades)"
        
        return True, "✅ Trading autorisé"
    
    def reset_stop(self):
        """Reset manuel après un STOP (à appeler manuellement)."""
        logger.info("🔄 Reset manuel du système Anti-Tilt")
        self.state.risk_level = "NORMAL"
        self.state.risk_multiplier = 1.0
        self.state.consecutive_losses = 0
        self.state.locked_until = None
    
    def reset_daily(self):
        """Reset quotidien automatique."""
        logger.info("🔄 Reset quotidien du système Anti-Tilt")
        self.state.trades_today = 0
        self.state.locked_until = None
        
        # Ne pas reset le drawdown ou les pertes consécutives
        # Ce sont des mesures de protection importantes
    
    def _check_daily_reset(self):
        """Vérifie si on doit faire un reset quotidien."""
        now = datetime.now()
        if self.last_daily_reset is None or self.last_daily_reset.date() < now.date():
            self.reset_daily()
            self.last_daily_reset = now
    
    def get_status(self) -> Dict:
        """Retourne le statut complet du système."""
        return {
            'equity': {
                'current': round(self.state.current_equity, 2),
                'peak': round(self.state.peak_equity, 2),
                'drawdown_pct': round(self.state.current_drawdown_pct, 2)
            },
            'risk': {
                'level': self.state.risk_level,
                'multiplier': round(self.state.risk_multiplier, 2),
                'kelly_optimal': round(self.state.kelly_optimal, 2),
                'kelly_adjusted': round(self.state.kelly_adjusted, 2)
            },
            'streaks': {
                'consecutive_wins': self.state.consecutive_wins,
                'consecutive_losses': self.state.consecutive_losses
            },
            'daily': {
                'trades_today': self.state.trades_today,
                'max_trades': self.max_daily_trades
            },
            'recent_performance': {
                'win_rate': round(self.state.recent_win_rate * 100, 1),
                'avg_win': round(self.state.recent_avg_win, 2),
                'avg_loss': round(self.state.recent_avg_loss, 2),
                'total_pnl': round(self.state.recent_trades_pnl, 2)
            }
        }


# ============================================
# SCRIPT DE TEST
# ============================================
if __name__ == "__main__":
    # Test du système Anti-Tilt
    system = AntiTiltSystem({
        'base_risk_percent': 1.0,
        'use_kelly': True,
        'kelly_fraction': 0.25
    })
    
    # Simuler une séquence de trades
    initial_capital = 10000.0
    equity = initial_capital
    
    # Définir le peak initial
    system.update_equity(equity)
    
    print("\n🧪 Test du système Anti-Tilt\n")
    
    # Quelques trades gagnants
    trades = [50, 30, -20, 40, -15, -25, -30, -20, 60, 45]
    
    for i, pnl in enumerate(trades):
        equity += pnl
        is_win = pnl > 0
        
        state = system.update_equity(equity, pnl, is_win)
        risk_result = system.get_adjusted_risk()
        
        print(f"Trade {i+1}: {'WIN' if is_win else 'LOSS'} ${pnl:+.2f}")
        print(f"  Equity: ${equity:.2f} | DD: {state.current_drawdown_pct:.1f}%")
        print(f"  Risk Level: {state.risk_level} | Multiplier: {state.risk_multiplier:.2f}")
        print(f"  Base: {risk_result.base_risk_percent:.2f}% → Adjusted: {risk_result.adjusted_risk_percent:.2f}%")
        if risk_result.warnings:
            print(f"  ⚠️ {', '.join(risk_result.warnings)}")
        print()
    
    print("\n📊 Status Final:")
    import json
    print(json.dumps(system.get_status(), indent=2))
