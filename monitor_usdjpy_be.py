
import os
import sys
import time
import pandas as pd
from pathlib import Path
from datetime import datetime

# Ajouter le dossier racine au path
sys.path.insert(0, str(Path(__file__).parent))

from utils.helpers import load_config
from broker.mt5_connector import MT5Connector

def monitor_usdjpy_be():
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    config = load_config("config/settings.yaml")
    mt5 = MT5Connector(config)
    if not mt5.connect():
        return

    symbol = "USDJPYm"
    be_trigger_r = config.get('risk', {}).get('management', {}).get('break_even_trigger', 1.5)
    
    print(f"\n🛡️ SURVEILLANCE BREAK-EVEN: {symbol}")
    print(f"Trigger BE: {be_trigger_r} R")
    
    while True:
        try:
            positions = mt5.get_positions(symbol=symbol)
            if not positions:
                print(f"❌ Plus de position ouverte sur {symbol}")
                break
            
            p = positions[0]
            ticket = p['ticket']
            entry = p['price_open']
            sl = p['sl']
            tp = p['tp']
            current_price = mt5.get_current_price(symbol)['bid']
            
            risk = abs(entry - sl)
            if risk == 0:
                print("⚠️ Risk nul (SL non défini?), monitoring impossible.")
                break
                
            trigger_pips = risk * be_trigger_r
            trigger_price = entry + trigger_pips if p['type'] == 'BUY' else entry - trigger_pips
            
            # Correction pour Pip Size sur JPY (0.01)
            pip_size = 0.01
            profit_pips = (current_price - entry) / pip_size if p['type'] == 'BUY' else (entry - current_price) / pip_size
            dist_to_trigger = (trigger_price - current_price) / pip_size if p['type'] == 'BUY' else (current_price - trigger_price) / pip_size
            dist_to_tp = (tp - current_price) / pip_size if p['type'] == 'BUY' else (current_price - tp) / pip_size

            print(f"[{datetime.now().strftime('%H:%M:%S')}] Prix: {current_price:.3f} | PnL: {profit_pips:.1f} pips | Distance BE: {dist_to_trigger:.1f} pips | Distance TP: {dist_to_tp:.1f} pips", flush=True)
            
            if (p['type'] == 'BUY' and current_price >= trigger_price) or (p['type'] == 'SELL' and current_price <= trigger_price):
                print(f"\n🎯 OBJECTIF BE ATTEINT ! Le bot devrait sécuriser le trade #{ticket} maintenant.")
                break
            
            if dist_to_tp <= 0:
                print(f"\n✅ TAKE PROFIT PROBABLEMENT ATTEINT (ou très proche) !")
                break
                
            time.sleep(20)
            
        except Exception as e:
            print(f"Erreur: {e}")
            time.sleep(20)

    mt5.disconnect()

if __name__ == "__main__":
    monitor_usdjpy_be()
