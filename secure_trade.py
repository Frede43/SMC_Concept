
import MetaTrader5 as mt5
import sys

def secure_eurusd():
    if not mt5.initialize():
        print("Erreur initialisation MT5")
        return

    ticket = 2163684814
    positions = mt5.positions_get(ticket=ticket)
    
    if not positions:
        print(f"Position #{ticket} non trouvée.")
        return
        
    p = positions[0]
    entry = p.price_open
    tp = p.tp
    
    # Nouveau SL à Entrée + 1 pip (0.0001)
    new_sl = entry + 0.0001
    
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl": new_sl,
        "tp": tp
    }
    
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"✅ SUCCÈS : Position #{ticket} sécurisée à {new_sl:.5f} (BE +1 pip)")
    else:
        print(f"❌ ÉCHEC : {result.comment} (Code: {result.retcode})")

    mt5.shutdown()

if __name__ == "__main__":
    secure_eurusd()
