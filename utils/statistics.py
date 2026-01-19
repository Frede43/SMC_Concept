"""
Statistical Validation Module
=============================
Outils de validation statistique pour s'assurer que les résultats
de backtest sont significatifs et non dus au hasard.

Fonctionnalités:
- Test du nombre minimum de trades
- Test binomial pour le win rate
- T-test pour les returns
- Analyse de significativité
- Recommendation de continuation/arrêt
"""

import sys
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from loguru import logger

try:
    from scipy import stats as scipy_stats
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    logger.warning("⚠️ scipy non disponible. Tests statistiques limités.")

# Ajouter le répertoire racine au path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))


@dataclass
class SignificanceTest:
    """Résultat d'un test de significativité."""
    test_name: str
    passed: bool
    p_value: float = 1.0
    confidence_level: float = 0.0
    observed_value: float = 0.0
    expected_value: float = 0.0
    interpretation: str = ""
    
    def to_dict(self) -> Dict:
        return {
            'test': self.test_name,
            'passed': self.passed,
            'p_value': round(self.p_value, 4),
            'confidence': round(self.confidence_level, 1),
            'observed': round(self.observed_value, 4),
            'expected': round(self.expected_value, 4),
            'interpretation': self.interpretation
        }


@dataclass
class StatisticalValidation:
    """Résultats complets de la validation statistique."""
    # Métriques de base
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_return: float = 0.0
    std_return: float = 0.0
    
    # Tests individuels
    tests: List[SignificanceTest] = field(default_factory=list)
    
    # Résumé
    tests_passed: int = 0
    tests_total: int = 0
    overall_confidence: float = 0.0
    
    # Verdict
    is_significant: bool = False
    recommendation: str = ""
    minimum_trades_needed: int = 0
    
    def add_test(self, test: SignificanceTest):
        """Ajoute un test et met à jour les compteurs."""
        self.tests.append(test)
        self.tests_total += 1
        if test.passed:
            self.tests_passed += 1
    
    def calculate_overall(self):
        """Calcule le score global."""
        if self.tests_total > 0:
            self.overall_confidence = (self.tests_passed / self.tests_total) * 100
        
        # Significatif si 75%+ des tests passent
        self.is_significant = self.overall_confidence >= 75
    
    def to_dict(self) -> Dict:
        return {
            'metrics': {
                'total_trades': self.total_trades,
                'win_rate': round(self.win_rate * 100, 1),
                'profit_factor': round(self.profit_factor, 2),
                'avg_return': round(self.avg_return, 4),
                'std_return': round(self.std_return, 4)
            },
            'tests': [t.to_dict() for t in self.tests],
            'summary': {
                'tests_passed': self.tests_passed,
                'tests_total': self.tests_total,
                'overall_confidence': round(self.overall_confidence, 1),
                'is_significant': self.is_significant,
                'minimum_trades_needed': self.minimum_trades_needed
            },
            'recommendation': self.recommendation
        }
    
    def print_report(self):
        """Affiche un rapport formaté."""
        print("\n" + "=" * 70)
        print("📊 STATISTICAL VALIDATION REPORT")
        print("=" * 70)
        
        print(f"\n📈 Métriques de Base:")
        print(f"  Total Trades: {self.total_trades}")
        print(f"  Win Rate: {self.win_rate * 100:.1f}%")
        print(f"  Profit Factor: {self.profit_factor:.2f}")
        print(f"  Avg Return: {self.avg_return:.4f}")
        print(f"  Std Return: {self.std_return:.4f}")
        
        print(f"\n🧪 Tests de Significativité:")
        for test in self.tests:
            status = "✅" if test.passed else "❌"
            print(f"  {status} {test.test_name}")
            print(f"      P-value: {test.p_value:.4f} | Confidence: {test.confidence_level:.1f}%")
            print(f"      {test.interpretation}")
        
        print(f"\n📊 Résumé:")
        print(f"  Tests passés: {self.tests_passed}/{self.tests_total}")
        print(f"  Confidence globale: {self.overall_confidence:.1f}%")
        print(f"  Statut: {'✅ SIGNIFICATIF' if self.is_significant else '❌ NON SIGNIFICATIF'}")
        
        if self.minimum_trades_needed > 0:
            print(f"  Trades minimum recommandés: {self.minimum_trades_needed}")
        
        print("\n" + "=" * 70)
        print(f"📋 RECOMMENDATION:")
        print(self.recommendation)
        print("=" * 70 + "\n")


