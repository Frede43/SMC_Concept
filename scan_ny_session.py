"""
NY SESSION SCANNER
Scanne le marché pour identifier les opportunités de la session de New York.
"""
import sys
from pathlib import Path
import yaml
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
from loguru import logger

# Ajouter le répertoire racine au path
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from broker.mt5_connector import MT5Connector
from strategy.smc_strategy import SMCStrategy

def market_scan():
    # Charger la config
    with open("config/settings.yaml", 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
        
    # Connexion MT5
    connector = MT5Connector(config)
    if not connector.connect():
        logger.error("Impossible de se connecter à MT5")
        return

    # Initialiser la stratégie
    strategy = SMCStrategy(config)
    
    symbols = [s['name'] for s in config['symbols']]
    
    print(f"\n[SCAN] SCAN DES OPPORTUNITES - NY SESSION ({datetime.now().strftime('%H:%M:%S')})")
    print("=" * 100)
    print(f"{'Symbole':<12} | {'Biais LTF':<10} | {'Biais HTF':<10} | {'Zone P/D':<10} | {'Setup Potentiel'}")
    print("-" * 100)

    for symbol in symbols:
        try:
            # Récupérer données LTF (M15)
            df_ltf = connector.get_ohlc(symbol, 'M15', 200)
            # Récupérer données HTF (D1)
            df_htf = connector.get_ohlc(symbol, 'D1', 100)
            
            if df_ltf is None or df_htf is None:
                continue

            # Analyser
            analysis = strategy.analyze(df_ltf, df_htf, symbol=symbol)
            
            bias_ltf = analysis.get('combined_bias', 'NEUTRAL')
            bias_htf = str(analysis.get('htf_bias', 'NEUTRAL'))
            
            # Zone P/D
            pd_zone = analysis.get('pd_zone', {})
            zone_name = "N/A"
            if hasattr(pd_zone, 'current_zone'):
                zone_name = pd_zone.current_zone.value.upper()
            
            # Détecter setups spécifiques
            setup = "Aucun"
            
            # Check Sweeps
            sweeps = analysis.get('sweeps', [])
            if sweeps:
                last_sweep = sweeps[-1]
                setup = f"SWEEP {last_sweep.type.value.upper()}"
            
            # Check iFVG
            ifvg = analysis.get('ifvg', {})
            if ifvg.get('signal') != 'NEUTRAL':
                setup = f"iFVG {ifvg.get('signal')} ({ifvg.get('confidence')}%)"

            # Displacement (Expert Check)
            is_displaced = False
            for i in range(1, 4):
                if strategy.market_structure._is_displaced(df_ltf, len(df_ltf)-i):
                    setup += " + DISPLACEMENT"
                    break

            # Couleur/Formatage rapide
            print(f"{symbol:<12} | {bias_ltf:<10} | {bias_htf:<10} | {zone_name:<10} | {setup}")

        except Exception as e:
            logger.error(f"Erreur sur {symbol}: {e}")

    print("-" * 100)
    print("[INFO] Biais directionnel global et confluences calculés selon SMC Strategy v3.2")
    print("=" * 100)
    
    mt5.shutdown()

if __name__ == "__main__":
    market_scan()
