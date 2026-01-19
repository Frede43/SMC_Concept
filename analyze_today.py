import MetaTrader5 as mt5
from dotenv import load_dotenv
import os
import pandas as pd
from datetime import datetime, timedelta

load_dotenv()
if not mt5.initialize(): exit()
mt5.login(int(os.getenv('MT5_LOGIN')), password=os.getenv('MT5_PASSWORD'), server='Exness-MT5Trial9')

# Aujourd'hui minuit
from_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
to_date = datetime.now() + timedelta(days=1)

history = mt5.history_deals_get(from_date, to_date)

print(f"\n=== HISTORIQUE DU JOUR ({datetime.now().strftime('%d/%m/%Y')}) ===\n")

# --- 1. POSITIONS OUVERTES ---
positions = mt5.positions_get(symbol="GBPUSDm")
if positions is None or len(positions) == 0:
    print(">> Pas de positions ouvertes.")
else:
    print(f"--- POSITIONS OUVERTES ({len(positions)}) ---")
    for pos in positions:
        type_str = "BUY" if pos.type == 0 else "SELL"
        profit = pos.profit
        print(f"> {type_str} | Open: {pos.price_open:.5f} | Current: {pos.price_current:.5f} | P/L: ${profit:.2f}")
        print(f"  SL: {pos.sl:.5f} | TP: {pos.tp:.5f}")
    print("-" * 40)

# --- 2. HISTORIQUE DEALS ---
if history is not None and len(history) > 0:
    df = pd.DataFrame(list(history), columns=history[0]._asdict().keys())
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    # Filtrer GBPUSDm sorties (Entry OUT = 1)
    gbp_today = df[(df['symbol'] == 'GBPUSDm') & (df['entry'] == 1)]
    
    if len(gbp_today) == 0:
        print("\nAucun trade TERMINE pour GBPUSD aujourd'hui.")
    else:
        total_pl = 0
        wins = 0
        losses = 0
        
        for i, row in gbp_today.iterrows():
            pnl = row['profit'] + row['swap'] + row['commission']
            total_pl += pnl
            
            # Déterminer si WIN ou LOSS
            res = "WIN" if pnl >= 0 else "LOSS"
            if pnl >= 0: wins += 1
            else: losses += 1
            
            time_str = row['time'].strftime("%H:%M")
            
            print(f"[CLOSED] {res} | Time: {time_str} | P/L: ${pnl:.2f}")
            print(f"   Exit Price: {row['price']:.5f}")
            print("-" * 40)

        print(f"\nBILAN GBPUSD: {wins} Wins / {losses} Losses")
        print(f"NET P/L: ${total_pl:.2f}")

else:
    print("Aucun historique disponible pour aujourd'hui.")

mt5.shutdown()
