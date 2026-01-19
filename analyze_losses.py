import MetaTrader5 as mt5
from dotenv import load_dotenv
import os
import pandas as pd
from datetime import datetime, timedelta

# Charger l'environnement
load_dotenv()

# Initialisation MT5
if not mt5.initialize():
    print("❌ MT5 Init Failed")
    exit()

# Login
login = int(os.getenv('MT5_LOGIN', 0))
password = os.getenv('MT5_PASSWORD', '')
server = os.getenv('MT5_SERVER', 'Exness-MT5Trial9')

if not mt5.login(login, password=password, server=server):
    print(f"❌ Login Failed: {mt5.last_error()}")
    mt5.shutdown()
    exit()

# Récupérer l'historique
from_date = datetime.now() - timedelta(days=30)
to_date = datetime.now() + timedelta(days=1)
history = mt5.history_deals_get(from_date, to_date)

if history is None or len(history) == 0:
    print("⚠️ Aucun historique trouvé")
else:
    # Créer DataFrame
    df = pd.DataFrame(list(history), columns=history[0]._asdict().keys())
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    # Filtrer les sorties de trades GBPUSDm
    trades = df[(df['symbol'] == 'GBPUSDm') & (df['entry'] == 1)]
    
    print(f"\n=== 📊 ANALYSE DÉTAILLÉE DES PERTES GBPUSD ({len(trades)} trades) ===\n")
    
    total_wins = 0
    total_losses = 0
    total_pnl = 0.0
    
    for _, row in trades.iterrows():
        pnl = row['profit'] + row['swap'] + row['commission']
        total_pnl += pnl
        
        is_win = pnl > 0
        if is_win: total_wins += 1
        else: total_losses += 1
        
        status_icon = "✅" if is_win else "❌"
        
        # Retrouver le deal d'entrée
        entry_deal = df[(df['position_id'] == row['position_id']) & (df['entry'] == 0)]
        
        entry_price = 0.0
        duration_str = "N/A"
        entry_time = None
        
        if not entry_deal.empty:
            entry_price = entry_deal.iloc[0]['price']
            entry_time = entry_deal.iloc[0]['time']
            type_op = "BUY" if entry_deal.iloc[0]['type'] == 0 else "SELL"
            
            duration = row['time'] - entry_time
            hours, remainder = divmod(duration.total_seconds(), 3600)
            minutes, _ = divmod(remainder, 60)
            duration_str = f"{int(hours)}h {int(minutes)}m"
        else:
            type_op = "UNKNOWN"
            
        print(f"{status_icon} Trade #{row['position_id']} | {type_op} | {row['time']} | P/L: ${pnl:.2f}")
        
        if entry_price > 0:
            diff_pips = abs(row['price'] - entry_price) * 10000
            print(f"   📉 Entry: {entry_price:.5f} -> Exit: {row['price']:.5f} | Mvmt: {diff_pips:.1f} pips | Durée: {duration_str}")
            
            # Analyse des causes de perte
            if not is_win:
                print("   ⚠️ DIAGNOSTIC PERTE:")
                if diff_pips < 10:
                    print("      -> SL TROP SERRÉ (< 10 pips). Le bruit du marché a touché le stop.")
                    print("      -> RECOMMANDATION: Augmenter 'min_sl_pips' à 15-20.")
                elif duration.total_seconds() < 300: # moins de 5 min
                    print("      -> REJET IMMÉDIAT (Fakeout). Entrée probablement sur une mèche.")
                    print("      -> RECOMMANDATION: Attendre clôture bougie ou confirmation.")
                elif row['price'] == entry_price: # Break Even
                    print("      -> SORTIE BREAK-EVEN. Le trade a bougé favorablement puis est revenu.")
                    print("      -> C'est une bonne protection, pas une 'vraie' perte.")
                elif type_op == "BUY" and row['price'] < entry_price:
                    print("      -> Tendance baissière plus forte que prévue.")
                elif type_op == "SELL" and row['price'] > entry_price:
                    print("      -> Tendance haussière plus forte que prévue.")
        
        print("-" * 50)

    print(f"\n=== RÉSUMÉ ===\nWins: {total_wins} | Losses: {total_losses} | P/L Total: ${total_pnl:.2f}")

mt5.shutdown()
