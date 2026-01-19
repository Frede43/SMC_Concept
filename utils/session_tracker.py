"""
📊 SESSION PERFORMANCE TRACKER
Version 1.0 - Statistiques détaillées par session de trading

Analyse les performances par:
- Session (Asian, London, NY)
- Jour de la semaine
- Heure de la journée
- Stratégie utilisée
- Symbole

Permet d'identifier:
- Meilleures sessions pour chaque stratégie
- Heures à éviter
- Patterns de performance
"""

import os
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from loguru import logger

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logger.warning("⚠️ pandas non disponible. Fonctionnalités réduites.")


@dataclass
class SessionStats:
    """Statistiques pour une session de trading."""
    session_name: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit: float = 0.0
    total_loss: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    avg_duration_minutes: float = 0.0
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100
    
    @property
    def profit_factor(self) -> float:
        if self.total_loss == 0:
            return float('inf') if self.total_profit > 0 else 0.0
        return abs(self.total_profit / self.total_loss)
    
    @property
    def net_profit(self) -> float:
        return self.total_profit + self.total_loss  # loss is negative
    
    @property
    def expectancy(self) -> float:
        """Expectancy = (WR * AvgWin) - (LR * AvgLoss)"""
        if self.total_trades == 0:
            return 0.0
        wr = self.winning_trades / self.total_trades
        lr = self.losing_trades / self.total_trades
        return (wr * self.avg_win) - (lr * abs(self.avg_loss))
    
    def to_dict(self) -> Dict:
        return {
            'session': self.session_name,
            'trades': self.total_trades,
            'wins': self.winning_trades,
            'losses': self.losing_trades,
            'win_rate': round(self.win_rate, 1),
            'profit_factor': round(self.profit_factor, 2),
            'net_profit': round(self.net_profit, 2),
            'expectancy': round(self.expectancy, 2),
            'avg_win': round(self.avg_win, 2),
            'avg_loss': round(self.avg_loss, 2),
            'best_trade': round(self.best_trade, 2),
            'worst_trade': round(self.worst_trade, 2),
            'avg_duration': round(self.avg_duration_minutes, 1)
        }


@dataclass
class StrategyStats:
    """Statistiques pour une stratégie spécifique."""
    strategy_name: str
    sessions: Dict[str, SessionStats] = field(default_factory=dict)
    total_trades: int = 0
    winning_trades: int = 0
    net_profit: float = 0.0
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100
    
    def get_best_session(self) -> Optional[str]:
        """Retourne la meilleure session pour cette stratégie."""
        if not self.sessions:
            return None
        best = max(self.sessions.values(), key=lambda s: s.win_rate if s.total_trades >= 3 else 0)
        return best.session_name if best.total_trades >= 3 else None