class StatisticalValidator:
    """
    Validateur statistique pour les résultats de trading.
    
    Effectue plusieurs tests pour s'assurer que les résultats
    ne sont pas dus au hasard.
    """
    
    # Seuils de signification
    ALPHA = 0.05  # Niveau de signification (5%)
    MIN_TRADES_BASIC = 30  # Minimum absolu
    MIN_TRADES_RELIABLE = 100  # Pour résultats fiables
    
    def __init__(self, alpha: float = 0.05):
        """
        Args:
            alpha: Niveau de signification (default: 0.05 = 5%)
        """
        self.alpha = alpha
        self.validation = StatisticalValidation()
    
    def validate(self, trade_returns: List[float], win_rate: float = None,
                 profit_factor: float = None) -> StatisticalValidation:
        """
        Effectue la validation statistique complète.
        
        Args:
            trade_returns: Liste des returns de chaque trade (en % ou $)
            win_rate: Win rate observé (calculé si non fourni)
            profit_factor: Profit factor (calculé si non fourni)
            
        Returns:
            StatisticalValidation avec tous les tests
        """
        n = len(trade_returns)
        
        if n == 0:
            logger.error("❌ Pas de trades à valider")
            return self.validation
        
        logger.info("=" * 60)
        logger.info("🧪 DÉMARRAGE VALIDATION STATISTIQUE")
        logger.info("=" * 60)
        
        # Convertir en numpy
        returns = np.array(trade_returns)
        
        # Calculer les métriques de base si non fournies
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        
        if win_rate is None:
            win_rate = len(wins) / n if n > 0 else 0
        
        if profit_factor is None:
            total_wins = np.sum(wins) if len(wins) > 0 else 0
            total_losses = abs(np.sum(losses)) if len(losses) > 0 else 1
            profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        # Stocker les métriques
        self.validation.total_trades = n
        self.validation.win_rate = win_rate
        self.validation.profit_factor = profit_factor
        self.validation.avg_return = np.mean(returns)
        self.validation.std_return = np.std(returns)
        
        # Exécuter les tests
        self._test_minimum_trades(n)
        self._test_winrate_significance(n, win_rate)
        self._test_returns_significance(returns)
        self._test_profit_factor_significance(profit_factor, n)
        self._test_sharpe_ratio(returns)
        self._test_stability(returns)
        
        # Calculer le résultat global
        self.validation.calculate_overall()
        self._generate_recommendation()
        
        logger.info(f"✅ Validation terminée: {self.validation.tests_passed}/{self.validation.tests_total} tests passés")
        
        return self.validation
    
    def _test_minimum_trades(self, n: int):
        """Test 1: Nombre minimum de trades."""
        passed = n >= self.MIN_TRADES_BASIC
        confidence = min(100, (n / self.MIN_TRADES_RELIABLE) * 100)
        
        if n < self.MIN_TRADES_BASIC:
            interpretation = f"❌ {n} trades insuffisant. Minimum: {self.MIN_TRADES_BASIC}"
        elif n < self.MIN_TRADES_RELIABLE:
            interpretation = f"⚠️ {n} trades acceptable mais {self.MIN_TRADES_RELIABLE}+ recommandé"
        else:
            interpretation = f"✅ {n} trades suffisant pour significativité"
        
        # Calculer combien de trades supplémentaires sont nécessaires
        self.validation.minimum_trades_needed = max(0, self.MIN_TRADES_BASIC - n)
        
        self.validation.add_test(SignificanceTest(
            test_name="Minimum Trades",
            passed=passed,
            p_value=0 if passed else 1,
            confidence_level=confidence,
            observed_value=n,
            expected_value=self.MIN_TRADES_BASIC,
            interpretation=interpretation
        ))
    
    def _test_winrate_significance(self, n: int, win_rate: float):
        """Test 2: Le win rate est-il significativement > 50%?"""
        if not SCIPY_AVAILABLE:
            self.validation.add_test(SignificanceTest(
                test_name="Win Rate Binomial Test",
                passed=win_rate > 0.5,
                p_value=0.5 if win_rate > 0.5 else 1.0,
                confidence_level=50 if win_rate > 0.5 else 0,
                observed_value=win_rate,
                expected_value=0.5,
                interpretation="⚠️ scipy non disponible pour test binomial complet"
            ))
            return
        
        # Test binomial: H0: win_rate = 50%
        wins = int(n * win_rate)
        p_value = scipy_stats.binom_test(wins, n, 0.5, alternative='greater')
        
        passed = p_value < self.alpha and win_rate > 0.5
        confidence = (1 - p_value) * 100
        
        if passed:
            interpretation = f"✅ Win rate {win_rate*100:.1f}% significativement > 50%"
        elif win_rate > 0.5:
            interpretation = f"⚠️ Win rate {win_rate*100:.1f}% > 50% mais pas significatif (p={p_value:.3f})"
        else:
            interpretation = f"❌ Win rate {win_rate*100:.1f}% pas meilleur que le hasard"
        
        self.validation.add_test(SignificanceTest(
            test_name="Win Rate Binomial Test",
            passed=passed,
            p_value=p_value,
            confidence_level=confidence,
            observed_value=win_rate,
            expected_value=0.5,
            interpretation=interpretation
        ))
    
    def _test_returns_significance(self, returns: np.ndarray):
        """Test 3: Les returns sont-ils significativement > 0?"""
        if not SCIPY_AVAILABLE:
            mean_return = np.mean(returns)
            self.validation.add_test(SignificanceTest(
                test_name="Returns T-Test",
                passed=mean_return > 0,
                p_value=0.5 if mean_return > 0 else 1.0,
                confidence_level=50 if mean_return > 0 else 0,
                observed_value=mean_return,
                expected_value=0,
                interpretation="⚠️ scipy non disponible pour t-test complet"
            ))
            return
        
        # T-test à un échantillon: H0: mean = 0
        t_stat, p_value = scipy_stats.ttest_1samp(returns, 0)
        p_value = p_value / 2  # One-tailed (on veut > 0)
        
        mean_return = np.mean(returns)
        passed = p_value < self.alpha and mean_return > 0
        confidence = (1 - p_value) * 100 if mean_return > 0 else 0
        
        if passed:
            interpretation = f"✅ Return moyen {mean_return:.4f} significativement > 0"
        elif mean_return > 0:
            interpretation = f"⚠️ Return moyen positif mais pas significatif (p={p_value:.3f})"
        else:
            interpretation = f"❌ Return moyen négatif ({mean_return:.4f})"
        
        self.validation.add_test(SignificanceTest(
            test_name="Returns T-Test",
            passed=passed,
            p_value=p_value,
            confidence_level=confidence,
            observed_value=mean_return,
            expected_value=0,
            interpretation=interpretation
        ))
    
    def _test_profit_factor_significance(self, pf: float, n: int):
        """Test 4: Le profit factor est-il significativement > 1?"""
        # Pas de test statistique formel, on utilise une heuristique
        # PF > 1.5 avec 30+ trades = significatif
        
        passed = pf > 1.0 and n >= 30
        strong = pf >= 1.5 and n >= 50
        confidence = min(100, (pf - 1) * 50 + (n / 50) * 25) if pf > 1 else 0
        
        if strong:
            interpretation = f"✅ PF {pf:.2f} excellent avec {n} trades"
        elif passed:
            interpretation = f"⚠️ PF {pf:.2f} positif mais plus de trades recommandés"
        else:
            interpretation = f"❌ PF {pf:.2f} insuffisant ou pas assez de trades"
        
        self.validation.add_test(SignificanceTest(
            test_name="Profit Factor Test",
            passed=passed,
            p_value=0 if strong else (0.5 if passed else 1),
            confidence_level=confidence,
            observed_value=pf,
            expected_value=1.0,
            interpretation=interpretation
        ))
    
    def _test_sharpe_ratio(self, returns: np.ndarray):
        """Test 5: Le Sharpe ratio est-il acceptable?"""
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return == 0:
            sharpe = 0
        else:
            # Annualisé (assumant 252 jours de trading)
            sharpe = (mean_return / std_return) * np.sqrt(252)
        
        # Seuils: > 1 = bon, > 2 = excellent
        passed = sharpe > 0.5
        excellent = sharpe > 1.5
        confidence = min(100, sharpe * 50) if sharpe > 0 else 0
        
        if excellent:
            interpretation = f"✅ Sharpe {sharpe:.2f} excellent"
        elif passed:
            interpretation = f"⚠️ Sharpe {sharpe:.2f} acceptable"
        else:
            interpretation = f"❌ Sharpe {sharpe:.2f} insuffisant"
        
        self.validation.add_test(SignificanceTest(
            test_name="Sharpe Ratio Test",
            passed=passed,
            p_value=0 if excellent else (0.5 if passed else 1),
            confidence_level=confidence,
            observed_value=sharpe,
            expected_value=1.0,
            interpretation=interpretation
        ))
    
    def _test_stability(self, returns: np.ndarray):
        """Test 6: La stratégie est-elle stable dans le temps?"""
        n = len(returns)
        
        if n < 20:
            self.validation.add_test(SignificanceTest(
                test_name="Stability Test",
                passed=False,
                p_value=1.0,
                confidence_level=0,
                observed_value=0,
                expected_value=0.5,
                interpretation="❌ Pas assez de trades pour test de stabilité"
            ))
            return
        
        # Diviser en deux moitiés et comparer les performances
        mid = n // 2
        first_half = returns[:mid]
        second_half = returns[mid:]
        
        # Comparer les win rates
        wr1 = (first_half > 0).sum() / len(first_half)
        wr2 = (second_half > 0).sum() / len(second_half)
        
        # La différence devrait être < 15% pour être stable
        diff = abs(wr1 - wr2)
        passed = diff < 0.15
        confidence = max(0, (0.15 - diff) / 0.15 * 100)
        
        if passed:
            interpretation = f"✅ Performance stable (diff WR: {diff*100:.1f}%)"
        else:
            interpretation = f"❌ Performance instable (diff WR: {diff*100:.1f}%)"
        
        self.validation.add_test(SignificanceTest(
            test_name="Stability Test",
            passed=passed,
            p_value=diff,
            confidence_level=confidence,
            observed_value=diff,
            expected_value=0.15,
            interpretation=interpretation
        ))
    
    def _generate_recommendation(self):
        """Génère une recommandation basée sur les tests."""
        v = self.validation
        
        if v.is_significant:
            if v.overall_confidence >= 90:
                v.recommendation = ("✅ STRATÉGIE VALIDÉE avec haute confiance.\n"
                                    "   → Déployer avec le sizing prévu.\n"
                                    "   → Continuer le monitoring.")
            else:
                v.recommendation = ("⚠️ STRATÉGIE PROVISOIREMENT VALIDÉE.\n"
                                    "   → Commencer avec sizing réduit (50%).\n"
                                    "   → Augmenter après 50+ trades live.")
        else:
            if v.total_trades < self.MIN_TRADES_BASIC:
                v.recommendation = (f"❌ INSUFFISANT - Seulement {v.total_trades} trades.\n"
                                    f"   → Collecter {v.minimum_trades_needed}+ trades supplémentaires.\n"
                                    "   → Relancer la validation ensuite.")
            else:
                v.recommendation = ("❌ STRATÉGIE NON VALIDÉE statistiquement.\n"
                                    "   → Les résultats pourraient être dus au hasard.\n"
                                    "   → Revoir la stratégie avant déploiement live.")


