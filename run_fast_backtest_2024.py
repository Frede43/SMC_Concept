"""
Backtest Rapide 2024 - Utilise données pré-chargées
Version optimisée qui ne télécharge PAS depuis MT5

Usage: python run_fast_backtest_2024.py
"""

import sys
import os

# ✅ FIX CRASH EMOJI WINDOWS: Forcer l'encodage UTF-8 pour la console
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
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

def run_fast_backtest():
    """Lance le backtest en mode rapide avec données existantes"""
    
    print("\n" + "="*70)
    print("⚡ BACKTEST RAPIDE 2024 - MODE SPLASH (Novembre 2024)")
    print("="*70)
    print("\nPériode réduite pour validation rapide: 1er Novembre 2024 → 30 Novembre 2024")
    print("(Mois standard avec bon volume - évite faiblesse Décembre)\n")
    
    # Charger configuration
    config_path = ROOT_DIR / 'config' / 'settings.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # Vérifier quelles données sont disponibles
    data_dir = ROOT_DIR / 'backtest' / 'data'
    print("📂 Vérification des données disponibles...\n")
    
    available_symbols = []
    test_symbols = ['GBPUSDm', 'EURUSDm', 'XAUUSDm'] # US30m retiré (Data H1 instable)
    
    # Récupérer le timeframe demandé
    target_tf = config.get('timeframes', {}).get('ltf', 'M15')
    print(f"🎯 Timeframe Cible: {target_tf}")
    
    for symbol in test_symbols:
        # Fichiers M15 source
        m15_pkl = data_dir / f"{symbol}_M15_2024-01-01_2024-12-31.pkl"
        
        # Fichier Cible (ex: H1)
        target_pkl = data_dir / f"{symbol}_{target_tf}_2024-01-01_2024-12-31.pkl"
        
        if target_pkl.exists():
            print(f"  ✅ {symbol}: Données {target_tf} PKL trouvées ({target_pkl.stat().st_size / 1024 / 1024:.1f} MB)")
            available_symbols.append(symbol)
        elif m15_pkl.exists():
            print(f"  ⚡ {symbol}: Génération {target_tf} depuis M15...")
            try:
                import pickle
                with open(m15_pkl, 'rb') as f:
                    df_m15 = pickle.load(f)
                
                # Resampling
                rule = '1h' if target_tf == 'H1' else '15min'
                df_resampled = df_m15.resample(rule).agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }).dropna()
                
                # Sauvegarde H1
                with open(target_pkl, 'wb') as f:
                    pickle.dump(df_resampled, f)
                    
                print(f"     ✅ Conversion terminée: {len(df_resampled)} bougies {target_tf}")
                available_symbols.append(symbol)
            except Exception as e:
                 print(f"     ❌ Erreur conversion: {e}")
        else:
            print(f"  ❌ {symbol}: Données manquantes (Ni {target_tf} ni M15)")
    
    if not available_symbols:
        print("\n❌ Aucune donnée disponible!")
        return 1
    
    print(f"\n✅ {len(available_symbols)} symboles prêts pour {target_tf}: {', '.join(available_symbols)}\n")
    
    # Configuration backtest - PÉRIODE RÉDUITE
    backtest_config = BacktestConfig(
        symbols=available_symbols,
        start_date=datetime(2024, 11, 1),  # Début Novembre (Meilleur volume)
        end_date=datetime(2024, 11, 30),   # Fin Novembre
        initial_capital=10000.0,
        data_dir=data_dir
    )
    
    print("="*70)
    print("🔄 LANCEMENT BACKTEST...")
    print("="*70 + "\n")
    
    # Lancer backtest avec données existantes (use_mt5=False)
    try:
        engine = BacktestEngine(backtest_config, config.get('smc', {}))
        
        # Force use_mt5=False dans le DataManager
        engine.data_manager.use_mt5 = False
        
        print("⏳ Exécution en cours...\n")
        results = engine.run()
        
    except Exception as e:
        logger.exception("Backtest failed")
        print(f"\n❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
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
    
    # Métriques clés
    print(f"\n🎯 MÉTRIQUES CLÉS:")
    
    wr = results['win_rate']
    wr_status = "✅" if wr >= 60 else "⚠️" if wr >= 55 else "❌"
    print(f"  Win Rate:         {wr:.2f}% {wr_status}")
    
    pf = results['profit_factor']
    pf_status = "✅" if pf >= 1.5 else "⚠️" if pf >= 1.3 else "❌"
    print(f"  Profit Factor:    {pf:.3f} {pf_status}")
    
    dd = results['max_drawdown']
    dd_status = "✅" if dd <= 10 else "⚠️" if dd <= 15 else "❌"
    print(f"  Max Drawdown:     {dd:.2f}% {dd_status}")
    
    sr = results['sharpe_ratio']
    sr_status = "✅" if sr >= 1.0 else "⚠️" if sr >= 0.7 else "❌"
    print(f"  Sharpe Ratio:     {sr:.3f} {sr_status}")
    
    if results.get('avg_win'):
        print(f"\n💵 MOYENNES:")
        print(f"  Gain Moyen:       ${results['avg_win']:,.2f}")
        print(f"  Perte Moyenne:    ${results.get('avg_loss', 0):,.2f}")
    
    # Évaluation
    print(f"\n" + "="*70)
    print("🎓 ÉVALUATION:")
    print("="*70 + "\n")
    
    score = 0
    if wr >= 60: score += 1
    elif wr >= 55: score += 0.5
    
    if pf >= 1.5: score += 1
    elif pf >= 1.3: score += 0.5
    
    if dd <= 10: score += 1
    elif dd <= 15: score += 0.5
    
    if sr >= 1.0: score += 1
    elif sr >= 0.7: score += 0.5
    
    if results['total_trades'] >= 50: score += 1
    elif results['total_trades'] >= 30: score += 0.5
    
    score_pct = (score / 5) * 100
    print(f"  📊 Score Global: {score:.1f}/5 ({score_pct:.0f}%)")
    
    if score >= 4.5:
        print("\n🏆 DÉCISION: EXCELLENT - Stratégie validée!")
    elif score >= 3.5:
        print("\n⚠️ DÉCISION: BON - Quelques optimisations possibles")
    elif score >= 2.5:
        print("\n⚠️ DÉCISION: ACCEPTABLE - Optimisations requises")
    else:
        print("\n❌ DÉCISION: ÉCHEC - Revoir la stratégie")
    
    print("="*70 + "\n")
    
    # Sauvegarder
    results_dir = ROOT_DIR / 'backtest' / 'results' / '2024'
    results_dir.mkdir(parents=True, exist_ok=True)
    
    import json
    results_file = results_dir / 'fast_backtest_results.json'
    
    # Conversion des trades en dictionnaires sérialisables
    serialized_trades = []
    for t in results.get('trades', []):
        try:
            trade_dict = {
                'id': getattr(t, 'ticket', 0),
                'symbol': getattr(t, 'symbol', 'UNKNOWN'),
                'direction': str(getattr(t, 'direction', '')),
                'entry_time': getattr(t, 'entry_time', datetime.now()).isoformat(),
                'exit_time': getattr(t, 'exit_time', datetime.now()).isoformat(),
                'entry_price': float(getattr(t, 'entry_price', 0.0)),
                'exit_price': float(getattr(t, 'exit_price', 0.0)),
                'pnl': float(getattr(t, 'profit', 0.0)),
                'lot_size': float(getattr(t, 'lot_size', 0.0)),
                'result': 'WIN' if getattr(t, 'profit', 0) > 0 else 'LOSS'
            }
            serialized_trades.append(trade_dict)
        except Exception as e:
            print(f"⚠️ Erreur sérialisation trade: {e}")
            continue

    save_data = {
        'date': datetime.now().isoformat(),
        'symbols': available_symbols,
        'capital_initial': backtest_config.initial_capital,
        'capital_final': results['final_capital'],
        'total_pnl': results['total_pnl'],
        'roi': results['roi'],
        'total_trades': results['total_trades'],
        'win_rate': results['win_rate'],
        'profit_factor': results['profit_factor'],
        'max_drawdown': results['max_drawdown'],
        'sharpe_ratio': results['sharpe_ratio'],
        'score': score,
        'trades': serialized_trades
    }
    
    with open(results_file, 'w') as f:
        json.dump(save_data, f, indent=4)
    
    print(f"💾 Résultats sauvegardés: {results_file}\n")
    
    return 0 if score >= 2.5 else 1


if __name__ == "__main__":
    try:
        exit_code = run_fast_backtest()
        exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️ Backtest interrompu")
        exit(1)
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
