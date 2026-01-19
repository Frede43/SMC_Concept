"""
Walk-Forward Analysis Module
============================
Système avancé pour éviter le curve fitting et valider la robustesse de la stratégie.

Méthode:
1. Diviser les données en N segments
2. Pour chaque segment:
   - Optimizer sur les (N-1) premiers segments → In-Sample (IS)
   - Tester sur le dernier segment → Out-of-Sample (OOS)
3. Comparer performance IS vs OOS
4. Calculer le Robustness Ratio

Interprétation du Robustness Ratio:
- > 0.85 : Excellent - Stratégie robuste
- 0.70 - 0.85 : Bon - Minor curve fitting
- 0.50 - 0.70 : Attention - Significant curve fitting
- < 0.50 : Danger - Over-optimized
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd
from loguru import logger
import json

# Ajouter le répertoire racine au path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backtest.enhanced_backtester import EnhancedBacktester, BacktestConfig, BacktestMetrics


@dataclass
class WalkForwardSegment:
    """Résultats d'un segment du Walk-Forward."""
    segment_id: int
    is_start: datetime
    is_end: datetime
    oos_start: datetime
    oos_end: datetime
    
    # Métriques In-Sample
    is_profit_factor: float = 0.0
    is_win_rate: float = 0.0
    is_total_trades: int = 0
    is_total_pnl: float = 0.0
    is_max_drawdown: float = 0.0
    is_sharpe: float = 0.0
    
    # Métriques Out-of-Sample
    oos_profit_factor: float = 0.0
    oos_win_rate: float = 0.0
    oos_total_trades: int = 0
    oos_total_pnl: float = 0.0
    oos_max_drawdown: float = 0.0
    oos_sharpe: float = 0.0
    
    # Ratio de robustesse pour ce segment
    segment_robustness: float = 0.0
    
    def calculate_robustness(self):
        """Calcule le ratio de robustesse pour ce segment."""
        if self.is_profit_factor > 0:
            self.segment_robustness = self.oos_profit_factor / self.is_profit_factor
        else:
            self.segment_robustness = 0.0
    
    def to_dict(self) -> Dict:
        return {
            'segment_id': self.segment_id,
            'is_period': f"{self.is_start.date()} → {self.is_end.date()}",
            'oos_period': f"{self.oos_start.date()} → {self.oos_end.date()}",
            'is_metrics': {
                'profit_factor': round(self.is_profit_factor, 2),
                'win_rate': round(self.is_win_rate * 100, 1),
                'total_trades': self.is_total_trades,
                'pnl': round(self.is_total_pnl, 2),
                'max_dd': round(self.is_max_drawdown, 1),
                'sharpe': round(self.is_sharpe, 2)
            },
            'oos_metrics': {
                'profit_factor': round(self.oos_profit_factor, 2),
                'win_rate': round(self.oos_win_rate * 100, 1),
                'total_trades': self.oos_total_trades,
                'pnl': round(self.oos_total_pnl, 2),
                'max_dd': round(self.oos_max_drawdown, 1),
                'sharpe': round(self.oos_sharpe, 2)
            },
            'robustness': round(self.segment_robustness, 3)
        }


