import MetaTrader5 as mt5
import time

def force_close_friday():
    print("--- FORCE CLOSE FRIDAY SAFETY ---", flush=True)
    
    if not mt5.initialize():
        print(f"[ERREUR] Connexion MT5: {mt5.last_error()}", flush=True)
        return

    positions = mt5.positions_get()
    
    if positions is None or len(positions) == 0:
        print("Aucune position ouverte.", flush=True)
        mt5.shutdown()
        return

    print(f"Positions trouvées: {len(positions)}", flush=True)
    
    for pos in positions:
        symbol = pos.symbol
        ticket = pos.ticket
        profit = pos.profit
        
        # LOGIQUE DE FILTRE : On garde les CRYPTOS (BTC, ETH, etc.)
        # On suppose que is_crypto n'est pas dispo ici, on filtre par nom commun
        is_crypto = "BTC" in symbol or "ETH" in symbol or "LTC" in symbol
        
        if is_crypto:
            print(f"🔒 GARDÉ: {symbol} #{ticket} (Crypto - Week-end OK)", flush=True)
            continue
            
        # FERMETURE DU RESTE (Forex/Or)
        print(f"🛑 FERMETURE: {symbol} #{ticket} (Profit: ${profit:.2f}) ...", flush=True)
        
        # Créer la requête de clôture
        tick = mt5.symbol_info_tick(symbol)
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": symbol,
            "volume": pos.volume,
            "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY, # Inverse du type actuel
            "price": tick.bid if pos.type == 0 else tick.ask,
            "deviation": 20,
            "magic": 234000,
            "comment": "Friday Force Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"   [ECHEC] Erreur fermeture: {result.comment}", flush=True)
        else:
            print(f"   [OK] Position fermée.", flush=True)
            
    mt5.shutdown()
    print("--- NETTOYAGE TERMINÉ ---", flush=True)

if __name__ == "__main__":
    force_close_friday()
