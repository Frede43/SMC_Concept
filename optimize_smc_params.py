"""
Optimizer - Grid Search pour Paramètres SMC Optimaux

Teste différentes combinaisons de paramètres pour trouver
la configuration optimale maximisant Win Rate et ROI.

Usage:
    python optimize_smc_params.py

Author: Expert SMC/ICT
Date: 19 Janvier 2026
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itertools import product
import json
import pandas as pd
from datetime import datetime
from loguru import logger

# Paramètres à tester (grid search)
PARAM_GRID = {
    'min_confidence': [0.70, 0.75, 0.80, 0.85],
    'min_fvg_size': [3.0, 4.0, 5.0, 6.0],
    'min_adx': [20, 25, 30],
    'killzone_strict': [True, False],
}


class SMCOptimizer:
    """Optimise paramètres SMC par grid search."""
    
    def __init__(self, base_config: dict):
        self.base_config = base_config
        self.results = []
        
    def run_grid_search(self, start_date: str, end_date: str, symbols: list):
        """
        Exécute grid search sur toutes combinaisons.
        
        Args:
            start_date: Date début backtest (YYYY-MM-DD)
            end_date: Date fin backtest
            symbols: Liste symboles à tester
        """
        logger.info(f"🔍 Grid Search démarré: {len(list(product(*PARAM_GRID.values())))} combinaisons")
        
        combinations = list(product(
            PARAM_GRID['min_confidence'],
            PARAM_GRID['min_fvg_size'],
            PARAM_GRID['min_adx'],
            PARAM_GRID['killzone_strict']
        ))
        
        best_result = None
        best_params = None
        
        for i, (conf, fvg, adx, kz_strict) in enumerate(combinations, 1):
            logger.info(f"\n{'='*70}")
            logger.info(f"Test {i}/{len(combinations)}")
            logger.info(f"Params: conf={conf}, fvg={fvg}, adx={adx}, kz_strict={kz_strict}")
            logger.info(f"{'='*70}")
            
            # Créer config avec ces params
            config = self._create_config(conf, fvg, adx, kz_strict)
            
            # Run backtest (simplifié pour exemple)
            result = self._run_backtest_mock(config, start_date, end_date, symbols)
            
            # Enregistrer résultat
            self.results.append({
                'params': {
                    'min_confidence': conf,
                    'min_fvg_size': fvg,
                    'min_adx': adx,
                    'killzone_strict': kz_strict
                },
                'performance': result
            })
            
            # Check if best
            if best_result is None or result['roi'] > best_result['roi']:
                best_result = result
                best_params = (conf, fvg, adx, kz_strict)
                logger.info(f"🏆 NOUVEAU MEILLEUR: ROI={result['roi']:.2f}%, WR={result['win_rate']:.2f}%")
        
        return best_params, best_result
    
    def _create_config(self, conf, fvg, adx, kz_strict):
        """Crée config avec params spécifiques."""
        config = self.base_config.copy()
        config['smc']['min_confidence'] = conf
        config['smc']['fvg']['min_size_pips'] = fvg
        config['smc']['trend_strength']['min_adx'] = adx
        config['smc']['killzones']['strict_mode'] = kz_strict
        return config
    
    def _run_backtest_mock(self, config, start_date, end_date, symbols):
        """
        Mock backtest (à remplacer par vrai backtest).
        
        Pour l'instant, génère résultats aléatoires pour démonstration.
        En production, appeler votre moteur de backtest réel.
        """
        import random
        
        # Simulation (à remplacer par backtest réel)
        win_rate = 40 + random.random() * 20  # 40-60%
        roi = -10 + random.random() * 40  # -10% à +30%
        profit_factor = 0.8 + random.random() * 1.2  # 0.8 à 2.0
        total_trades = random.randint(100, 500)
        
        return {
            'win_rate': win_rate,
            'roi': roi,
            'profit_factor': profit_factor,
            'total_trades': total_trades,
            'max_drawdown': random.random() * 30,
            'sharpe_ratio': -1 + random.random() * 3
        }
    
    def save_results(self, filename: str = "optimization_results.json"):
        """Sauvegarde tous les résultats."""
        with open(filename, 'w') as f:
            json.dump(self.results, f, indent=2)
        logger.info(f"✅ Résultats sauvegardés: {filename}")
    
    def generate_report(self):
        """Génère rapport d'analyse."""
        if not self.results:
            return "Aucun résultat disponible"
        
        # Trier par ROI
        sorted_results = sorted(self.results, key=lambda x: x['performance']['roi'], reverse=True)
        
        report = f"""
{'='*70}
RAPPORT D'OPTIMISATION SMC
{'='*70}

Total combinaisons testées: {len(self.results)}

TOP 5 MEILLEURES CONFIGURATIONS:
"""
        
        for i, result in enumerate(sorted_results[:5], 1):
            params = result['params']
            perf = result['performance']
            
            report += f"""
{i}. Configuration:
   min_confidence: {params['min_confidence']}
   min_fvg_size: {params['min_fvg_size']}
   min_adx: {params['min_adx']}
   killzone_strict: {params['killzone_strict']}
   
   Performance:
   - ROI: {perf['roi']:.2f}%
   - Win Rate: {perf['win_rate']:.2f}%
   - Profit Factor: {perf['profit_factor']:.2f}
   - Trades: {perf['total_trades']}
   - Max DD: {perf['max_drawdown']:.2f}%
   
"""
        
        # Analyse patterns
        report += f"\n{'='*70}\nANALYSE PATTERNS:\n{'='*70}\n"
        
        # Meilleurs min_confidence
        by_confidence = {}
        for r in self.results:
            conf = r['params']['min_confidence']
            if conf not in by_confidence:
                by_confidence[conf] = []
            by_confidence[conf].append(r['performance']['roi'])
        
        report += "\nROI moyen par min_confidence:\n"
        for conf, rois in sorted(by_confidence.items()):
            avg_roi = sum(rois) / len(rois)
            report += f"  {conf}: {avg_roi:.2f}%\n"
        
        return report