@dataclass
class WalkForwardResults:
    """Résultats complets du Walk-Forward Analysis."""
    segments: List[WalkForwardSegment] = field(default_factory=list)
    
    # Métriques agrégées
    avg_is_profit_factor: float = 0.0
    avg_oos_profit_factor: float = 0.0
    avg_is_win_rate: float = 0.0
    avg_oos_win_rate: float = 0.0
    total_is_trades: int = 0
    total_oos_trades: int = 0
    total_is_pnl: float = 0.0
    total_oos_pnl: float = 0.0
    
    # Ratio de robustesse global
    robustness_ratio: float = 0.0
    robustness_rating: str = ""
    
    # Statistiques de variance
    is_pf_std: float = 0.0
    oos_pf_std: float = 0.0
    consistency_score: float = 0.0
    
    # Verdict
    is_robust: bool = False
    recommendation: str = ""
    
    def calculate_aggregates(self):
        """Calcule les métriques agrégées."""
        if not self.segments:
            return
        
        n = len(self.segments)
        
        # Moyennes
        self.avg_is_profit_factor = np.mean([s.is_profit_factor for s in self.segments])
        self.avg_oos_profit_factor = np.mean([s.oos_profit_factor for s in self.segments])
        self.avg_is_win_rate = np.mean([s.is_win_rate for s in self.segments])
        self.avg_oos_win_rate = np.mean([s.oos_win_rate for s in self.segments])
        
        # Totaux
        self.total_is_trades = sum(s.is_total_trades for s in self.segments)
        self.total_oos_trades = sum(s.oos_total_trades for s in self.segments)
        self.total_is_pnl = sum(s.is_total_pnl for s in self.segments)
        self.total_oos_pnl = sum(s.oos_total_pnl for s in self.segments)
        
        # Écarts-types (mesure de consistance)
        self.is_pf_std = np.std([s.is_profit_factor for s in self.segments])
        self.oos_pf_std = np.std([s.oos_profit_factor for s in self.segments])
        
        # Robustness Ratio global
        if self.avg_is_profit_factor > 0:
            self.robustness_ratio = self.avg_oos_profit_factor / self.avg_is_profit_factor
        
        # Consistency Score (inverse de la variance relative)
        # Score élevé = résultats consistants entre segments
        if self.avg_oos_profit_factor > 0:
            cv = self.oos_pf_std / self.avg_oos_profit_factor  # Coefficient de variation
            self.consistency_score = max(0, 1 - cv) * 100
        
        # Rating et recommandations
        self._evaluate_robustness()
    
    def _evaluate_robustness(self):
        """Évalue la robustesse et génère des recommandations."""
        rr = self.robustness_ratio
        
        if rr >= 0.85:
            self.robustness_rating = "EXCELLENT"
            self.is_robust = True
            self.recommendation = "✅ Stratégie robuste. Prête pour le déploiement live avec monitoring."
        elif rr >= 0.70:
            self.robustness_rating = "BON"
            self.is_robust = True
            self.recommendation = "✅ Stratégie acceptable. Commencer en micro-lot avec surveillance."
        elif rr >= 0.50:
            self.robustness_rating = "ATTENTION"
            self.is_robust = False
            self.recommendation = "⚠️ Curve fitting significatif détecté. Réviser les paramètres avant live."
        else:
            self.robustness_rating = "DANGER"
            self.is_robust = False
            self.recommendation = "❌ Sur-optimisation sévère. NE PAS déployer. Revoir la stratégie."
        
        # Ajouter des recommandations basées sur la consistance
        if self.consistency_score < 50:
            self.recommendation += "\n⚠️ Haute variance entre segments. Résultats imprévisibles."
        
        # Vérifier le nombre de trades
        if self.total_oos_trades < 30:
            self.recommendation += f"\n⚠️ Seulement {self.total_oos_trades} trades OOS. Statistiquement insuffisant."
    
    def to_dict(self) -> Dict:
        return {
            'summary': {
                'robustness_ratio': round(self.robustness_ratio, 3),
                'robustness_rating': self.robustness_rating,
                'consistency_score': round(self.consistency_score, 1),
                'is_robust': self.is_robust
            },
            'aggregates': {
                'in_sample': {
                    'avg_profit_factor': round(self.avg_is_profit_factor, 2),
                    'avg_win_rate': round(self.avg_is_win_rate * 100, 1),
                    'total_trades': self.total_is_trades,
                    'total_pnl': round(self.total_is_pnl, 2),
                    'pf_std': round(self.is_pf_std, 2)
                },
                'out_of_sample': {
                    'avg_profit_factor': round(self.avg_oos_profit_factor, 2),
                    'avg_win_rate': round(self.avg_oos_win_rate * 100, 1),
                    'total_trades': self.total_oos_trades,
                    'total_pnl': round(self.total_oos_pnl, 2),
                    'pf_std': round(self.oos_pf_std, 2)
                }
            },
            'segments': [s.to_dict() for s in self.segments],
            'recommendation': self.recommendation
        }
    
    def print_report(self):
        """Affiche un rapport formaté."""
        print("\n" + "=" * 70)
        print("📊 WALK-FORWARD ANALYSIS REPORT")
        print("=" * 70)
        
        print(f"\n🎯 ROBUSTNESS RATIO: {self.robustness_ratio:.2%}")
        print(f"📈 Rating: {self.robustness_rating}")
        print(f"🎲 Consistency Score: {self.consistency_score:.1f}%")
        
        print("\n" + "-" * 40)
        print("IN-SAMPLE (Training)")
        print("-" * 40)
        print(f"  Avg Profit Factor: {self.avg_is_profit_factor:.2f} (±{self.is_pf_std:.2f})")
        print(f"  Avg Win Rate: {self.avg_is_win_rate * 100:.1f}%")
        print(f"  Total Trades: {self.total_is_trades}")
        print(f"  Total PnL: ${self.total_is_pnl:.2f}")
        
        print("\n" + "-" * 40)
        print("OUT-OF-SAMPLE (Validation)")
        print("-" * 40)
        print(f"  Avg Profit Factor: {self.avg_oos_profit_factor:.2f} (±{self.oos_pf_std:.2f})")
        print(f"  Avg Win Rate: {self.avg_oos_win_rate * 100:.1f}%")
        print(f"  Total Trades: {self.total_oos_trades}")
        print(f"  Total PnL: ${self.total_oos_pnl:.2f}")
        
        print("\n" + "-" * 40)
        print("SEGMENT DETAILS")
        print("-" * 40)
        for seg in self.segments:
            print(f"\n  Segment {seg.segment_id}:")
            print(f"    IS: PF={seg.is_profit_factor:.2f}, Trades={seg.is_total_trades}")
            print(f"    OOS: PF={seg.oos_profit_factor:.2f}, Trades={seg.oos_total_trades}")
            print(f"    Robustness: {seg.segment_robustness:.2%}")
        
        print("\n" + "=" * 70)
        print("📋 RECOMMENDATION:")
        print(self.recommendation)
        print("=" * 70 + "\n")


