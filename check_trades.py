
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import sys

# Encodage pour les emojis
sys.stdout.reconfigure(encoding='utf-8')

def get_open_trades():
    if not mt5.initialize():
        print("❌ Erreur d'initialisation MetaTrader5")
        return

    positions = mt5.positions_get()
    
    if positions is None:
        print("❌ Erreur lors de la récupération des positions")
        mt5.shutdown()
        return

    if len(positions) == 0:
        print("\n📭 Aucune position ouverte actuellement.")
        mt5.shutdown()
        return

    print("\n" + "="*80)
    print(f"💼 RÉSUMÉ DES POSITIONS OUVERTES - {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("="*80)
    
    total_profit = 0
    
    for p in positions:
        type_str = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
        emoji = "🔵" if type_str == "BUY" else "🔴"
        
        profit_emoji = "💰" if p.profit >= 0 else "📉"
        
        # Calculer en pips (approximatif pour faciliter la lecture)
        pip_size = 0.0001 if "JPY" not in p.symbol and "BTC" not in p.symbol and "US30" not in p.symbol else 0.01
        if "XAU" in p.symbol: pip_size = 0.1
        
        pips = (p.price_current - p.price_open) / pip_size if type_str == "BUY" else (p.price_open - p.price_current) / pip_size
        
        print(f"{emoji} {p.symbol} | {type_str} | {p.volume} lots")
        print(f"   🎟️ Ticket: {p.ticket}")
        print(f"   📥 Entrée: {p.price_open:.5f} | 🏷️ Actuel: {p.price_current:.5f}")
        print(f"   🛑 SL: {p.sl:.5f} | 🎯 TP: {p.tp:.5f}")
        print(f"   {profit_emoji} P&L: ${p.profit:.2f} ({pips:+.1f} pips)")
        print("-" * 40)
        
        total_profit += p.profit

    print("="*80)
    print(f"💵 PROFIT TOTAL : ${total_profit:.2f}")
    print("="*80 + "\n")

    mt5.shutdown()

if __name__ == "__main__":
    get_open_trades()
