# -*- coding: utf-8 -*-
"""
Script de Profiling pour Backtest SMC
Identifie les bottlenecks de performance

Usage:
    python profile_backtest_simple.py

Genere:
    - backtest.prof (fichier de profiling)
    - Rapport texte des top fonctions
"""

import sys
import cProfile
import pstats
from pathlib import Path
from datetime import datetime
from io import StringIO

# Add project root
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from backtest.backtester import BacktestConfig, BacktestEngine
import yaml


def run_quick_backtest():
    """Backtest rapide sur 3 mois pour profiling"""
    
    print("\n" + "="*70)
    print("PROFILING BACKTEST - Test 3 mois")
    print("="*70 + "\n")
    
    # Configuration
    config_path = ROOT_DIR / 'config' / 'settings.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # Periode courte pour profiling rapide
    backtest_config = BacktestConfig(
        symbols=['EURUSDm'],  # 1 seul symbole pour profiling
        start_date=datetime(2024, 10, 1),  # 3 mois seulement
        end_date=datetime(2024, 12, 31),
        initial_capital=10000.0,
        data_dir=ROOT_DIR / 'backtest' / 'data'
    )
    
    print(f"Symbole: {backtest_config.symbols[0]}")
    print(f"Periode: {backtest_config.start_date.date()} -> {backtest_config.end_date.date()}")
    print(f"Timeframe: M15 (environ 12,000 bougies)")
    print("\nLancement profiling...\n")
    
    # Creer et lancer engine
    engine = BacktestEngine(backtest_config, config.get('smc', {}))
    results = engine.run()
    
    print(f"\nProfiling termine!")
    print(f"   Trades: {results['total_trades']}")
    print(f"   Win Rate: {results['win_rate']:.1f}%")
    
    return results


def analyze_profile(prof_file: Path):
    """Analyse le fichier de profiling et genere un rapport"""
    
    print("\n" + "="*70)
    print("ANALYSE DES RESULTATS")
    print("="*70 + "\n")
    
    # Charger stats
    stats = pstats.Stats(str(prof_file))
    
    # Trier par temps cumulatif
    stats.strip_dirs()
    stats.sort_stats('cumulative')
    
    print("TOP 20 FONCTIONS PAR TEMPS CUMULATIF:\n")
    stats.print_stats(20)
    
    # Sauvegarder rapport detaille
    report_file = ROOT_DIR / 'backtest' / 'profiling_report.txt'
    with open(report_file, 'w', encoding='utf-8') as f:
        stats.stream = f
        f.write("=" * 80 + "\n")
        f.write("PROFILING REPORT - SMC Backtest\n")
        f.write(f"Genere: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")
        
        f.write("TOP 30 FONCTIONS PAR TEMPS CUMULATIF:\n")
        f.write("-" * 80 + "\n")
        stats.print_stats(30)
        
        f.write("\n\n" + "=" * 80 + "\n")
        f.write("TOP 30 FONCTIONS PAR TEMPS PROPRE (sans appels):\n")
        f.write("-" * 80 + "\n")
        stats.sort_stats('time')
        stats.print_stats(30)
        
        f.write("\n\n" + "=" * 80 + "\n")
        f.write("FONCTIONS APPELEES FREQUEMMENT:\n")
        f.write("-" * 80 + "\n")
        stats.sort_stats('calls')
        stats.print_stats(30)
    
    print(f"\nRapport detaille sauvegarde: {report_file}")
    
    # Instructions pour visualisation
    print("\n" + "="*70)
    print("VISUALISATION INTERACTIVE (Optionnel)")
    print("="*70 + "\n")
    print("Pour une analyse visuelle interactive:")
    print(f"  1. Installer: pip install snakeviz")
    print(f"  2. Lancer: snakeviz {prof_file}")
    print(f"  3. Ouvre navigateur avec flamegraph interactif\n")


def main():
    """Point d'entree principal"""
    
    prof_file = ROOT_DIR / 'backtest' / 'backtest.prof'
    
    print("\n" + "="*70)
    print("PROFILING BACKTEST SMC")
    print("="*70)
    print("\nCe script va:")
    print("  1. Lancer un backtest de 3 mois (rapide)")
    print("  2. Profiler toutes les fonctions appelees")
    print("  3. Identifier les bottlenecks de performance")
    print("  4. Generer un rapport detaille\n")
    
    # Profiler le backtest
    profiler = cProfile.Profile()
    profiler.enable()
    
    try:
        results = run_quick_backtest()
    except Exception as e:
        profiler.disable()
        print(f"\nERRUER pendant le backtest: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    profiler.disable()
    
    # Sauvegarder profiling
    prof_file.parent.mkdir(exist_ok=True)
    profiler.dump_stats(str(prof_file))
    
    print(f"\nProfiling sauvegarde: {prof_file}")
    
    # Analyser
    analyze_profile(prof_file)
    
    print("\n" + "="*70)
    print("PROCHAINES ETAPES")
    print("="*70 + "\n")
    print("1. Lire le rapport: backtest/profiling_report.txt")
    print("2. Identifier les fonctions > 10% du temps total")
    print("3. Optimiser ces fonctions en priorite")
    print("4. Re-profiler pour mesurer l'amelioration\n")
    
    return 0


if __name__ == "__main__":
    exit(main())