class WalkForwardAnalyzer:
    """
    Walk-Forward Analyzer pour éviter le curve fitting.
    
    Méthode Anchored Walk-Forward:
    - Le début reste ancré (toutes les données passées sont utilisées)
    - Seule la fenêtre OOS avance
    
    Exemple avec 5 segments sur 1 an:
    Segment 1: IS [Jan-Sept], OOS [Oct-Nov]
    Segment 2: IS [Jan-Nov], OOS [Dec-Jan]
    ...etc
    """
    
    def __init__(self, base_config: BacktestConfig, n_segments: int = 5,
                 oos_ratio: float = 0.20, anchored: bool = True):
        """
        Args:
            base_config: Configuration de base du backtest
            n_segments: Nombre de segments (default: 5)
            oos_ratio: Ratio de données pour OOS (default: 20%)
            anchored: Si True, utilise la méthode ancrée (recommandé)
        """
        self.base_config = base_config
        self.n_segments = n_segments
        self.oos_ratio = oos_ratio
        self.anchored = anchored
        self.results = WalkForwardResults()
    
    def run(self, progress_callback=None) -> WalkForwardResults:
        """
        Exécute le Walk-Forward Analysis complet.
        
        Returns:
            WalkForwardResults avec toutes les métriques
        """
        logger.info("=" * 60)
        logger.info("🚀 DÉMARRAGE WALK-FORWARD ANALYSIS")
        logger.info("=" * 60)
        logger.info(f"📅 Période totale: {self.base_config.start_date.date()} → {self.base_config.end_date.date()}")
        logger.info(f"📊 Segments: {self.n_segments}, OOS Ratio: {self.oos_ratio:.0%}")
        logger.info(f"📌 Méthode: {'Anchored' if self.anchored else 'Rolling'}")
        
        # Calculer les dates des segments
        segments = self._generate_segments()
        
        # Exécuter chaque segment
        for i, (is_start, is_end, oos_start, oos_end) in enumerate(segments):
            logger.info(f"\n--- Segment {i+1}/{len(segments)} ---")
            logger.info(f"  IS: {is_start.date()} → {is_end.date()}")
            logger.info(f"  OOS: {oos_start.date()} → {oos_end.date()}")
            
            if progress_callback:
                progress_callback((i / len(segments)) * 100, f"Segment {i+1}/{len(segments)}")
            
            segment_result = self._run_segment(i+1, is_start, is_end, oos_start, oos_end)
            self.results.segments.append(segment_result)
        
        # Calculer les agrégats
        self.results.calculate_aggregates()
        
        logger.info("\n" + "=" * 60)
        logger.info("✅ WALK-FORWARD ANALYSIS TERMINÉ")
        logger.info("=" * 60)
        
        return self.results
    
    def _generate_segments(self) -> List[Tuple[datetime, datetime, datetime, datetime]]:
        """Génère les périodes IS/OOS pour chaque segment."""
        segments = []
        
        total_days = (self.base_config.end_date - self.base_config.start_date).days
        oos_days = int(total_days * self.oos_ratio / self.n_segments)
        
        if self.anchored:
            # Méthode Anchored: IS commence toujours au début
            for i in range(self.n_segments):
                oos_end = self.base_config.end_date - timedelta(days=oos_days * (self.n_segments - i - 1))
                oos_start = oos_end - timedelta(days=oos_days)
                is_start = self.base_config.start_date
                is_end = oos_start - timedelta(days=1)
                
                if is_end > is_start:  # Vérifier validité
                    segments.append((is_start, is_end, oos_start, oos_end))
        else:
            # Méthode Rolling: fenêtre glissante
            is_days = int(total_days * (1 - self.oos_ratio))
            
            for i in range(self.n_segments):
                offset = i * (total_days // self.n_segments)
                is_start = self.base_config.start_date + timedelta(days=offset)
                is_end = is_start + timedelta(days=is_days)
                oos_start = is_end + timedelta(days=1)
                oos_end = min(oos_start + timedelta(days=oos_days), self.base_config.end_date)
                
                if oos_end > oos_start:
                    segments.append((is_start, is_end, oos_start, oos_end))
        
        return segments
    
    def _run_segment(self, segment_id: int, is_start: datetime, is_end: datetime,
                     oos_start: datetime, oos_end: datetime) -> WalkForwardSegment:
        """Exécute un segment IS + OOS."""
        segment = WalkForwardSegment(
            segment_id=segment_id,
            is_start=is_start, is_end=is_end,
            oos_start=oos_start, oos_end=oos_end
        )
        
        # Configuration In-Sample
        is_config = BacktestConfig(
            symbols=self.base_config.symbols,
            start_date=is_start,
            end_date=is_end,
            initial_capital=self.base_config.initial_capital,
            risk_per_trade=self.base_config.risk_per_trade,
            use_fixed_lot=self.base_config.use_fixed_lot,
            fixed_lot_size=self.base_config.fixed_lot_size,
            max_trades_per_day=self.base_config.max_trades_per_day,
            max_open_trades=self.base_config.max_open_trades,
            ltf=self.base_config.ltf,
            htf=self.base_config.htf,
            include_spread=self.base_config.include_spread,
            include_slippage=self.base_config.include_slippage
        )
        
        # Configuration Out-of-Sample
        oos_config = BacktestConfig(
            symbols=self.base_config.symbols,
            start_date=oos_start,
            end_date=oos_end,
            initial_capital=self.base_config.initial_capital,
            risk_per_trade=self.base_config.risk_per_trade,
            use_fixed_lot=self.base_config.use_fixed_lot,
            fixed_lot_size=self.base_config.fixed_lot_size,
            max_trades_per_day=self.base_config.max_trades_per_day,
            max_open_trades=self.base_config.max_open_trades,
            ltf=self.base_config.ltf,
            htf=self.base_config.htf,
            include_spread=self.base_config.include_spread,
            include_slippage=self.base_config.include_slippage
        )
        
        # Exécuter les backtests
        try:
            logger.info(f"  Running In-Sample backtest...")
            is_backtester = EnhancedBacktester(is_config)
            is_metrics = is_backtester.run()
            
            segment.is_profit_factor = is_metrics.profit_factor
            segment.is_win_rate = is_metrics.win_rate
            segment.is_total_trades = is_metrics.total_trades
            segment.is_total_pnl = is_metrics.total_pnl
            segment.is_max_drawdown = is_metrics.max_drawdown_pct
            segment.is_sharpe = is_metrics.sharpe_ratio
            
            logger.info(f"  IS Results: PF={is_metrics.profit_factor:.2f}, WR={is_metrics.win_rate*100:.1f}%, Trades={is_metrics.total_trades}")
        
        except Exception as e:
            logger.error(f"  ❌ Erreur IS: {e}")
        
        try:
            logger.info(f"  Running Out-of-Sample backtest...")
            oos_backtester = EnhancedBacktester(oos_config)
            oos_metrics = oos_backtester.run()
            
            segment.oos_profit_factor = oos_metrics.profit_factor
            segment.oos_win_rate = oos_metrics.win_rate
            segment.oos_total_trades = oos_metrics.total_trades
            segment.oos_total_pnl = oos_metrics.total_pnl
            segment.oos_max_drawdown = oos_metrics.max_drawdown_pct
            segment.oos_sharpe = oos_metrics.sharpe_ratio
            
            logger.info(f"  OOS Results: PF={oos_metrics.profit_factor:.2f}, WR={oos_metrics.win_rate*100:.1f}%, Trades={oos_metrics.total_trades}")
        
        except Exception as e:
            logger.error(f"  ❌ Erreur OOS: {e}")
        
        # Calculer la robustesse du segment
        segment.calculate_robustness()
        logger.info(f"  Segment Robustness: {segment.segment_robustness:.2%}")
        
        return segment
    
    def save_results(self, output_dir: Path = None) -> Path:
        """Sauvegarde les résultats en JSON."""
        if output_dir is None:
            output_dir = ROOT_DIR / "backtest" / "results"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"walk_forward_{timestamp}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results.to_dict(), f, indent=2, ensure_ascii=False, default=str)
        
        logger.info(f"📁 Résultats sauvegardés: {output_file}")
        return output_file


# ============================================
# SCRIPT DE TEST
# ============================================
if __name__ == "__main__":
    from datetime import datetime
    
    # Configuration de test
    config = BacktestConfig(
        symbols=["XAUUSDm"],
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 12, 31),
        initial_capital=10000.0,
        use_fixed_lot=True,
        fixed_lot_size=0.01
    )
    
    # Lancer le Walk-Forward
    analyzer = WalkForwardAnalyzer(config, n_segments=4)
    results = analyzer.run()
    
    # Afficher le rapport
    results.print_report()
    
    # Sauvegarder
    analyzer.save_results()
