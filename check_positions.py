"""
POSITION INSPECTOR
Analyse les positions ouvertes pour vérifier leur conformité avec la stratégie SMC actuelle.
"""
import sys
import time
from pathlib import Path
import yaml
from loguru import logger
import MetaTrader5 as mt5
import pandas as pd

# Ajouter le répertoire racine au path
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from broker.mt5_connector import MT5Connector
from strategy.smc_strategy import SMCStrategy

def check_positions():
    # Charger la config
    with open("config/settings.yaml", 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
        
    # Connexion MT5
    connector = MT5Connector(config)
    if not connector.connect():
        logger.error("Impossible de se connecter à MT5")
        return

    # Récupérer les positions
    positions = mt5.positions_get()
    
    if not positions:
        print("\n[!] AUCUNE POSITION OUVERTE")
        return

    print(f"\n[INFO] ANALYSE DES {len(positions)} POSITIONS OUVERTES")
    print("=" * 60)
    
    strategy = SMCStrategy(config)
    
    for pos in positions:
        symbol = pos.symbol
        ticket = pos.ticket
        type_str = "BUY" if pos.type == 0 else "SELL"
        profit = pos.profit
        entry = pos.price_open
        
        print(f"\n[POS] #{ticket} | {symbol} | {type_str} @ {entry:.5f} | P&L: ${profit:.2f}")
        print("-" * 60)
        
        # Récupérer données pour analyse
        # On a besoin de M15 (LTF) et D1 (HTF)
        rates_ltf = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 500)
        rates_htf = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 100)
        
        if rates_ltf is None or rates_htf is None:
            print("   [x] Erreur récupération données historiques")
            continue
            
        df_ltf = pd.DataFrame(rates_ltf)
        df_ltf['time'] = pd.to_datetime(df_ltf['time'], unit='s')
        df_ltf.set_index('time', inplace=True)
        df_ltf.rename(columns={'tick_volume': 'volume'}, inplace=True)
        
        df_htf = pd.DataFrame(rates_htf)
        df_htf['time'] = pd.to_datetime(df_htf['time'], unit='s')
        df_htf.set_index('time', inplace=True)
        df_htf.rename(columns={'tick_volume': 'volume'}, inplace=True)
        
        # Analyse SMC
        print("   [...] Analyse SMC en cours...")
        analysis = strategy.analyze(df_ltf, df_htf, symbol=symbol)
        
        # Comparaison
        trend = analysis.get('trend', 'NEUTRAL')
        bias = analysis.get('bias', 'NEUTRAL')
        structure = analysis.get('structure', {})
        
        # Affichage du diagnostic
        print(f"   [DATA] Contexte Marché (M15):")
        print(f"      Trend: {trend}")
        print(f"      Bias:  {bias}")
        
        if structure:
             last_bos = structure.get('last_bos')
             if last_bos:
                 print(f"      Last BOS: {last_bos.type} (Bar -{getattr(last_bos, 'index', '?')})")
        
        # Verdict
        is_aligned = False
        if type_str == "BUY" and ("BULLISH" in str(bias).upper() or "BULLISH" in str(trend).upper()):
            is_aligned = True
        elif type_str == "SELL" and ("BEARISH" in str(bias).upper() or "BEARISH" in str(trend).upper()):
             is_aligned = True
             
        status_icon = "[OK]" if is_aligned else "[WARN]"
        print(f"   {status_icon} Verdict: La position est {'ALIGNEE' if is_aligned else 'CONTRE-TENDANCE'} avec l'analyse actuelle.")
        
        # Vérifier si on est dans une zone d'intérêt
        pd_zone = analysis.get('pd_zone')
        if pd_zone:
            print(f"      Zone Prix: {pd_zone.current_zone.value} ({pd_zone.current_percentage:.1f}%)")
            
    print("\n" + "=" * 60)
    mt5.shutdown()

if __name__ == "__main__":
    check_positions()
