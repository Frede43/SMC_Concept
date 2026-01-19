
import sys
import os
import time
import MetaTrader5 as mt5
from datetime import datetime

# Ajouter la racine au path pour les imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker.mt5_connector import MT5Connector

# Configuration minimale (credentials dans .env)
CONFIG = {
    'mt5': {
        'login': int(os.getenv('MT5_LOGIN', 0)),
        'password': os.getenv('MT5_PASSWORD', ''),
        'server': os.getenv('MT5_SERVER', ''),
        'path': os.getenv('MT5_PATH', r"C:\Program Files\MetaTrader 5\terminal64.exe")
    }
}

def force_close_friday():
    print("\n🚨 EMERGENCY FORCE CLOSE FRIDAY 🚨")
    print("==================================")
    
    connector = MT5Connector(CONFIG)
    if not connector.connect():
        print("❌ Echec connexion MT5")
        return

    # 1. Récupérer positions
    positions = connector.get_positions()
    if not positions:
        print("✅ Aucune position ouverte. Bon week-end!")
        connector.disconnect()
        return

    print(f"🔍 Scan de {len(positions)} positions...")
    
    for pos in positions:
        symbol = pos['symbol']
        ticket = pos['ticket']
        profit = pos['profit']
        
        # 2. Filtrer Crypto (On garde)
        if "BTC" in symbol or "ETH" in symbol or "CRYPTO" in symbol:
            print(f"🪙 [KEEP] {symbol} #{ticket} (Crypto 24/7)")
            continue
            
        # 3. Fermer les autres (Forex/Indices/Gold)
        print(f"📉 [CLOSING] {symbol} #{ticket} | P/L: ${profit:.2f} ...")
        
        # Préparer la requête de fermeture
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            print(f"   ❌ Erreur prix pour {symbol}")
            continue
            
        close_price = tick.bid if pos['type'] == 'BUY' else tick.ask
        type_order = mt5.ORDER_TYPE_SELL if pos['type'] == 'BUY' else mt5.ORDER_TYPE_BUY
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": symbol,
            "volume": pos['volume'],
            "type": type_order,
            "price": close_price,
            "deviation": 20,
            "magic": 0,
            "comment": "Force Close Friday",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        # Exécuter
        result = mt5.order_send(request)
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"   ❌ Echec fermeture: {result.comment}")
        else:
            print(f"   ✅ FERMÉ à {result.price} (Deal: {result.deal})")
            
    print("\n🏁 Opération terminée.")
    connector.disconnect()

if __name__ == "__main__":
    force_close_friday()