# ============================================
# FONCTION UTILITAIRE
# ============================================
def validate_backtest_results(closed_trades: List, initial_capital: float = 10000.0) -> StatisticalValidation:
    """
    Fonction utilitaire pour valider des résultats de backtest.
    
    Args:
        closed_trades: Liste de BacktestTrade du backtester
        initial_capital: Capital initial pour calculer les returns
        
    Returns:
        StatisticalValidation
    """
    # Extraire les returns (en % du capital)
    trade_returns = []
    for t in closed_trades:
        if hasattr(t, 'pnl'):
            trade_returns.append(t.pnl / initial_capital)
    
    if not trade_returns:
        logger.error("❌ Pas de trades valides à analyser")
        return StatisticalValidation()
    
    # Valider
    validator = StatisticalValidator()
    return validator.validate(trade_returns)


# ============================================
# SCRIPT DE TEST
# ============================================
if __name__ == "__main__":
    # Simuler des trades
    np.random.seed(42)
    
    # Stratégie profitable simulée
    # 55% WR, ratio 1.2:1
    n_trades = 50
    n_wins = int(n_trades * 0.55)
    
    trades = []
    for i in range(n_wins):
        trades.append(np.random.uniform(15, 50))  # Gains
    for i in range(n_trades - n_wins):
        trades.append(-np.random.uniform(10, 30))  # Pertes
    
    np.random.shuffle(trades)
    
    # Valider
    validator = StatisticalValidator()
    results = validator.validate(trades)
    
    # Afficher le rapport
    results.print_report()
