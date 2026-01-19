"""
Analyse de performance détaillée des trades
"""
import pandas as pd
from datetime import datetime

# Lire le journal de trades
df = pd.read_csv('logs/trade_journal.csv', header=None, on_bad_lines='skip')

# Colonnes simplifiées
cols = ['timestamp', 'ticket', 'symbol', 'direction', 'entry', 'sl', 'tp', 'lot', 'risk', 
        'atr', 'rr', 'score', 'zone', 'bias_ltf', 'trend_htf', 'bias_htf', 'smt_bias', 
        'reasons', 'tags', 'confidence', 'major_sweep', 'confluence_htf', 'confluence_news',
        'ifvg_dir', 'amd_phase', 'session', 'passed_filters']

df.columns = cols + [f'extra_{i}' for i in range(len(df.columns) - len(cols))]

# Filtrer les trades fermés (ligne EXIT)
exits = df[df['symbol'] == '---EXIT---'].copy()

# Extraire les données des sorties
if len(exits) > 0:
    # Récupérer le P/L depuis les colonnes extra
    exits['exit_price'] = pd.to_numeric(exits['extra_0'], errors='coerce')
    exits['exit_time'] = exits['extra_1']
    exits['pnl_dollar'] = pd.to_numeric(exits['extra_3'], errors='coerce')
    exits['status'] = exits['extra_5']
    exits['close_reason'] = exits['extra_6']
    
    # Filtrer les valeurs valides
    exits = exits[exits['pnl_dollar'].notna()].copy()
    
    print("\n" + "="*80)
    print("ANALYSE DETAILLEE DES TRADES - SMC BOT")
    print("="*80)
    
    # Stats globales
    total = len(exits)
    wins = exits[exits['pnl_dollar'] > 0]
    losses = exits[exits['pnl_dollar'] < 0]
    
    win_rate = len(wins) / total * 100 if total > 0 else 0
    total_profit = exits['pnl_dollar'].sum()
    
    print(f"\n🎯 PERFORMANCE GLOBALE")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Total Trades Fermés   : {total}")
    print(f"Gagnants (✅)         : {len(wins)} ({win_rate:.1f}%)")
    print(f"Perdants (❌)         : {len(losses)} ({100-win_rate:.1f}%)")
    print(f"\nProfit Total          : ${total_profit:.2f}")
    
    if len(wins) > 0 and len(losses) > 0:
        avg_win = wins['pnl_dollar'].mean()
        avg_loss = losses['pnl_dollar'].mean()
        profit_factor = wins['pnl_dollar'].sum() / abs(losses['pnl_dollar'].sum())
        
        print(f"Profit Moyen (Win)    : ${avg_win:.2f}")
        print(f"Perte Moyenne (Loss)  : ${avg_loss:.2f}")
        print(f"Profit Factor         : {profit_factor:.2f}")
        print(f"Expectancy par trade  : ${exits['pnl_dollar'].mean():.2f}")
    
    # Par symbole
    print(f"\n💹 PERFORMANCE PAR SYMBOLE")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # Récupérer le symbole du trade d'entrée correspondant
    entries = df[df['symbol'] != '---EXIT---'].copy()
    
    for idx, exit_row in exits.iterrows():
        # Trouver l'entrée correspondante par ticket
        entry = entries[entries['ticket'] == exit_row['ticket']]
        if len(entry) > 0:
            symbol = entry.iloc[0]['symbol']
            exits.at[idx, 'real_symbol'] = symbol
    
    if 'real_symbol' in exits.columns:
        for symbol in exits['real_symbol'].dropna().unique():
            sym_trades = exits[exits['real_symbol'] == symbol]
            sym_wins = sym_trades[sym_trades['pnl_dollar'] > 0]
            sym_pnl = sym_trades['pnl_dollar'].sum()
            sym_wr = len(sym_wins) / len(sym_trades) * 100 if len(sym_trades) > 0 else 0
            
            status = "✅" if sym_pnl > 0 else "❌"
            print(f"{status} {symbol:12s}: {len(sym_wins):2d}/{len(sym_trades):2d} wins ({sym_wr:5.1f}%) | P/L: ${sym_pnl:+7.2f}")
    
    # Raisons de clôture
    print(f"\n🔍 RAISONS DE CLÔTURE")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    close_reasons = exits['close_reason'].value_counts()
    for reason, count in close_reasons.items():
        pct = count / total * 100
        print(f"{reason:20s}: {count:2d} ({pct:5.1f}%)")
    
    # Meilleurs et pires trades
    print(f"\n🏆 TOP 3 MEILLEURS TRADES")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    top_wins = exits.nlargest(3, 'pnl_dollar')
    for idx, trade in top_wins.iterrows():
        entry = entries[entries['ticket'] == trade['ticket']]
        if len(entry) > 0:
            symbol = entry.iloc[0]['symbol']
            direction = entry.iloc[0]['direction']
            print(f"${trade['pnl_dollar']:+7.2f} | {symbol} {direction} | Ticket #{trade['ticket']}")
    
    print(f"\n💔 TOP 3 PIRES TRADES")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    worst_losses = exits.nsmallest(3, 'pnl_dollar')
    for idx, trade in worst_losses.iterrows():
        entry = entries[entries['ticket'] == trade['ticket']]
        if len(entry) > 0:
            symbol = entry.iloc[0]['symbol']
            direction = entry.iloc[0]['direction']
            print(f"${trade['pnl_dollar']:+7.2f} | {symbol} {direction} | Ticket #{trade['ticket']}")
    
    print("\n" + "="*80)

else:
    print("Aucun trade fermé trouvé dans le journal")
