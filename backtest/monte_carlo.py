"""
Monte Carlo Simulation Module
=============================
Simule des milliers de scénarios possibles pour comprendre la distribution
des résultats et évaluer le risque réel de la stratégie.

Fonctionnalités:
- Shuffling des trades pour voir la variance des chemins d'equity
- Calcul du VaR (Value at Risk) à 95% et 99%
- Distribution des drawdowns possibles
- Probabilité de ruine
- Confidence intervals
"""

import sys
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd
from loguru import logger
import json

# Ajouter le répertoire racine au path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))


@dataclass
class MonteCarloResults:
    """Résultats de la simulation Monte Carlo."""
    n_simulations: int = 0
    n_trades: int = 0
    initial_capital: float = 0.0
    
    # Distribution des équités finales
    final_equities: List[float] = field(default_factory=list)
    median_final_equity: float = 0.0
    mean_final_equity: float = 0.0
    std_final_equity: float = 0.0
    
    # Value at Risk
    var_95: float = 0.0  # Pire cas 5%
    var_99: float = 0.0  # Pire cas 1%
    cvar_95: float = 0.0  # Expected Shortfall 5%
    
    # Best/Worst cases
    best_case_5pct: float = 0.0   # Meilleur 5%
    worst_case_5pct: float = 0.0  # Pire 5%
    absolute_best: float = 0.0
    absolute_worst: float = 0.0
    
    # Drawdown distribution
    max_drawdowns: List[float] = field(default_factory=list)
    median_max_drawdown: float = 0.0
    worst_drawdown_5pct: float = 0.0
    worst_drawdown_1pct: float = 0.0
    
    # Probabilités
    probability_profitable: float = 0.0
    probability_double: float = 0.0  # Prob de doubler le capital
    probability_of_ruin: float = 0.0  # Prob de perdre 50%+
    
    # Streaks
    avg_max_win_streak: float = 0.0
    avg_max_loss_streak: float = 0.0
    worst_loss_streak_95pct: float = 0.0
    
    # Equity paths pour visualisation (échantillon)
    sample_paths: List[List[float]] = field(default_factory=list)
    
    # Confidence Intervals
    ci_95_lower: float = 0.0
    ci_95_upper: float = 0.0
    ci_99_lower: float = 0.0
    ci_99_upper: float = 0.0
    
    # Verdict
    risk_rating: str = ""
    recommendation: str = ""
    
    def to_dict(self) -> Dict:
        return {
            'configuration': {
                'n_simulations': self.n_simulations,
                'n_trades': self.n_trades,
                'initial_capital': self.initial_capital
            },
            'final_equity': {
                'median': round(self.median_final_equity, 2),
                'mean': round(self.mean_final_equity, 2),
                'std': round(self.std_final_equity, 2),
                'best_5pct': round(self.best_case_5pct, 2),
                'worst_5pct': round(self.worst_case_5pct, 2),
                'absolute_best': round(self.absolute_best, 2),
                'absolute_worst': round(self.absolute_worst, 2)
            },
            'value_at_risk': {
                'var_95': round(self.var_95, 2),
                'var_99': round(self.var_99, 2),
                'cvar_95': round(self.cvar_95, 2)
            },
            'drawdown': {
                'median_max_dd': round(self.median_max_drawdown, 1),
                'worst_dd_5pct': round(self.worst_drawdown_5pct, 1),
                'worst_dd_1pct': round(self.worst_drawdown_1pct, 1)
            },
            'probabilities': {
                'profitable': round(self.probability_profitable, 1),
                'double_capital': round(self.probability_double, 1),
                'ruin_50pct': round(self.probability_of_ruin, 1)
            },
            'streaks': {
                'avg_max_win_streak': round(self.avg_max_win_streak, 1),
                'avg_max_loss_streak': round(self.avg_max_loss_streak, 1),
                'worst_loss_streak_95pct': round(self.worst_loss_streak_95pct, 0)
            },
            'confidence_intervals': {
                '95pct': {'lower': round(self.ci_95_lower, 2), 'upper': round(self.ci_95_upper, 2)},
                '99pct': {'lower': round(self.ci_99_lower, 2), 'upper': round(self.ci_99_upper, 2)}
            },
            'risk_rating': self.risk_rating,
            'recommendation': self.recommendation
        }
    
    def print_report(self):
        """Affiche un rapport formaté."""
        print("\n" + "=" * 70)
        print("🎲 MONTE CARLO SIMULATION REPORT")
        print("=" * 70)
        
        print(f"\n📊 Configuration:")
        print(f"  Simulations: {self.n_simulations:,}")
        print(f"  Trades par simulation: {self.n_trades}")
        print(f"  Capital initial: ${self.initial_capital:,.2f}")
        
        print(f"\n💰 Distribution des Équités Finales:")
        print(f"  Médiane: ${self.median_final_equity:,.2f}")
        print(f"  Moyenne: ${self.mean_final_equity:,.2f} (±${self.std_final_equity:,.2f})")
        print(f"  Meilleur 5%: ${self.best_case_5pct:,.2f}")
        print(f"  Pire 5%: ${self.worst_case_5pct:,.2f}")
        
        print(f"\n📉 Value at Risk (VaR):")
        print(f"  VaR 95%: ${self.var_95:,.2f} (dans 95% des cas, perte max)")
        print(f"  VaR 99%: ${self.var_99:,.2f} (dans 99% des cas, perte max)")
        print(f"  CVaR 95%: ${self.cvar_95:,.2f} (perte moyenne dans le pire 5%)")
        
        print(f"\n📈 Distribution des Drawdowns:")
        print(f"  Médiane Max DD: {self.median_max_drawdown:.1f}%")
        print(f"  Pire DD (5%): {self.worst_drawdown_5pct:.1f}%")
        print(f"  Pire DD (1%): {self.worst_drawdown_1pct:.1f}%")
        
        print(f"\n🎯 Probabilités:")
        print(f"  Profitable: {self.probability_profitable:.1f}%")
        print(f"  Doubler le capital: {self.probability_double:.1f}%")
        print(f"  Ruine (perdre 50%+): {self.probability_of_ruin:.1f}%")
        
        print(f"\n📊 Confidence Intervals:")
        print(f"  95% CI: [${self.ci_95_lower:,.2f} - ${self.ci_95_upper:,.2f}]")
        print(f"  99% CI: [${self.ci_99_lower:,.2f} - ${self.ci_99_upper:,.2f}]")
        
        print(f"\n🔥 Séries de Trades:")
        print(f"  Avg Max Win Streak: {self.avg_max_win_streak:.1f}")
        print(f"  Avg Max Loss Streak: {self.avg_max_loss_streak:.1f}")
        print(f"  Worst Loss Streak (95%): {self.worst_loss_streak_95pct:.0f}")
        
        print("\n" + "=" * 70)
        print(f"📋 RISK RATING: {self.risk_rating}")
        print(f"📋 RECOMMENDATION:")
        print(self.recommendation)
        print("=" * 70 + "\n")


