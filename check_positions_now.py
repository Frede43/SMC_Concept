import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime

def print_positions():
    # Attempt to initialize, assuming the terminal is already running as per previous context
    if not mt5.initialize():
        print(f"❌ Échec de l'initialisation de MT5, erreur: {mt5.last_error()}")
        return

    positions = mt5.positions_get()

    if positions is None:
        print(f"❌ Impossible de récupérer les positions, erreur: {mt5.last_error()}")
    elif len(positions) == 0:
        print("ℹ️ Aucune position ouverte actuellement.")
    else:
        print(f"\nPOSITIONS EN COURS ({len(positions)}):")
        print("=" * 60)
        
        total_profit = 0.0
        
        for pos in positions:
            symbol = pos.symbol
            # 0 is BUY, 1 is SELL usually in MT5
            type_str = "BUY" if pos.type == 0 else "SELL"
            volume = pos.volume
            open_price = pos.price_open
            current_price = pos.price_current
            profit = pos.profit
            swap = pos.swap
            comment = pos.comment
            ticket = pos.ticket
            sl = pos.sl
            tp = pos.tp
            
            total_profit += profit + swap
            
            status_icon = "[PROFIT]" if (profit + swap) >= 0 else "[LOSS]"
            
            print(f"{status_icon} {symbol} | {type_str} | {volume} lots | Ticket: {ticket}")
            print(f"   Prix: {open_price:.5f} -> {current_price:.5f}")
            print(f"   SL: {sl:.5f} | TP: {tp:.5f}")
            print(f"   P&L: ${profit:.2f} (Swap: ${swap:.2f})")
            if comment:
                print(f"   Raison: {comment}")
            print("-" * 60)
            
        print(f"TOTAL P&L LATENT: ${total_profit:.2f}")
        print("=" * 60)

    mt5.shutdown()

if __name__ == "__main__":
    print_positions()
