# -*- coding: utf-8 -*-
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd

# Lire le journal
df = pd.read_csv('logs/trade_journal.csv', header=None, on_bad_lines='skip')

# Définir les colonnes principales
main_cols = ['timestamp', 'ticket', 'symbol', 'direction', 'entry', 'sl', 'tp', 'lot']
df.columns = main_cols + [f'col{i}' for i in range(len(df.columns) - len(main_cols))]

print("\n" + "="*80)
print("ANALYSE DES TRADES - SMC BOT")
print("="*80 + "\n")

# Séparer entrées et sorties
entries = df[df['symbol'] != '---EXIT---'].copy()
exits = df[df['symbol'] == '---EXIT---'].copy()

print(f"Total Entries logged: {len(entries)}")
print(f"Total Exits logged: {len(exits)}\n")

# Analyser les exits avec P/L
if len(exits) > 0:
    # Essayer de trouver P/L dans les colonnes supplémentaires
    for i in range(8, min(15, len(exits.columns))):
        col_name = exits.columns[i]
        try:
            exits['pnl_test'] = pd.to_numeric(exits[col_name], errors='coerce')
            if exits['pnl_test'].notna().sum() > 0:
                # Vérifier que ce sont des valeurs de P/L raisonnables
                if abs(exits['pnl_test'].mean()) < 1000:
                    exits['pnl_dollar'] = exits['pnl_test']
                    print(f"P/L trouvé dans colonne {i} ({col_name})")
                    break
        except:
            continue
    
    if 'pnl_dollar' in exits.columns:
        valid_exits = exits[exits['pnl_dollar'].notna()].copy()
        
        print(f"\nTrades with P/L data: {len(valid_exits)}")
        
        wins = valid_exits[valid_exits['pnl_dollar'] > 0]
        losses = valid_exits[valid_exits['pnl_dollar'] <= 0]
        
        print("\n" + "-"*80)
        print("STATISTIQUES GLOBALES")
        print("-"*80)
        print(f"Total Trades    : {len(valid_exits)}")
        print(f"Winners         : {len(wins)} ({len(wins)/len(valid_exits)*100:.1f}%)")
        print(f"Losers          : {len(losses)} ({len(losses)/len(valid_exits)*100:.1f}%)")
        print(f"\nProfit Total    : ${valid_exits['pnl_dollar'].sum():.2f}")
        
        if len(wins) > 0:
            print(f"Avg Win         : ${wins['pnl_dollar'].mean():.2f}")
            print(f"Best Win        : ${wins['pnl_dollar'].max():.2f}")
        
        if len(losses) > 0:
            print(f"Avg Loss        : ${losses['pnl_dollar'].mean():.2f}")
            print(f"Worst Loss      : ${losses['pnl_dollar'].min():.2f}")
        
        if len(wins) > 0 and len(losses) > 0:
            pf = wins['pnl_dollar'].sum() / abs(losses['pnl_dollar'].sum())
            print(f"\nProfit Factor   : {pf:.2f}")
        
        # Merger avec entries pour récupérer symbole
        print("\n" + "-"*80)
        print("PAR SYMBOLE")
        print("-"*80)
        
        for idx, exit_row in valid_exits.iterrows():
            ticket = exit_row['ticket']
            entry = entries[entries['ticket'] == ticket]
            if len(entry) > 0:
                valid_exits.at[idx, 'real_symbol'] = entry.iloc[0]['symbol']
                valid_exits.at[idx, 'real_direction'] = entry.iloc[0]['direction']
        
        if 'real_symbol' in valid_exits.columns:
            for symbol in sorted(valid_exits['real_symbol'].dropna().unique()):
                sym_trades = valid_exits[valid_exits['real_symbol'] == symbol]
                sym_wins = sym_trades[sym_trades['pnl_dollar'] > 0]
                sym_pnl = sym_trades['pnl_dollar'].sum()
                sym_wr = len(sym_wins) / len(sym_trades) * 100
                
                status = "[+]" if sym_pnl > 0 else "[-]"
                print(f"{status} {symbol:12s}: {len(sym_wins):2d}/{len(sym_trades):2d} ({sym_wr:5.1f}%) | P/L: ${sym_pnl:+7.2f}")
        
        # Par direction
        print("\n" + "-"*80)
        print("PAR DIRECTION")
        print("-"*80)
        
        if 'real_direction' in valid_exits.columns:
            for direction in ['BUY', 'SELL']:
                dir_trades = valid_exits[valid_exits['real_direction'] == direction]
                if len(dir_trades) > 0:
                    dir_wins = dir_trades[dir_trades['pnl_dollar'] > 0]
                    dir_pnl = dir_trades['pnl_dollar'].sum()
                    dir_wr = len(dir_wins) / len(dir_trades) * 100
                    print(f"{direction:4s}: {len(dir_wins):2d}/{len(dir_trades):2d} ({dir_wr:5.1f}%) | P/L: ${dir_pnl:+7.2f}")
        
        # Top 5 wins
        print("\n" + "-"*80)
        print("TOP 5 MEILLEURS TRADES")
        print("-"*80)
        top_wins = valid_exits.nlargest(5, 'pnl_dollar')
        for i, (idx, trade) in enumerate(top_wins.iterrows(), 1):
            symbol = trade.get('real_symbol', '???')
            direction = trade.get('real_direction', '???')
            print(f"{i}. ${trade['pnl_dollar']:+7.2f} | {symbol} {direction} | Ticket #{int(trade['ticket'])}")
        
        # Top 5 losses
        print("\n" + "-"*80)
        print("TOP 5 PIRES TRADES")
        print("-"*80)
        worst_losses = valid_exits.nsmallest(5, 'pnl_dollar')
        for i, (idx, trade) in enumerate(worst_losses.iterrows(), 1):
            symbol = trade.get('real_symbol', '???')
            direction = trade.get('real_direction', '???')
            print(f"{i}. ${trade['pnl_dollar']:+7.2f} | {symbol} {direction} | Ticket #{int(trade['ticket'])}")

print("\n" + "="*80 + "\n")
