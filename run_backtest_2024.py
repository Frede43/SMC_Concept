"""
Backtest Professionnel 2024 - Validation Out-of-Sample 1
Teste la performance sur l'année 2024 complète

Author: Antigravity AI
Date: 2026-01-11
Usage: python run_backtest_2024.py
"""

import sys
import os

# ✅ FIX CRASH EMOJI WINDOWS: Forcer l'encodage UTF-8 pour la console
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        # Fallback si reconfigure échoue
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from pathlib import Path
from datetime import datetime
import pandas as pd
from loguru import logger
import yaml

# Add project root
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from backtest.backtester import BacktestConfig, BacktestEngine

def run_backtest_2024():
    """Lance le backtest sur l'année 2024"""
    
    print("\n" + "="*70)
    print("📊 BACKTEST 2024 - VALIDATION OUT-OF-SAMPLE")
    print("="*70)
    print("\nObjectif: Valider edge statistique sur 2024")
    print("Période: 1er Janvier 2024 → 31 Décembre 2024")
    print("\nCritères de SUCCÈS:")
    print("  ✓ Win Rate > 60%")
    print("  ✓ Profit Factor > 1.5")
    print("  ✓ Max Drawdown < 10%")
    print("  ✓ Sharpe Ratio > 1.0")
    print("  ✓ Trades > 50 (statistiquement significatif)")
    
    # Charger configuration
    print("\n⚙️ Chargement configuration...")
    config_path = ROOT_DIR / 'config' / 'settings.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # Configuration backtest
    backtest_config = BacktestConfig(
        symbols=['GBPUSDm', 'EURUSDm', 'XAUUSDm', 'US30m'],  # Top 4 performers
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 12, 31),
        initial_capital=10000.0,  # $10,000 initial
        data_dir=ROOT_DIR / 'backtest' / 'data'
    )
    
    print(f"\n📋 Configuration:")
    print(f"  Symboles: {', '.join(backtest_config.symbols)}")
    print(f"  Période: {backtest_config.start_date.date()} → {backtest_config.end_date.date()}")
    print(f"  Capital: ${backtest_config.initial_capital:,.0f}")
    
    # Créer répertoire résultats
    results_dir = ROOT_DIR / 'backtest' / 'results' / '2024'
    results_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n" + "="*70)
    print("🔄 LANCEMENT BACKTEST...")
    print("="*70)
    print("\n⏳ Temps estimé: 2-5 minutes")
    print("   (Processing ~50,000 bougies M15 × 4 symboles)\n")
    
    # Lancer backtest
    try:
        engine = BacktestEngine(backtest_config, config.get('smc', {}))
        results = engine.run()
        
    except Exception as e:
        logger.exception("Backtest failed")
        print(f"\n❌ ERREUR: {e}")
        print("\nVérifiez:")
        print("  • Les données sont bien téléchargées (backtest/data/)")
        print("  • La configuration est valide (config/settings.yaml)")
        print("  • Les logs pour plus de détails: logs/backtest.log")
        return 1
    
    # Afficher résultats
    print("\n" + "="*70)
    print("📊 RÉSULTATS BACKTEST 2024")
    print("="*70)
    
    # Performance
    print(f"\n💰 PERFORMANCE:")
    print(f"  Capital Initial:  ${backtest_config.initial_capital:,.2f}")
    print(f"  Capital Final:    ${results['final_capital']:,.2f}")
    pnl = results['total_pnl']
    pnl_sign = "+" if pnl >= 0 else ""
    print(f"  P&L Total:        {pnl_sign}${pnl:,.2f}")
    roi_sign = "+" if results['roi'] >= 0 else ""
    print(f"  ROI:              {roi_sign}{results['roi']:.2f}%")
    
    # Trades
    print(f"\n📈 STATISTIQUES:")
    print(f"  Total Trades:     {results['total_trades']}")
    print(f"  Gagnants:         {results['winning_trades']}")
    print(f"  Perdants:         {results['losing_trades']}")
    print(f"  Break-even:       {results.get('breakeven_trades', 0)}")
    
    # Métriques clés
    print(f"\n🎯 MÉTRIQUES CLÉS:")
    
    # Win Rate
    wr = results['win_rate']
    wr_status = "✅" if wr >= 60 else "⚠️" if wr >= 55 else "❌"
    print(f"  Win Rate:         {wr:.2f}% {wr_status}")
    
    # Profit Factor
    pf = results['profit_factor']
    pf_status = "✅" if pf >= 1.5 else "⚠️" if pf >= 1.3 else "❌"
    print(f"  Profit Factor:    {pf:.3f} {pf_status}")
    
    # Max Drawdown
    dd = results['max_drawdown']
    dd_status = "✅" if dd <= 10 else "⚠️" if dd <= 15 else "❌"
    print(f"  Max Drawdown:     {dd:.2f}% {dd_status}")
    
    # Sharpe Ratio
    sr = results['sharpe_ratio']
    sr_status = "✅" if sr >= 1.0 else "⚠️" if sr >= 0.7 else "❌"
    print(f"  Sharpe Ratio:     {sr:.3f} {sr_status}")
    
    # Risk/Reward
    rr = results.get('risk_reward_avg', 0)
    print(f"  Risk/Reward Avg:  1:{rr:.2f}")
    
    # Moyennes
    if results.get('avg_win'):
        print(f"\n💵 MOYENNES:")
        print(f"  Gain Moyen:       ${results['avg_win']:,.2f}")
        print(f"  Perte Moyenne:    ${results.get('avg_loss', 0):,.2f}")
        print(f"  Plus Gros Gain:   ${results.get('largest_win', 0):,.2f}")
        print(f"  Plus Grosse Perte:${results.get('largest_loss', 0):,.2f}")
    
    # Évaluation globale
    print(f"\n" + "="*70)
    print("🎓 ÉVALUATION:")
    print("="*70 + "\n")
    
    score = 0
    max_score = 5
    issues = []
    
    # Critère 1: Win Rate
    if wr >= 60:
        print("  ✅ Win Rate EXCELLENT (≥60%)")
        score += 1
    elif wr >= 55:
        print("  ⚠️ Win Rate BON (55-60%)")
        score += 0.5
        issues.append("Augmenter min_confidence à 85%")
    else:
        print("  ❌ Win Rate INSUFFISANT (<55%)")
        issues.append("CRITIQUE: Augmenter confluence_required à 3")
    
    # Critère 2: Profit Factor
    if pf >= 1.5:
        print("  ✅ Profit Factor EXCELLENT (≥1.5)")
        score += 1
    elif pf >= 1.3:
        print("  ⚠️ Profit Factor BON (1.3-1.5)")
        score += 0.5
        issues.append("Optimiser TP/SL ratios")
    else:
        print("  ❌ Profit Factor FAIBLE (<1.3)")
        issues.append("CRITIQUE: Revoir stratégies actives")
    
    # Critère 3: Max Drawdown
    if dd <= 10:
        print("  ✅ Max Drawdown EXCELLENT (≤10%)")
        score += 1
    elif dd <= 15:
        print("  ⚠️ Max Drawdown ACCEPTABLE (10-15%)")
        score += 0.5
        issues.append("Réduire max_open_trades")
    else:
        print("  ❌ Max Drawdown ÉLEVÉ (>15%)")
        issues.append("CRITIQUE: Réduire risk_per_trade")
    
    # Critère 4: Sharpe Ratio
    if sr >= 1.0:
        print("  ✅ Sharpe Ratio EXCELLENT (≥1.0)")
        score += 1
    elif sr >= 0.7:
        print("  ⚠️ Sharpe Ratio BON (0.7-1.0)")
        score += 0.5
    else:
        print("  ❌ Sharpe Ratio FAIBLE (<0.7)")
        issues.append("Variance trop élevée")
    
    # Critère 5: Nombre de trades
    if results['total_trades'] >= 50:
        print("  ✅ Trades Suffisants (≥50)")
        score += 1
    elif results['total_trades'] >= 30:
        print("  ⚠️ Trades Limités (30-50)")
        score += 0.5
        issues.append("Données limitées - Valider sur 2025")
    else:
        print("  ❌ Trades Insuffisants (<30)")
        issues.append("CRITIQUE: Pas assez de données")
    
    # Score final
    score_pct = (score / max_score) * 100
    print(f"\n  📊 Score Global: {score:.1f}/{max_score} ({score_pct:.0f}%)")
    
    # Décision
    print(f"\n" + "="*70)
    if score >= 4.5:
        print("🏆 DÉCISION: EXCELLENT - Passer au Backtest 2025")
        decision = "PASS"
    elif score >= 3.5:
        print("⚠️ DÉCISION: BON - Appliquer recommandations puis 2025")
        decision = "PASS_WITH_WARNINGS"
    elif score >= 2.5:
        print("⚠️ DÉCISION: ACCEPTABLE - Optimisations requises")
        decision = "NEEDS_OPTIMIZATION"
    else:
        print("❌ DÉCISION: ÉCHEC - NE PAS continuer")
        decision = "FAIL"
    print("="*70)
    
    # Recommandations
    if issues:
        print(f"\n📝 RECOMMANDATIONS:")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
    
    # Sauvegarder résultats
    import json
    results_file = results_dir / 'backtest_2024_results.json'
    
    # Préparer données pour sauvegarde (sans objets)
    save_data = {
        'date': datetime.now().isoformat(),
        'period': '2024-01-01 to 2024-12-31',
        'symbols': backtest_config.symbols,
        'capital_initial': backtest_config.initial_capital,
        'capital_final': results['final_capital'],
        'total_pnl': results['total_pnl'],
        'roi': results['roi'],
        'total_trades': results['total_trades'],
        'winning_trades': results['winning_trades'],
        'losing_trades': results['losing_trades'],
        'win_rate': results['win_rate'],
        'profit_factor': results['profit_factor'],
        'max_drawdown': results['max_drawdown'],
        'sharpe_ratio': results['sharpe_ratio'],
        'avg_win': results.get('avg_win', 0),
        'avg_loss': results.get('avg_loss', 0),
        'score': score,
        'decision': decision,
        'issues': issues
    }
    
    with open(results_file, 'w') as f:
        json.dump(save_data, f, indent=4)
    
    print(f"\n💾 Résultats sauvegardés:")
    print(f"  • {results_file}")
    
    # Prochaines étapes
    print(f"\n" + "="*70)
    print("🎯 PROCHAINES ÉTAPES:")
    print("="*70 + "\n")
    
    if decision == "PASS":
        print("  ✅ 1. Résultats validés!")
        print("  ✅ 2. Lancer backtest 2025:")
        print("       python run_backtest_2025.py")
        print("  ✅ 3. Comparer 2024 vs 2025")
    elif decision == "PASS_WITH_WARNINGS":
        print("  ⚠️ 1. Noter les warnings ci-dessus")
        print("  ⚠️ 2. Lancer backtest 2025 quand même")
        print("  ⚠️ 3. Si 2025 similaire, appliquer optimisations")
    elif decision == "NEEDS_OPTIMIZATION":
        print("  ⚠️ 1. Appliquer recommandations (config/settings.yaml)")
        print("  ⚠️ 2. Re-lancer ce backtest 2024")
        print("  ⚠️ 3. Viser score ≥ 4/5")
    else:
        print("  ❌ 1. STOP - Ne pas continuer")
        print("  ❌ 2. Analyser les trades perdants")
        print("  ❌ 3. Revoir configuration fondamentale")
        print("  ❌ 4. Consulter POINT_DE_VUE_EXPERT.md")
    
    print("\n" + "="*70 + "\n")
    
    return 0 if score >= 3.5 else 1


if __name__ == "__main__":
    try:
        exit_code = run_backtest_2024()
        exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️ Backtest interrompu par l'utilisateur")
        exit(1)
    except Exception as e:
        logger.exception("Fatal error in backtest")
        print(f"\n❌ ERREUR FATALE: {e}")
        print("\nStack trace dans logs/backtest.log")
        exit(1)