class MonteCarloSimulator:
    """
    Simulateur Monte Carlo pour l'analyse de risque de trading.
    
    Prend une liste de trades historiques et simule des milliers de
    chemins d'equity possibles en mélangeant l'ordre des trades.
    """
    
    def __init__(self, initial_capital: float = 10000.0, n_simulations: int = 10000):
        """
        Args:
            initial_capital: Capital initial pour chaque simulation
            n_simulations: Nombre de simulations à exécuter
        """
        self.initial_capital = initial_capital
        self.n_simulations = n_simulations
        self.results = MonteCarloResults()
        self.trade_pnls: List[float] = []
    
    def run(self, trade_pnls: List[float], progress_callback=None) -> MonteCarloResults:
        """
        Exécute la simulation Monte Carlo.
        
        Args:
            trade_pnls: Liste des PnL de chaque trade (en $)
            progress_callback: Callback pour afficher la progression
        
        Returns:
            MonteCarloResults avec toutes les statistiques
        """
        self.trade_pnls = trade_pnls
        n_trades = len(trade_pnls)
        
        if n_trades < 5:
            logger.error("❌ Pas assez de trades pour Monte Carlo (minimum 5)")
            return self.results
        
        logger.info("=" * 60)
        logger.info("🎲 DÉMARRAGE SIMULATION MONTE CARLO")
        logger.info("=" * 60)
        logger.info(f"📊 Simulations: {self.n_simulations:,}")
        logger.info(f"📊 Trades: {n_trades}")
        logger.info(f"💰 Capital initial: ${self.initial_capital:,.2f}")
        
        # Initialiser les résultats
        self.results.n_simulations = self.n_simulations
        self.results.n_trades = n_trades
        self.results.initial_capital = self.initial_capital
        
        # Arrays pour stocker les résultats
        final_equities = []
        max_drawdowns = []
        max_win_streaks = []
        max_loss_streaks = []
        sample_paths = []
        
        # Convertir en numpy pour la vitesse
        pnls = np.array(trade_pnls)
        
        # Exécuter les simulations
        for i in range(self.n_simulations):
            if progress_callback and i % 1000 == 0:
                progress_callback((i / self.n_simulations) * 100, f"Sim {i:,}/{self.n_simulations:,}")
            
            # Mélanger les trades aléatoirement
            shuffled_pnls = np.random.permutation(pnls)
            
            # Calculer l'equity curve
            equity_curve = [self.initial_capital]
            peak = self.initial_capital
            max_dd = 0
            
            current_equity = self.initial_capital
            for pnl in shuffled_pnls:
                current_equity += pnl
                equity_curve.append(current_equity)
                
                if current_equity > peak:
                    peak = current_equity
                
                dd = (peak - current_equity) / peak * 100 if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd
            
            final_equities.append(current_equity)
            max_drawdowns.append(max_dd)
            
            # Calculer les streaks
            win_streak, loss_streak = self._calculate_streaks(shuffled_pnls)
            max_win_streaks.append(win_streak)
            max_loss_streaks.append(loss_streak)
            
            # Garder quelques paths pour visualisation
            if i < 100:
                sample_paths.append(equity_curve)
        
        # Convertir en numpy pour les calculs
        final_equities = np.array(final_equities)
        max_drawdowns = np.array(max_drawdowns)
        
        # Calculer toutes les statistiques
        self._calculate_equity_stats(final_equities)
        self._calculate_var(final_equities)
        self._calculate_drawdown_stats(max_drawdowns)
        self._calculate_probabilities(final_equities)
        self._calculate_streak_stats(np.array(max_win_streaks), np.array(max_loss_streaks))
        self._calculate_confidence_intervals(final_equities)
        
        # Sauvegarder les paths d'exemple
        self.results.sample_paths = sample_paths[:20]
        
        # Évaluer le risque
        self._evaluate_risk()
        
        logger.info("✅ Simulation terminée!")
        return self.results
    
    def _calculate_streaks(self, pnls: np.ndarray) -> Tuple[int, int]:
        """Calcule les plus longues séries de gains et pertes."""
        max_win = 0
        max_loss = 0
        current_win = 0
        current_loss = 0
        
        for pnl in pnls:
            if pnl > 0:
                current_win += 1
                current_loss = 0
                max_win = max(max_win, current_win)
            elif pnl < 0:
                current_loss += 1
                current_win = 0
                max_loss = max(max_loss, current_loss)
            else:
                current_win = 0
                current_loss = 0
        
        return max_win, max_loss
    
    def _calculate_equity_stats(self, final_equities: np.ndarray):
        """Calcule les statistiques sur les équités finales."""
        self.results.final_equities = final_equities.tolist()
        self.results.median_final_equity = np.median(final_equities)
        self.results.mean_final_equity = np.mean(final_equities)
        self.results.std_final_equity = np.std(final_equities)
        self.results.best_case_5pct = np.percentile(final_equities, 95)
        self.results.worst_case_5pct = np.percentile(final_equities, 5)
        self.results.absolute_best = np.max(final_equities)
        self.results.absolute_worst = np.min(final_equities)
    
    def _calculate_var(self, final_equities: np.ndarray):
        """Calcule Value at Risk et Expected Shortfall."""
        # VaR = perte max dans X% des cas
        # VaR 95% = on est sûr à 95% de ne pas perdre plus que cette somme
        losses = self.initial_capital - final_equities
        
        self.results.var_95 = np.percentile(losses, 95)
        self.results.var_99 = np.percentile(losses, 99)
        
        # CVaR (Conditional VaR) = perte moyenne dans le pire 5%
        worst_5pct = np.percentile(final_equities, 5)
        worst_cases = final_equities[final_equities <= worst_5pct]
        self.results.cvar_95 = self.initial_capital - np.mean(worst_cases) if len(worst_cases) > 0 else 0
    
    def _calculate_drawdown_stats(self, max_drawdowns: np.ndarray):
        """Calcule les statistiques de drawdown."""
        self.results.max_drawdowns = max_drawdowns.tolist()
        self.results.median_max_drawdown = np.median(max_drawdowns)
        self.results.worst_drawdown_5pct = np.percentile(max_drawdowns, 95)
        self.results.worst_drawdown_1pct = np.percentile(max_drawdowns, 99)
    
    def _calculate_probabilities(self, final_equities: np.ndarray):
        """Calcule les probabilités importantes."""
        n = len(final_equities)
        
        # Probabilité d'être profitable
        self.results.probability_profitable = (final_equities > self.initial_capital).sum() / n * 100
        
        # Probabilité de doubler
        self.results.probability_double = (final_equities >= self.initial_capital * 2).sum() / n * 100
        
        # Probabilité de ruine (perdre 50%+)
        self.results.probability_of_ruin = (final_equities <= self.initial_capital * 0.5).sum() / n * 100
    
    def _calculate_streak_stats(self, win_streaks: np.ndarray, loss_streaks: np.ndarray):
        """Calcule les statistiques de séries."""
        self.results.avg_max_win_streak = np.mean(win_streaks)
        self.results.avg_max_loss_streak = np.mean(loss_streaks)
        self.results.worst_loss_streak_95pct = np.percentile(loss_streaks, 95)
    
    def _calculate_confidence_intervals(self, final_equities: np.ndarray):
        """Calcule les intervalles de confiance."""
        self.results.ci_95_lower = np.percentile(final_equities, 2.5)
        self.results.ci_95_upper = np.percentile(final_equities, 97.5)
        self.results.ci_99_lower = np.percentile(final_equities, 0.5)
        self.results.ci_99_upper = np.percentile(final_equities, 99.5)
    
    def _evaluate_risk(self):
        """Évalue le niveau de risque global."""
        risk_score = 0
        concerns = []
        
        # 1. Probabilité de profit
        if self.results.probability_profitable >= 80:
            risk_score += 3
        elif self.results.probability_profitable >= 60:
            risk_score += 2
        elif self.results.probability_profitable >= 50:
            risk_score += 1
        else:
            concerns.append("Probabilité de profit < 50%")
        
        # 2. Risque de ruine
        if self.results.probability_of_ruin < 1:
            risk_score += 3
        elif self.results.probability_of_ruin < 5:
            risk_score += 2
        elif self.results.probability_of_ruin < 10:
            risk_score += 1
        else:
            concerns.append(f"Risque de ruine élevé ({self.results.probability_of_ruin:.1f}%)")
        
        # 3. Drawdown médian
        if self.results.median_max_drawdown < 10:
            risk_score += 3
        elif self.results.median_max_drawdown < 20:
            risk_score += 2
        elif self.results.median_max_drawdown < 30:
            risk_score += 1
        else:
            concerns.append(f"Drawdown médian élevé ({self.results.median_max_drawdown:.1f}%)")
        
        # 4. Loss streak
        if self.results.worst_loss_streak_95pct <= 5:
            risk_score += 2
        elif self.results.worst_loss_streak_95pct <= 8:
            risk_score += 1
        else:
            concerns.append(f"Longues séries de pertes possibles ({self.results.worst_loss_streak_95pct:.0f})")
        
        # Rating basé sur le score
        if risk_score >= 9:
            self.results.risk_rating = "🟢 FAIBLE RISQUE"
            self.results.recommendation = "✅ Stratégie stable. Déploiement recommandé avec sizing normal."
        elif risk_score >= 6:
            self.results.risk_rating = "🟡 RISQUE MODÉRÉ"
            self.results.recommendation = "⚠️ Stratégie acceptable. Déployer avec sizing réduit (50%)."
        elif risk_score >= 3:
            self.results.risk_rating = "🟠 RISQUE ÉLEVÉ"
            self.results.recommendation = "⚠️ Stratégie risquée. Micro-lot uniquement ou revoir les paramètres."
        else:
            self.results.risk_rating = "🔴 RISQUE TRÈS ÉLEVÉ"
            self.results.recommendation = "❌ NE PAS DÉPLOYER. Stratégie trop risquée."
        
        if concerns:
            self.results.recommendation += "\n\n⚠️ Points d'attention:\n" + "\n".join(f"  • {c}" for c in concerns)
    
    def save_results(self, output_dir: Path = None) -> Path:
        """Sauvegarde les résultats en JSON."""
        if output_dir is None:
            output_dir = ROOT_DIR / "backtest" / "results"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"monte_carlo_{timestamp}.json"
        
        # Ne pas sauvegarder toutes les équités (trop lourd)
        results_dict = self.results.to_dict()
        results_dict['sample_equity_paths'] = self.results.sample_paths[:10]
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results_dict, f, indent=2, ensure_ascii=False, default=str)
        
        logger.info(f"📁 Résultats sauvegardés: {output_file}")
        return output_file


