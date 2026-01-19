
import os
import sys
import pandas as pd
import time
from pathlib import Path
from loguru import logger
from datetime import datetime

# Ajouter le dossier racine au path
sys.path.insert(0, str(Path(__file__).parent))

from utils.helpers import load_config
from broker.mt5_connector import MT5Connector
from core.market_structure import MarketStructure, StructureType, Trend

def monitor_m1_choch():
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

    # 1. Charger la config
    config = load_config("config/settings.yaml")
    
    # 2. Initialiser MT5
    mt5 = MT5Connector(config)
    if not mt5.connect():
        print("❌ Échec de connexion MT5")
        return

    symbol = "EURUSDm"
    print(f"\n📡 MODE ALERTE: Surveillance CHoCH Bullish M1 sur {symbol}")
    print(f"Biais recherché: Retournement après Sweep PDL/Asian Low")
    
    # 3. Initialiser le détecteur avec une sensibilité accrue pour le M1
    # swing_strength=3 (au lieu de 5) pour détecter les micro-structures
    structure_detector = MarketStructure(swing_strength=3, min_impulse_pips=1.0, displacement_multiplier=1.1)
    
    last_processed_idx = -1
    
    # On va boucler pendant environ 5 minutes (30 checks de 10s)
    for i in range(30):
        try:
            # Récupérer les données M1
            df = mt5.get_ohlc(symbol, "M1", count=150)
            if df is None or df.empty:
                time.sleep(10)
                continue
                
            current_price = df.iloc[-1]['close']
            
            # Analyser la structure
            analysis = structure_detector.analyze(df)
            
            # Chercher le dernier CHoCH
            last_choch = structure_detector.get_last_choch()
            
            # On vérifie si un nouveau CHoCH est apparu sur les 5 dernières bougies
            if last_choch and last_choch.break_index > (len(df) - 5):
                if last_choch.direction == Trend.BULLISH:
                    print(f"\n🚀 🔥🔥🔥 ALERTE CHoCH BULLISH CONFIRMÉ !!! 🔥🔥🔥")
                    print(f"Heure: {datetime.now().strftime('%H:%M:%S')}")
                    print(f"Prix de cassure: {last_choch.break_price:.5f}")
                    print(f"Prix actuel: {current_price:.5f}")
                    print(f"Action: Le retournement institutionnel commence probablement ICI.")
                    # On s'arrête si trouvé
                    break
            
            # Si pas de CHoCH, on check les Swing Highs non cassés pour voir la cible
            pending_highs = [sh for sh in analysis['swing_highs'] if not sh.broken]
            if pending_highs:
                target = pending_highs[-1]
                dist = (target.price - current_price) * 10000
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Prix: {current_price:.5f} | Prochain CHoCH si > {target.price:.5f} ({dist:.1f} pips)", flush=True)
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Prix: {current_price:.5f} | En attente de formation de structure High...", flush=True)

            time.sleep(10) # Attendre 10 secondes
            
        except Exception as e:
            print(f"Erreur monitoring: {e}")
            time.sleep(10)

    mt5.disconnect()
    print("\n🏁 Fin de la session de monitoring.")

if __name__ == "__main__":
    monitor_m1_choch()
