"""
Script de profilage pour mesurer la vitesse d'une seule itération SMC.
Permet de diagnostiquer pourquoi le backtest est bloqué à 0%.

Usage: python profile_one_iteration.py
"""

import sys
import os
import time
import yaml
import cProfile
import pstats
import io
import pandas as pd
from pathlib import Path

# ✅ FIX CRASH EMOJI WINDOWS
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass

# Add project root
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from strategy.smc_strategy import SMCStrategy
from backtest.backtester import BacktestConfig, DataManager

def profile_iteration():
    print("\n" + "="*70)
    print("⏱️ PROFILING UNE ITÉRATION SMC")
    print("="*70 + "\n")
    
    # 1. Charger Config
    print("⚙️ Chargement configuration...")
    config_path = ROOT_DIR / 'config' / 'settings.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # Désactiver logs
    from loguru import logger
    logger.remove()
    
    # 2. Charger Données (Pack M15)
    print("📂 Chargement données GBPUSDm...")
    data_dir = ROOT_DIR / 'backtest' / 'data'
    pkl_file = data_dir / "GBPUSDm_M15_2024-01-01_2024-12-31.pkl"
    
    if not pkl_file.exists():
        print("❌ Fichier de données manquant. Lancez prepare_backtest_data.py d'abord.")
        return
        
    df_ltf = pd.read_pickle(pkl_file)
    print(f"✅ Données chargées: {len(df_ltf)} bougies")
    
    # Préparer un slice de 1000 bougies
    lookback = 1000
    if len(df_ltf) < lookback:
        df_slice = df_ltf
    else:
        # Prendre un slice au milieu
        mid = len(df_ltf) // 2
        df_slice = df_ltf.iloc[mid-lookback : mid]
    
    print(f"📊 Slice pour analyse: {len(df_slice)} bougies")
    
    # 3. Initialiser Stratégie
    print("🔧 Initialisation stratégie...")
    strategy = SMCStrategy(config)
    
    # 4. Mesure Temps ANALYSE
    print("\n🚀 Lancement ANALYSE (1 itération)...")
    
    start_time = time.time()
    
    # Profiling complet
    pr = cProfile.Profile()
    pr.enable()
    
    # === LA FONCTION LOURDE ===
    analysis = strategy.analyze(df_slice, symbol="GBPUSDm")
    # ==========================
    
    pr.disable()
    end_time = time.time()
    
    duration = end_time - start_time
    candles_per_sec = 1 / duration if duration > 0 else 0
    total_estimated_time_hours = (25000 * duration) / 3600
    
    print("\n" + "="*70)
    print(f"⏱️ RÉSULTATS RAPIDES:")
    print(f"  Temps par itération: {duration:.4f} secondes")
    print(f"  Vitesse: {candles_per_sec:.2f} itérations/sec")
    print(f"  Temps estimé pour 25k bougies: {total_estimated_time_hours:.2f} HEURES")
    print("="*70)
    
    # 5. Afficher Details Profiling
    print("\n🔍 DÉTAILS PROFILING (Top 20 fonctions les plus lentes):")
    s = io.StringIO()
    sortby = 'cumulative'
    ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
    ps.print_stats(20)
    print(s.getvalue())

if __name__ == "__main__":
    profile_iteration()
