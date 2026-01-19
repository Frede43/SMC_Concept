
import sys
import os
import pandas as pd
from datetime import datetime

# Ajouter la racine au path pour les imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker.mt5_connector import MT5Connector
from loguru import logger

# Configuration minimale pour le connecteur (les vrais credentials sont dans .env)
CONFIG = {
    'mt5': {
        'login': int(os.getenv('MT5_LOGIN', 0)),
        'password': os.getenv('MT5_PASSWORD', ''),
        'server': os.getenv('MT5_SERVER', ''),
        'path': os.getenv('MT5_PATH', r"C:\Program Files\MetaTrader 5\terminal64.exe")
    }
}

def analyze_positions():
    connector = MT5Connector(CONFIG)
    
    # 1. Connexion
    if not connector.connect():
        print("❌ Impossible de se connecter à MT5. Vérifiez que MT5 est ouvert.")
        return

    # 2. Récupérer les positions
    positions = connector.get_positions()
    
    if not positions:
        print("\n✅ AUCUNE POSITION OUVERTE")
        connector.disconnect()
        return

    print(f"\n📊 RAPPORT POSITIONS EN COURS ({len(positions)})")
    print("=" * 80)
    print(f"{'TICKET':<12} | {'SYMBOL':<8} | {'TYPE':<5} | {'VOL':<5} | {'PRICE':<10} | {'SL':<10} | {'PROFIT ($)':<12} | {'DURATION':<10}")
    print("-" * 80)
    
    total_profit = 0.0
    total_volume = 0.0
    
    for pos in positions:
        # Calcul durée
        duration = datetime.now() - pos['time']
        duration_str = str(duration).split('.')[0] # HH:MM:SS
        
        # Style
        pnl_symbol = "🟢" if pos['profit'] >= 0 else "🔴"
        type_str = pos['type']
        
        print(f"{pos['ticket']:<12} | {pos['symbol']:<8} | {type_str:<5} | {pos['volume']:<5} | {pos['price_open']:<10.5f} | {pos['sl']:<10.5f} | {pnl_symbol} {pos['profit']:<8.2f} | {duration_str:<10}")
        
        total_profit += pos['profit']
        total_volume += pos['volume']

    print("-" * 80)
    print(f"💰 P/L TOTAL: {'🟢' if total_profit >= 0 else '🔴'} ${total_profit:.2f}")
    print(f"⚖️ VOLUME TOTAL: {total_volume:.2f} lots")
    
    # 3. Vérification des prix actuels pour voir la distance au SL
    print("\n🛡️ DISTANCE AU STOP LOSS")
    print("-" * 60)
    for pos in positions:
        current_data = connector.get_current_price(pos['symbol'])
        if not current_data: continue
        
        current_price = current_data['bid'] if pos['type'] == 'BUY' else current_data['ask']
        sl_price = pos['sl']
        open_price = pos['price_open']
        
        if sl_price > 0:
            if pos['type'] == 'BUY':
                dist_sl = (current_price - sl_price) 
                risk_dist = (open_price - sl_price)
            else:
                dist_sl = (sl_price - current_price)
                risk_dist = (sl_price - open_price)
            
            # Normaliser par point/pip
            symbol_info = connector.get_symbol_info(pos['symbol'])
            pip_val = symbol_info['point'] if symbol_info else 0.0001
            
            dist_pips = dist_sl / pip_val if pip_val > 0 else 0
            
            status = "safe"
            if dist_pips < 50: status = "DANGER ⚠️"
            if dist_pips < 0: status = "HIT? ❌"
            
            # % progression vers BE
            be_status = ""
            if pos['profit'] > 0:
                be_status = "✅ In Profit"
            
            print(f"[{pos['symbol']}] SL Distance: {dist_pips:.1f} pts ({status}) {be_status}")
    
    connector.disconnect()

if __name__ == "__main__":
    analyze_positions()
