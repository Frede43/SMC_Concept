"""
Full Backtest 2025 - Validation Annuelle
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import pandas as pd
from loguru import logger
import yaml

# ✅ FIX CRASH EMOJI WINDOWS
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from backtest.backtester import BacktestConfig, BacktestEngine

def run_2025_backtest():
    print("\n" + "="*70)
    print("📅 BACKTEST COMPLET ANNÉE 2025")
    print("="*70)
    
    # Charger configuration
    config_path = ROOT_DIR / 'config' / 'settings.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    data_dir = ROOT_DIR / 'backtest' / 'data'
    target_tf = config.get('timeframes', {}).get('ltf', 'M15')
    print(f"🎯 Timeframe: {target_tf}")
    
    available_symbols = []
    # US30m exclu pour l'instant (focus Forex/Gold stable)
    test_symbols = ['GBPUSDm', 'EURUSDm', 'XAUUSDm', 'BTCUSDm'] 
    
    for symbol in test_symbols:
        # Fichiers M15 source (couvrent 2024-2026 selon le nom)
        m15_pkl = data_dir / f"{symbol}_M15_2024-01-01_2024-12-31.pkl" # Nom a adapter si besoin
        # On va chercher plutôt le CSV large s'il existe
        csv_full = data_dir / f"{symbol}_M15_2024-2026.csv"
        
        target_pkl = data_dir / f"{symbol}_{target_tf}_2025_FULL.pkl"
        
        if target_pkl.exists():
             print(f"  ✅ {symbol}: Cache 2025 {target_tf} trouvé")
             available_symbols.append(symbol)
        elif csv_full.exists():
            print(f"  ⚡ {symbol}: Génération Data 2025 depuis CSV...")
            try:
                df = pd.read_csv(csv_full)
                df['time'] = pd.to_datetime(df['time'])
                df.set_index('time', inplace=True)
                
                # Normaliser nom colonne volume (MT5 CSV utilise souvent tick_volume)
                if 'tick_volume' in df.columns:
                    df = df.rename(columns={'tick_volume': 'volume'})
                elif 'real_volume' in df.columns:
                    df = df.rename(columns={'real_volume': 'volume'})
                
                # Filtrer 2025
                df_2025 = df.loc['2025-01-01':'2025-12-31']
                
                if len(df_2025) == 0:
                    print(f"     ❌ Pas de données pour 2025 dans le CSV!")
                    continue
                
                # Resample si nécessaire
                if target_tf == 'H1':
                    df_resampled = df_2025.resample('1h').agg({
                        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
                    }).dropna()
                else:
                    df_resampled = df_2025 # M15 natif
                
                with open(target_pkl, 'wb') as f:
                    import pickle
                    pickle.dump(df_resampled, f)
                
                print(f"     ✅ Généré: {len(df_resampled)} bougies")
                available_symbols.append(symbol)
            except Exception as e:
                print(f"     ❌ Erreur extraction 2025: {e}")
        else:
             # Fallback sur le PKL existant (qui s'arrête peut-être fin 2024? On checke)
             if m15_pkl.exists():
                 print(f"  ⚠️ {symbol}: Tentative utilisation PKL existant (vérifier dates)")
                 available_symbols.append(symbol)
             else:
                 print(f"  ❌ {symbol}: Données introuvables")

    if not available_symbols:
        print("❌ Echec: Aucune donnée 2025.")
        return

    # Config 2025
    backtest_config = BacktestConfig(
        symbols=available_symbols,
        start_date=datetime(2025, 1, 1),
        end_date=datetime(2025, 12, 31),
        initial_capital=10000.0,
        data_dir=data_dir
    )
    
    print("\n🔄 Lancement Moteur 2025...")
    try:
        engine = BacktestEngine(backtest_config, config.get('smc', {}))
        engine.data_manager.use_mt5 = False
        results = engine.run()
        
        # Sauvegarde résultats
        res_file = ROOT_DIR / 'backtest' / 'results' / '2025_full_results.json'
        res_file.parent.mkdir(parents=True, exist_ok=True)
        import json
        with open(res_file, 'w') as f:
            # Sérialisation simple pour éviter erreur Object
            json.dump(results, f, default=str, indent=2)
        print(f"\n💾 Résultats sauvegardés: {res_file}")
        
    except Exception as e:
        logger.exception("Crash Backtest")
        print(f"❌ Erreur: {e}")

if __name__ == "__main__":
    run_2025_backtest()