class SessionPerformanceTracker:
    """
    Tracker de performance par session de trading.
    
    Collecte et analyse les performances pour identifier:
    - Les meilleures sessions par stratégie
    - Les patterns horaires
    - Les jours les plus profitables
    """
    
    SESSIONS = {
        'asian': {'start': 0, 'end': 8},        # 00:00 - 08:00 GMT
        'london_open': {'start': 8, 'end': 10}, # 08:00 - 10:00 GMT
        'london': {'start': 10, 'end': 12},     # 10:00 - 12:00 GMT
        'ny_open': {'start': 13, 'end': 15},    # 13:00 - 15:00 GMT
        'ny': {'start': 15, 'end': 17},         # 15:00 - 17:00 GMT
        'off_hours': {'start': 17, 'end': 24}   # 17:00 - 00:00 GMT
    }
    
    def __init__(self, data_file: str = "logs/session_performance.json", 
                 timezone_offset: int = 2):
        """
        Args:
            data_file: Fichier de sauvegarde des données
            timezone_offset: Décalage par rapport à GMT
        """
        self.data_file = Path(data_file)
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.timezone_offset = timezone_offset
        
        # Structures de données
        self.trades: List[Dict] = []
        self.session_stats: Dict[str, SessionStats] = {}
        self.strategy_stats: Dict[str, StrategyStats] = {}
        self.symbol_stats: Dict[str, Dict[str, SessionStats]] = {}
        self.hourly_stats: Dict[int, SessionStats] = {}
        self.daily_stats: Dict[str, SessionStats] = {}  # Mon, Tue, etc.
        
        # Charger les données existantes
        self._load_data()
        
        logger.info(f"📊 SessionPerformanceTracker initialisé avec {len(self.trades)} trades historiques")
    
    def _get_session_name(self, hour_gmt: int) -> str:
        """Détermine la session basée sur l'heure GMT."""
        for session_name, times in self.SESSIONS.items():
            if times['start'] <= hour_gmt < times['end']:
                return session_name
        return 'off_hours'
    
    def _local_to_gmt(self, local_hour: int) -> int:
        """Convertit heure locale en GMT."""
        return (local_hour - self.timezone_offset) % 24
    
    def record_trade(self, trade_data: Dict[str, Any]):
        """
        Enregistre un trade fermé pour l'analyse.
        
        Args:
            trade_data: Dictionnaire avec les infos du trade:
                - ticket: ID du trade
                - symbol: Symbole tradé
                - direction: BUY/SELL
                - entry_time: datetime d'entrée
                - exit_time: datetime de sortie
                - profit: Profit/perte en USD
                - strategy: Stratégie utilisée (pdl_sweep, asian_sweep, silver_bullet, etc.)
                - session: Session (optionnel, calculé si non fourni)
                - confluences: Liste des confluences
        """
        try:
            # Normaliser les données
            entry_time = trade_data.get('entry_time')
            if isinstance(entry_time, str):
                entry_time = datetime.strptime(entry_time, "%Y-%m-%d %H:%M:%S")
            elif entry_time is None:
                entry_time = datetime.now()
            
            exit_time = trade_data.get('exit_time')
            if isinstance(exit_time, str):
                exit_time = datetime.strptime(exit_time, "%Y-%m-%d %H:%M:%S")
            elif exit_time is None:
                exit_time = datetime.now()
            
            # Déterminer la session
            hour_local = entry_time.hour
            hour_gmt = self._local_to_gmt(hour_local)
            session = trade_data.get('session') or self._get_session_name(hour_gmt)
            
            # Calculer la durée
            duration = (exit_time - entry_time).total_seconds() / 60
            
            # Déterminer la stratégie principale
            strategy = trade_data.get('strategy', 'unknown')
            if strategy == 'unknown' and trade_data.get('confluences'):
                confluences = trade_data.get('confluences', [])
                if isinstance(confluences, str):
                    confluences = confluences.split('|')
                # Prioriser: Silver Bullet > PDL Sweep > Asian Sweep > SMT
                if 'Silver_Bullet' in confluences or 'SB' in confluences:
                    strategy = 'silver_bullet'
                elif 'PDL_Sweep' in confluences or 'PDL' in confluences:
                    strategy = 'pdl_sweep'
                elif 'Asian_Sweep' in confluences or 'Asian' in confluences:
                    strategy = 'asian_sweep'
                elif any('SMT' in c for c in confluences):
                    strategy = 'smt'
                else:
                    strategy = 'other'
            
            # Créer l'entrée
            trade_entry = {
                'ticket': trade_data.get('ticket', 0),
                'symbol': trade_data.get('symbol', 'UNKNOWN'),
                'direction': trade_data.get('direction', 'UNKNOWN'),
                'entry_time': entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                'exit_time': exit_time.strftime("%Y-%m-%d %H:%M:%S"),
                'hour_gmt': hour_gmt,
                'day_of_week': entry_time.strftime("%A"),
                'session': session,
                'strategy': strategy,
                'profit': float(trade_data.get('profit', 0.0)),
                'duration_minutes': float(duration),
                'is_win': bool(trade_data.get('profit', 0) > 0)
            }
            
            self.trades.append(trade_entry)
            self._update_stats(trade_entry)
            self._save_data()
            
            logger.debug(f"📊 Trade enregistré: {trade_entry['symbol']} {session} | ${trade_entry['profit']:.2f}")
            
        except Exception as e:
            logger.error(f"❌ Erreur enregistrement trade: {e}")
    
    def _update_stats(self, trade: Dict):
        """Met à jour toutes les statistiques avec un nouveau trade."""
        session = trade['session']
        strategy = trade['strategy']
        symbol = trade['symbol']
        hour = trade['hour_gmt']
        day = trade['day_of_week']
        profit = trade['profit']
        duration = trade['duration_minutes']
        is_win = trade['is_win']
        
        # 1. Stats par session
        if session not in self.session_stats:
            self.session_stats[session] = SessionStats(session_name=session)
        self._update_single_stat(self.session_stats[session], profit, duration, is_win)
        
        # 2. Stats par stratégie
        if strategy not in self.strategy_stats:
            self.strategy_stats[strategy] = StrategyStats(strategy_name=strategy)
        strat = self.strategy_stats[strategy]
        strat.total_trades += 1
        if is_win:
            strat.winning_trades += 1
        strat.net_profit += profit
        
        # Stats par session pour cette stratégie
        if session not in strat.sessions:
            strat.sessions[session] = SessionStats(session_name=session)
        self._update_single_stat(strat.sessions[session], profit, duration, is_win)
        
        # 3. Stats par symbole
        if symbol not in self.symbol_stats:
            self.symbol_stats[symbol] = {}
        if session not in self.symbol_stats[symbol]:
            self.symbol_stats[symbol][session] = SessionStats(session_name=session)
        self._update_single_stat(self.symbol_stats[symbol][session], profit, duration, is_win)
        
        # 4. Stats horaires
        if hour not in self.hourly_stats:
            self.hourly_stats[hour] = SessionStats(session_name=f"Hour_{hour}")
        self._update_single_stat(self.hourly_stats[hour], profit, duration, is_win)
        
        # 5. Stats par jour
        if day not in self.daily_stats:
            self.daily_stats[day] = SessionStats(session_name=day)
        self._update_single_stat(self.daily_stats[day], profit, duration, is_win)
    
    def _update_single_stat(self, stat: SessionStats, profit: float, duration: float, is_win: bool):
        """Met à jour un objet SessionStats avec un trade."""
        stat.total_trades += 1
        
        if is_win:
            stat.winning_trades += 1
            stat.total_profit += profit
            if profit > stat.best_trade:
                stat.best_trade = profit
        else:
            stat.losing_trades += 1
            stat.total_loss += profit  # profit est négatif
            if profit < stat.worst_trade:
                stat.worst_trade = profit
        
        # Moyennes
        if stat.winning_trades > 0:
            stat.avg_win = stat.total_profit / stat.winning_trades
        if stat.losing_trades > 0:
            stat.avg_loss = stat.total_loss / stat.losing_trades
        
        # Durée moyenne (moyenne mobile)
        n = stat.total_trades
        stat.avg_duration_minutes = ((stat.avg_duration_minutes * (n - 1)) + duration) / n
    
    def _load_data(self):
        """Charge les données depuis le fichier."""
        if not self.data_file.exists():
            return
        
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.trades = data.get('trades', [])
                
            # Recalculer les stats
            for trade in self.trades:
                self._update_stats(trade)
                
            logger.info(f"📊 Chargé {len(self.trades)} trades depuis {self.data_file}")
        except Exception as e:
            logger.error(f"❌ Erreur chargement données: {e}")
    
    def _save_data(self):
        """Sauvegarde les données dans le fichier."""
        try:
            # Fonction pour convertir les types non-JSON (numpy.bool_, etc)
            def json_serializable(obj):
                if isinstance(obj, (dict, list)):
                    return obj
                if hasattr(obj, 'item'): # Gère numpy.bool_, numpy.int64, etc.
                    return obj.item()
                return str(obj)

            data = {
                'trades': self.trades,
                'last_updated': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=json_serializable)
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde données: {e}")
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Retourne un résumé des performances par session."""
        summary = {}
        for name, stats in self.session_stats.items():
            if stats.total_trades > 0:
                summary[name] = stats.to_dict()
        return summary
    
    def get_best_sessions(self, min_trades: int = 5) -> List[Tuple[str, float]]:
        """
        Retourne les sessions classées par win rate.
        
        Args:
            min_trades: Nombre minimum de trades pour être inclus
        """
        sessions = [
            (name, stats.win_rate, stats.total_trades)
            for name, stats in self.session_stats.items()
            if stats.total_trades >= min_trades
        ]
        return sorted(sessions, key=lambda x: x[1], reverse=True)
    
    def get_strategy_session_matrix(self) -> Dict[str, Dict[str, Dict]]:
        """
        Retourne une matrice stratégie x session avec les performances.
        
        Utile pour identifier quelle stratégie fonctionne le mieux à quelle session.
        """
        matrix = {}
        for strategy_name, strategy in self.strategy_stats.items():
            matrix[strategy_name] = {
                'total': {
                    'trades': strategy.total_trades,
                    'win_rate': round(strategy.win_rate, 1),
                    'net_profit': round(strategy.net_profit, 2)
                },
                'best_session': strategy.get_best_session(),
                'sessions': {}
            }
            for session_name, session_stats in strategy.sessions.items():
                if session_stats.total_trades > 0:
                    matrix[strategy_name]['sessions'][session_name] = session_stats.to_dict()
        return matrix
    
    def get_hourly_heatmap(self) -> Dict[int, Dict]:
        """Retourne les performances par heure pour créer un heatmap."""
        heatmap = {}
        for hour in range(24):
            if hour in self.hourly_stats:
                stats = self.hourly_stats[hour]
                heatmap[hour] = {
                    'trades': stats.total_trades,
                    'win_rate': round(stats.win_rate, 1),
                    'net_profit': round(stats.net_profit, 2),
                    'expectancy': round(stats.expectancy, 2)
                }
            else:
                heatmap[hour] = {'trades': 0, 'win_rate': 0, 'net_profit': 0, 'expectancy': 0}
        return heatmap
    
    def get_recommendations(self, min_trades: int = 10) -> List[str]:
        """
        Génère des recommandations basées sur l'analyse des données.
        
        Returns:
            Liste de recommandations textuelles
        """
        recommendations = []
        
        # 1. Meilleures et pires sessions
        if self.session_stats:
            valid_sessions = [(n, s) for n, s in self.session_stats.items() if s.total_trades >= min_trades]
            if valid_sessions:
                best_session = max(valid_sessions, key=lambda x: x[1].win_rate)
                worst_session = min(valid_sessions, key=lambda x: x[1].win_rate)
                
                if best_session[1].win_rate > 55:
                    recommendations.append(
                        f"✅ Focus sur {best_session[0].upper()}: WR {best_session[1].win_rate:.1f}% "
                        f"sur {best_session[1].total_trades} trades"
                    )
                
                if worst_session[1].win_rate < 45:
                    recommendations.append(
                        f"⚠️ Éviter {worst_session[0].upper()}: WR {worst_session[1].win_rate:.1f}% "
                        f"sur {worst_session[1].total_trades} trades"
                    )
        
        # 2. Meilleures stratégies par session
        for strategy_name, strategy in self.strategy_stats.items():
            if strategy.total_trades >= min_trades:
                best_session = strategy.get_best_session()
                if best_session:
                    session_stats = strategy.sessions.get(best_session)
                    if session_stats and session_stats.win_rate > 60:
                        recommendations.append(
                            f"💡 {strategy_name.upper()} performe mieux pendant {best_session.upper()}: "
                            f"WR {session_stats.win_rate:.1f}%"
                        )
        
        # 3. Heures à éviter
        bad_hours = [
            h for h, stats in self.hourly_stats.items()
            if stats.total_trades >= 5 and stats.win_rate < 40
        ]
        if bad_hours:
            hours_str = ", ".join([f"{h}:00 GMT" for h in sorted(bad_hours)])
            recommendations.append(f"🚫 Heures à éviter: {hours_str}")
        
        # 4. Jours à éviter
        for day, stats in self.daily_stats.items():
            if stats.total_trades >= min_trades and stats.win_rate < 40:
                recommendations.append(
                    f"⚠️ {day} sous-performe: WR {stats.win_rate:.1f}% sur {stats.total_trades} trades"
                )
        
        return recommendations if recommendations else ["📊 Pas assez de données pour des recommandations"]
    
    def print_report(self):
        """Affiche un rapport complet des performances."""
        print("\n" + "=" * 70)
        print("📊 SESSION PERFORMANCE REPORT")
        print(f"📅 Généré le: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📈 Total trades analysés: {len(self.trades)}")
        print("=" * 70)
        
        # Sessions
        print("\n🕐 PERFORMANCE PAR SESSION:")
        print("-" * 60)
        print(f"{'Session':<15} {'Trades':>8} {'Win%':>8} {'PF':>8} {'Net $':>10} {'E[x]':>8}")
        print("-" * 60)
        
        for name in ['asian', 'london_open', 'london', 'ny_open', 'ny', 'off_hours']:
            if name in self.session_stats:
                s = self.session_stats[name]
                pf = f"{s.profit_factor:.2f}" if s.profit_factor != float('inf') else "∞"
                print(f"{name:<15} {s.total_trades:>8} {s.win_rate:>7.1f}% {pf:>8} {s.net_profit:>10.2f} {s.expectancy:>8.2f}")
        
        # Stratégies
        print("\n📈 PERFORMANCE PAR STRATÉGIE:")
        print("-" * 60)
        print(f"{'Stratégie':<20} {'Trades':>8} {'Win%':>8} {'Net $':>10} {'Best Session':<15}")
        print("-" * 60)
        
        for name, strat in sorted(self.strategy_stats.items(), key=lambda x: -x[1].total_trades):
            if strat.total_trades > 0:
                best = strat.get_best_session() or "N/A"
                print(f"{name:<20} {strat.total_trades:>8} {strat.win_rate:>7.1f}% {strat.net_profit:>10.2f} {best:<15}")
        
        # Recommandations
        print("\n💡 RECOMMANDATIONS:")
        print("-" * 60)
        for rec in self.get_recommendations():
            print(f"  {rec}")
        
        print("\n" + "=" * 70)
    
    def export_to_csv(self, filepath: str = "logs/session_analysis.csv"):
        """Exporte les données en CSV pour analyse externe."""
        try:
            if not PANDAS_AVAILABLE:
                logger.warning("pandas requis pour export CSV")
                return
            
            df = pd.DataFrame(self.trades)
            df.to_csv(filepath, index=False)
            logger.info(f"📊 Données exportées vers {filepath}")
        except Exception as e:
            logger.error(f"❌ Erreur export CSV: {e}")


# Singleton pour accès global
_tracker_instance: Optional[SessionPerformanceTracker] = None

def get_session_tracker(timezone_offset: int = 2) -> SessionPerformanceTracker:
    """Retourne l'instance singleton du tracker."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = SessionPerformanceTracker(timezone_offset=timezone_offset)
    return _tracker_instance


# Test
if __name__ == "__main__":
    tracker = SessionPerformanceTracker()
    
    # Simuler quelques trades
    test_trades = [
        {'symbol': 'GBPUSDm', 'direction': 'BUY', 'profit': 25.50, 'strategy': 'silver_bullet',
         'entry_time': datetime(2024, 1, 15, 15, 30), 'exit_time': datetime(2024, 1, 15, 16, 45)},
        {'symbol': 'GBPUSDm', 'direction': 'SELL', 'profit': -12.00, 'strategy': 'pdl_sweep',
         'entry_time': datetime(2024, 1, 15, 10, 15), 'exit_time': datetime(2024, 1, 15, 11, 30)},
        {'symbol': 'EURUSDm', 'direction': 'BUY', 'profit': 18.75, 'strategy': 'asian_sweep',
         'entry_time': datetime(2024, 1, 16, 9, 0), 'exit_time': datetime(2024, 1, 16, 10, 20)},
    ]
    
    for trade in test_trades:
        tracker.record_trade(trade)
    
    tracker.print_report()
