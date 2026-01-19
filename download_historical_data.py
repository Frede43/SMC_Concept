"""
Script Helper - Téléchargement Données Historiques pour Backtests
Télécharge 2 ans de données (2024-2026) pour tous les symboles

Author: Antigravity AI
Date: 2026-01-11
"""

import MetaTrader5 as mt5
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from loguru import logger

# Configuration
SYMBOLS = ['GBPUSDm', 'EURUSDm', 'BTCUSDm', 'XAUUSDm', 'USDJPYm', 'US30m', 'USTECm']
TIMEFRAMES = {
    'M15': mt5.TIMEFRAME_M15,
    'H4': mt5.TIMEFRAME_H4,
    'D1': mt5.TIMEFRAME_D1
}

# Période: 2 ans
END_DATE = datetime.now()
START_DATE = END_DATE - timedelta(days=730)

# Répertoire de sortie
DATA_DIR = Path('backtest/data')
DATA_DIR.mkdir(parents=True, exist_ok=True)

logger.add('logs/data_download.log', rotation='10 MB')

def download_data():
    """Télécharge les données historiques pour backtests"""
    
    print("\n" + "="*70)
    print("📥 TÉLÉCHARGEMENT DONNÉES HISTORIQUES - 2 ANS")
    print("="*70)
    print(f"\nPériode: {START_DATE.date()} → {END_DATE.date()}")
    print(f"Symboles: {len(SYMBOLS)}")
    print(f"Timeframes: {list(TIMEFRAMES.keys())}")
    print(f"Destination: {DATA_DIR}")
    
    # Initialiser MT5
    if not mt5.initialize():
        logger.error("Failed to initialize MT5")
        print("\n❌ ERREUR: Impossible d'initialiser MT5")
        print("Vérifiez que MT5 est installé et lancé")
        return False
    
    logger.info(f"MT5 initialized: {mt5.terminal_info().company}")
    
    total_files = len(SYMBOLS) * len(TIMEFRAMES)
    completed = 0
    
    # Télécharger chaque symbole et timeframe
    for symbol in SYMBOLS:
        print(f"\n📊 Traitement: {symbol}")
        print("-" * 70)
        
        for tf_name, tf_value in TIMEFRAMES.items():
            try:
                logger.info(f"Downloading {symbol} {tf_name}...")
                
                # Télécharger depuis MT5
                rates = mt5.copy_rates_range(symbol, tf_value, START_DATE, END_DATE)
                
                if rates is None or len(rates) == 0:
                    logger.warning(f"No data for {symbol} {tf_name}")
                    print(f"  ⚠️ {tf_name}: Pas de données")
                    continue
                
                # Convertir en DataFrame
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s')
                
                # Sauvegarder CSV
                filename = f"{symbol}_{tf_name}_2024-2026.csv"
                filepath = DATA_DIR / filename
                df.to_csv(filepath, index=False)
                
                completed += 1
                progress = (completed / total_files) * 100
                
                logger.info(f"Saved {filename}: {len(df)} candles")
                print(f"  ✅ {tf_name}: {len(df):,} bougies → {filename}")
                print(f"     Progression: {progress:.0f}% ({completed}/{total_files})")
                
            except Exception as e:
                logger.error(f"Error downloading {symbol} {tf_name}: {e}")
                print(f"  ❌ {tf_name}: Erreur - {e}")
    
    mt5.shutdown()
    
    print("\n" + "="*70)
    print("✅ TÉLÉCHARGEMENT TERMINÉ")
    print("="*70)
    print(f"\nFichiers créés: {completed}/{total_files}")
    print(f"Répertoire: {DATA_DIR.absolute()}")
    
    # Liste des fichiers
    files = sorted(DATA_DIR.glob('*.csv'))
    if files:
        print(f"\n📁 Fichiers disponibles:")
        for f in files:
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"   • {f.name} ({size_mb:.1f} MB)")
    
    print("\n🎯 PROCHAINE ÉTAPE:")
    print("   python run_backtest_2024.py")
    
    return True


if __name__ == "__main__":
    try:
        success = download_data()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️ Téléchargement interrompu par l'utilisateur")
        exit(1)
    except Exception as e:
        logger.exception("Fatal error")
        print(f"\n❌ ERREUR FATALE: {e}")
        exit(1)
