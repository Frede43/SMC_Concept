import os
import sys
import cProfile
import pstats
from datetime import datetime
from backtest.backtester import run_backtest, print_summary

# Fix Windows encoding
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Configuration du backtest
SYMBOLS = ["EURUSDm", "GBPUSDm", "XAUUSDm"]
YEARS = 1
CAPITAL = 10000

def main():
    print(f">> Demarrage du backtest optimise sur {YEARS} an(s)...")
    print(">> Note: Le lookback a ete limite a 1000 bars pour une performance maximale.")
    
    # Créer un profileur
    profiler = cProfile.Profile()
    
    try:
        profiler.enable()
        
        # Lancer le backtest
        results = run_backtest(years=YEARS, symbols=SYMBOLS, capital=CAPITAL)
        
        profiler.disable()
        
        # Sauvegarder et afficher les stats du profilage
        stats = pstats.Stats(profiler).sort_stats('cumulative')
        stats.print_stats(30)  # Afficher les 30 fonctions les plus lentes
        
        print("\n>> Backtest termine avec succes.")
        
    except Exception as e:
        print(f">> Erreur pendant le backtest: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