def main():
    """Point d'entrée principal."""
    
    print("="*70)
    print("OPTIMISATION PARAMÈTRES SMC")
    print("="*70)
    print()
    
    # Config de base (charger depuis settings.yaml en production)
    base_config = {
        'smc': {
            'min_confidence': 0.75,
            'fvg': {'min_size_pips': 3.0},
            'trend_strength': {'min_adx': 25},
            'killzones': {'strict_mode': True}
        }
    }
    
    # Créer optimizer
    optimizer = SMCOptimizer(base_config)
    
    # Grid search
    print("\n🔍 Lancement Grid Search...")
    print(f"Combinaisons à tester: {len(list(product(*PARAM_GRID.values())))}\n")
    
    best_params, best_result = optimizer.run_grid_search(
        start_date="2024-01-01",
        end_date="2024-12-31",
        symbols=["EURUSD", "GBPUSD"]
    )
    
    # Résultats
    print("\n" + "="*70)
    print("✅ OPTIMISATION TERMINÉE")
    print("="*70)
    
    print(f"\n🏆 MEILLEURE CONFIGURATION:")
    print(f"   min_confidence: {best_params[0]}")
    print(f"   min_fvg_size: {best_params[1]}")
    print(f"   min_adx: {best_params[2]}")
    print(f"   killzone_strict: {best_params[3]}")
    
    print(f"\n📊 PERFORMANCE:")
    print(f"   ROI: {best_result['roi']:.2f}%")
    print(f"   Win Rate: {best_result['win_rate']:.2f}%")
    print(f"   Profit Factor: {best_result['profit_factor']:.2f}")
    print(f"   Total Trades: {best_result['total_trades']}")
    
    # Sauvegarder
    optimizer.save_results()
    
    # Rapport complet
    report = optimizer.generate_report()
    print("\n" + report)
    
    # Sauvegarder rapport
    with open("optimization_report.txt", 'w') as f:
        f.write(report)
    print("\n📄 Rapport complet sauvegardé: optimization_report.txt")
    
    print("\n" + "="*70)
    print("✅ PROCHAINES ÉTAPES:")
    print("="*70)
    print("1. Appliquer meilleurs paramètres dans config/settings.yaml")
    print("2. Backtest complet avec nouveaux params")
    print("3. Si Win Rate >50% → Paper trading")
    print("4. Si Win Rate <50% → Affiner davantage")


if __name__ == "__main__":
    main()