# ============================================
# FONCTION UTILITAIRE
# ============================================
def run_monte_carlo_from_backtest(closed_trades: List, initial_capital: float = 10000.0,
                                    n_simulations: int = 10000) -> MonteCarloResults:
    """
    Fonction utilitaire pour lancer Monte Carlo depuis des trades de backtest.
    
    Args:
        closed_trades: Liste de BacktestTrade du backtester
        initial_capital: Capital initial
        n_simulations: Nombre de simulations
    
    Returns:
        MonteCarloResults
    """
    # Extraire les PnL des trades
    trade_pnls = [t.pnl for t in closed_trades if hasattr(t, 'pnl')]
    
    if not trade_pnls:
        logger.error("❌ Pas de trades avec PnL trouvés")
        return MonteCarloResults()
    
    # Lancer la simulation
    simulator = MonteCarloSimulator(initial_capital, n_simulations)
    return simulator.run(trade_pnls)


# ============================================
# SCRIPT DE TEST
# ============================================
if __name__ == "__main__":
    # Simuler des trades pour le test
    np.random.seed(42)
    
    # Distribution réaliste: 45% WR, ratio 1:2
    wins = [20, 25, 30, 40, 50, 35, 28, 45, 22, 38]  # Gains en $
    losses = [-15, -12, -10, -18, -14, -11, -16, -13, -17, -12]  # Pertes en $
    
    # Mélanger
    all_trades = wins + losses
    np.random.shuffle(all_trades)
    
    # Lancer la simulation
    simulator = MonteCarloSimulator(initial_capital=10000, n_simulations=10000)
    results = simulator.run(all_trades)
    
    # Afficher le rapport
    results.print_report()
    
    # Sauvegarder
    simulator.save_results()
