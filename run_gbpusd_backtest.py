"""
Backtest Complet GBPUSD - Configuration PRO
Utilise les données M15 et la configuration optimisée
"""

import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
from loguru import logger

# Add project root
sys.path.insert(0, str(Path(__file__).parent))

from utils.helpers import load_config

def run_gbpusd_backtest():
    """Lance le backtest avec les données GBPUSDm"""
    
    print("\n" + "="*75)
    print("🚀 BACKTEST PROFESSIONNEL - GBPUSDm")
    print("Configuration: OPTIMISÉE (Feedbacks IA Experts)")
    print("="*75 + "\n")
    
    # Configuration
    config_file = "config/settings.yaml"
    data_file = Path("data/GBPUSDm_M15_backtest.csv")
    
    # Vérifier fichier données
    if not data_file.exists():
        print(f"❌ ERROR: Fichier de données non trouvé: {data_file}")
        print("\nVeuillez d'abord exécuter:")
        print("  python prepare_backtest_data.py")
        return 1
    
    # Charger config
    print("⚙️  Chargement configuration...")
    try:
        config = load_config(config_file)
    except Exception as e:
        print(f"❌ ERROR: Chargement config échoué: {e}")
        return 1
    
    # Charger données
    print(f"📊 Chargement données: {data_file.name}")
    try:
        df = pd.read_csv(data_file)
        df['time'] = pd.to_datetime(df['time'])
    except Exception as e:
        print(f"❌ ERROR: Chargement données échoué: {e}")
        return 1
    
    print(f"   Bougies: {len(df):,}")
    print(f"   Période: {df['time'].min().date()} → {df['time'].max().date()}")
    print(f"   Durée: {(df['time'].max() - df['time'].min()).days} jours")
    
    # Vérifier config GBPUSD
    gbp_config = next((s for s in config['symbols'] if 'GBP' in s['name']), None)
    
    if not gbp_config:
        print("❌ ERROR: GBPUSDm non trouvé dans config")
        return 1
    
    if not gbp_config.get('enabled', False):
        print("❌ ERROR: GBPUSDm est désactivé dans config")
        return 1
    
    print(f"\n✅ Symbole: {gbp_config['name']} (ACTIF)")
    
    # Afficher stratégies
    strategies = gbp_config.get('strategies', {})
    active_strategies = [k for k, v in strategies.items() 
                        if v and k not in ['force_short_only', 'force_long_only']]
    
    print(f"\n📌 Stratégies Actives:")
    for strat in active_strategies:
        print(f"   ✓ {strat}")
    
    # Paramètres risk
    print(f"\n💰 Risk Management:")
    print(f"   Lot: {config['risk']['fixed_lot_size']}")
    print(f"   Max Daily Trades: {config['risk']['max_daily_trades']}")
    print(f"   Max Trades/Session: {config['risk'].get('max_trades_per_session', 'N/A')}")
    print(f"   Max Daily Loss: {config['risk']['max_daily_loss']}%")
    
    print(f"\n🎯 Confluence:")
    print(f"   Required: {gbp_config.get('confluence_required', 'N/A')}")
    print(f"   Min Confidence: {gbp_config.get('min_confidence', 'N/A')}%")
    
    print("\n" + "="*75)
    print("🔄 LANCEMENT DU BACKTEST...")
    print("="*75 + "\n")
    print("⏳ Temps estimé: 2-5 minutes pour ~3 mois de données")
    print("   (Processing ~5,000-10,000 bougies M15)\n")
    
    # Import backtest engine
    try:
        from backtest.backtester import BacktestConfig, BacktestEngine
    except ImportError as e:
        print(f"❌ ERROR: Import backtest engine failed: {e}")
        return 1
    
    # Configuration backtest
    backtest_config = BacktestConfig(
        symbols=["GBPUSDm"],
        start_date=df['time'].min(),
        end_date=df['time'].max(),
        initial_capital=1000.0,
        data_dir=Path("data")
    )
    
    # Lancer
    try:
        engine = BacktestEngine(backtest_config, config)
        results = engine.run()
    except Exception as e:
        logger.exception("Backtest failed")
        print(f"\n❌ ERROR: Backtest échoué: {e}")
        print("\nVérifiez logs/backtest.log pour détails")
        return 1
    
    # Afficher résultats
    print("\n" + "="*75)
    print("📊 RÉSULTATS BACKTEST - GBPUSDm")
    print("="*75 + "\n")
    
    # Période
    print(f"📅 Période Testée:")
    print(f"   Du: {backtest_config.start_date.date()}")
    print(f"   Au: {backtest_config.end_date.date()}")
    print(f"   Durée: {(backtest_config.end_date - backtest_config.start_date).days} jours")
    
    # Capital
    print(f"\n💰 ÉVOLUTION CAPITAL:")
    print(f"   Capital Initial:  ${backtest_config.initial_capital:,.2f}")
    print(f"   Capital Final:    ${results['final_capital']:,.2f}")
    total_pnl = results['total_profit']
    pnl_color = "+" if total_pnl >= 0 else ""
    print(f"   P&L Total:        {pnl_color}${total_pnl:,.2f}")
    roi_color = "+" if results['roi'] >= 0 else ""
    print(f"   ROI:              {roi_color}{results['roi']:.2f}%")
    
    # Trades
    print(f"\n📈 STATISTIQUES TRADES:")
    print(f"   Total Trades:     {results['total_trades']}")
    print(f"   Gagnants:         {results['winning_trades']} ({results['win_rate']:.1f}%)")
    print(f"   Perdants:         {results['losing_trades']}")
    print(f"   Break-even:       {results.get('breakeven_trades', 0)}")
    
    # Performance
    print(f"\n🎯 MÉTRIQUES PERFORMANCE:")
    wr_status = "✅" if results['win_rate'] >= 55 else "⚠️" if results['win_rate'] >= 50 else "❌"
    print(f"   Win Rate:         {results['win_rate']:.2f}% {wr_status}")
    
    pf_status = "✅" if results['profit_factor'] >= 1.3 else "⚠️" if results['profit_factor'] >= 1.0 else "❌"
    print(f"   Profit Factor:    {results['profit_factor']:.3f} {pf_status}")
    
    dd_status = "✅" if results['max_drawdown'] <= 12 else "⚠️" if results['max_drawdown'] <= 15 else "❌"
    print(f"   Max Drawdown:     {results['max_drawdown']:.2f}% {dd_status}")
    
    sr_status = "✅" if results['sharpe_ratio'] >= 0.9 else "⚠️" if results['sharpe_ratio'] >= 0.5 else "❌"
    print(f"   Sharpe Ratio:     {results['sharpe_ratio']:.3f} {sr_status}")
    
    # Moyennes
    if results.get('avg_win'):
        print(f"\n💵 MOYENNES PAR TRADE:")
        print(f"   Gain Moyen:       ${results['avg_win']:,.2f}")
        print(f"   Perte Moyenne:    ${results.get('avg_loss', 0):,.2f}")
        print(f"   Plus Gros Gain:   ${results.get('largest_win', 0):,.2f}")
        print(f"   Plus Grosse Perte:${results.get('largest_loss', 0):,.2f}")
    
    # Évaluation
    print(f"\n" + "="*75)
    print("🎓 ÉVALUATION SYSTÈME:")
    print("="*75 + "\n")
    
    score = 0
    recommendations = []
    
    # Score Win Rate
    if results['win_rate'] >= 60:
        print("   ✅ Win Rate: EXCELLENT (≥60%)")
        score += 3
    elif results['win_rate'] >= 55:
        print("   ✅ Win Rate: BON (55-60%)")
        score += 2
    elif results['win_rate'] >= 50:
        print("   ⚠️  Win Rate: ACCEPTABLE (50-55%)")
        score += 1
        recommendations.append("Augmenter min_confidence à 80%")
    else:
        print("   ❌ Win Rate: FAIBLE (<50%)")
        recommendations.append("URGENT: Augmenter confluence_required à 3")
        recommendations.append("URGENT: Augmenter min_confidence à 85%")
    
    # Score Profit Factor
    if results['profit_factor'] >= 1.5:
        print("   ✅ Profit Factor: EXCELLENT (≥1.5)")
        score += 3
    elif results['profit_factor'] >= 1.3:
        print("   ✅ Profit Factor: BON (1.3-1.5)")
        score += 2
    elif results['profit_factor'] >= 1.0:
        print("   ⚠️  Profit Factor: ACCEPTABLE (1.0-1.3)")
        score += 1
        recommendations.append("Optimiser stratégies ou ajuster TP/SL")
    else:
        print("   ❌ Profit Factor: PERDANT (<1.0)")
        recommendations.append("URGENT: Système non profitable - Revoir config")
    
    # Score Drawdown
    if results['max_drawdown'] <= 10:
        print("   ✅ Max Drawdown: EXCELLENT (≤10%)")
        score += 2
    elif results['max_drawdown'] <= 12:
        print("   ✅ Max Drawdown: BON (10-12%)")
        score += 1
    elif results['max_drawdown'] <= 15:
        print("   ⚠️  Max Drawdown: ACCEPTABLE (12-15%)")
        recommendations.append("Réduire max_open_trades à 1")
    else:
        print("   ❌ Max Drawdown: RISQUE ÉLEVÉ (>15%)")
        recommendations.append("URGENT: Réduire lot size et max daily loss")
    
    # Score global
    max_score = 8
    print(f"\n   Score Global: {score}/{max_score} ({(score/max_score)*100:.0f}%)")
    
    if score >= 7:
        print("   🏆 Status: EXCELLENT - Prêt pour Demo!")
    elif score >= 5:
        print("   ⚠️  Status: BON - Optimisations mineures recommandées")
    elif score >= 3:
        print("   ⚠️  Status: ACCEPTABLE - Optimisations nécessaires")
    else:
        print("   ❌ Status: INSUFFISANT - Corrections majeures requises")
    
    # Recommandations
    if recommendations:
        print(f"\n📝 RECOMMANDATIONS:")
        for i, rec in enumerate(recommendations, 1):
            print(f"   {i}. {rec}")
    
    # Sauvegarder
    results_dir = Path("backtest/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    results_file = results_dir / f"backtest_gbpusd_pro_{timestamp}.csv"
    
    results_df = pd.DataFrame([results])
    results_df.to_csv(results_file, index=False)
    
    print(f"\n" + "="*75)
    print(f"💾 FICHIERS SAUVEGARDÉS:")
    print("="*75)
    print(f"   Résultats: {results_file}")
    print(f"   Logs: logs/backtest.log")
    
    # Prochaines étapes
    print(f"\n" + "="*75)
    print("📌 PROCHAINES ÉTAPES:")
    print("="*75 + "\n")
    
    if score >= 7:
        print("   ✅ 1. Résultats excellents!")
        print("   ✅ 2. Lancer walk-forward validation:")
        print("         python backtest/walk_forward.py --symbol GBPUSDm")
        print("   ✅ 3. Si validation OK, démarrer demo:")
        print("         python main.py --mode demo")
    elif score >= 5:
        print("   ⚠️  1. Appliquer recommandations ci-dessus")
        print("   ⚠️  2. Re-lancer ce backtest")
        print("   ⚠️  3. Si score ≥ 7/8, passer à walk-forward")
    else:
        print("   ❌ 1. Lire CONFIG_OPTIMISATION_PRO.md")
        print("   ❌ 2. Appliquer corrections critiques")
        print("   ❌ 3. Re-lancer ce backtest")
        print("   ❌ 4. Viser score minimum 6/8")
    
    print("\n" + "="*75 + "\n")
    
    return 0 if score >= 5 else 1

if __name__ == "__main__":
    exit(run_gbpusd_backtest())
