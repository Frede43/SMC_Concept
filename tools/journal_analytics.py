
import csv
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import os
from datetime import datetime

# CONFIGURATION
CSV_PATH = r"D:\SMC\logs\trade_journal.csv"
OUTPUT_DIR = r"D:\SMC\reports"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"Pro_Trading_Journal_{datetime.now().strftime('%Y%m%d')}.html")

def load_data():
    if not os.path.exists(CSV_PATH):
        print(f"ERROR: Le fichier {CSV_PATH} n'existe pas.")
        return None
    
    trades = {}
    completed_trades = []
    
    try:
        with open(CSV_PATH, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f)
            for row in reader:
                if not row: continue
                if len(row) < 3: continue 

                # Parsing manuel index-based (très robuste)
                date_val = row[0]
                try:
                    ticket_val = str(row[1]).strip()
                except: continue
                
                symbol_val = str(row[2]).strip()

                # --- CAS 1: OPEN ---
                if len(row) > 3 and row[3] in ['BUY', 'SELL'] and '---EXIT---' not in symbol_val:
                    
                    # Robust Score Parsing
                    score_val = 0
                    # On cherche un float entre 0 et 100 dans les colonnes 16 a 20 (apres la description)
                    for k in range(16, min(len(row), 25)):
                        try:
                            val = float(row[k])
                            if 10 <= val <= 100: # Score plausible
                                score_val = val
                                break
                        except: pass
                    
                    setup_val = "Unknown"
                    # Setup est souvent une string avec des pipes ex "SMT|FVG"
                    for k in range(15, min(len(row), 25)):
                        if "|" in str(row[k]):
                            setup_val = row[k]
                            break

                    trades[ticket_val] = {
                        'Date': date_val,
                        'Ticket': ticket_val,
                        'Symbol': symbol_val,
                        'Type': row[3],
                        'Setup': setup_val,
                        'Score': score_val,
                        'Outcome': 'OPEN' 
                    }

                # --- CAS 2: EXIT ---
                elif '---EXIT---' in symbol_val:
                    if ticket_val in trades:
                        trade = trades[ticket_val]
                        
                        pnl = 0.0
                        outcome = "Unknown"
                        
                        try:
                            closed_idx = -1
                            # Chercher 'CLOSED' depuis la fin
                            for i in range(len(row)-1, 0, -1):
                                if row[i] == 'CLOSED':
                                    closed_idx = i
                                    break
                            
                            if closed_idx != -1:
                                # Chercher Profit avant CLOSED
                                for j in range(closed_idx-1, closed_idx-6, -1):
                                    try:
                                        val = float(row[j])
                                        if abs(val) > 0.0001: 
                                            pnl = val
                                            # On continue de chercher si on trouve plus grand (car parfois risk% est petit)
                                            # Non, prenons le premier trouvé en reculant (souvent PnL est juste avant)
                                            break 
                                    except: pass
                                
                                if len(row) > closed_idx + 1:
                                    outcome = row[closed_idx+1]
                            
                            trade['Profit'] = pnl
                            trade['Result'] = 'CLOSED'
                            trade['Outcome'] = outcome
                            completed_trades.append(trade)
                            
                        except Exception as e:
                            print(f"Error parsing exit row {ticket_val}: {e}")

        print(f"DEBUG: Trades complets reconstruits: {len(completed_trades)}")
        
        results_df = pd.DataFrame(completed_trades)
        if not results_df.empty:
            results_df['Date'] = pd.to_datetime(results_df['Date'])
            results_df = results_df.sort_values(by='Date')
            results_df['Equity'] = results_df['Profit'].cumsum()
            
        return results_df

    except Exception as e:
        print(f"ERROR global parsing: {e}")
        return None

def generate_dashboard(df):
    if df is None or df.empty:
        print("WARN: Aucune donnee de trade cloture a analyser.")
        return

    # --- KPI CALCULATIONS ---
    total_trades = len(df)
    wins = df[df['Profit'] > 0]
    losses = df[df['Profit'] <= 0]
    breakeven = df[df['Profit'] == 0]
    
    win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0
    total_profit = df['Profit'].sum()
    avg_win = wins['Profit'].mean() if not wins.empty else 0
    avg_loss = losses['Profit'].mean() if not losses.empty else 0
    
    gross_win = wins['Profit'].sum()
    gross_loss = abs(losses['Profit'].sum())
    profit_factor = (gross_win / gross_loss) if gross_loss != 0 else 0
    
    # --- VISUALIZATIONS ---
    fig = make_subplots(rows=2, cols=2, 
                        specs=[[{"colspan": 2}, None], [{"type": "domain"}, {"type": "bar"}]],
                        subplot_titles=("Cumulative Profit (Equity)", "Win / Loss Ratio", "Performance by Symbol"))

    fig.add_trace(go.Scatter(x=df['Date'], y=df['Equity'], mode='lines+markers', name='Equity',
                             line=dict(color='#00E676', width=3), fill='tozeroy'), row=1, col=1)

    fig.add_trace(go.Pie(labels=['Wins', 'Losses', 'BE'], values=[len(wins), len(losses), len(breakeven)], 
                         marker_colors=['#00E676', '#FF5252', '#FFD600'], hole=.6), row=2, col=1)

    symbol_perf = df.groupby('Symbol')['Profit'].sum().reset_index()
    fig.add_trace(go.Bar(x=symbol_perf['Symbol'], y=symbol_perf['Profit'], 
                         marker_color=symbol_perf['Profit'].apply(lambda x: '#00E676' if x>0 else '#FF5252')), 
                  row=2, col=2)

    fig.update_layout(template="plotly_dark", height=800, showlegend=False,
                      title_text=f"<b>SMC PERFORMANCE DASHBOARD</b> | Net: ${total_profit:.2f} | PF: {profit_factor:.2f}")

    # Setup Analysis
    setup_perf = df.groupby('Setup')['Profit'].sum().reset_index().sort_values(by='Profit', ascending=False)
    setup_fig = px.bar(setup_perf, x='Setup', y='Profit', color='Profit', 
                       title="Best Performing Setups",
                       color_continuous_scale=['#FF5252', '#00E676'])
    setup_fig.update_layout(template="plotly_dark")

    # --- HTML OUT ---
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    with open(OUTPUT_FILE, 'w', encoding="utf-8") as f:
        f.write(f"""
        <html>
        <head>
            <title>SMC Pro Journal</title>
            <style>
                body {{ font-family: 'Segoe UI', sans-serif; background-color: #0e0e0e; color: #e0e0e0; padding: 20px; }}
                h1 {{ color: #00E676; text-transform: uppercase; letter-spacing: 2px; }}
                .kpi-container {{ display: flex; justify-content: space-between; margin-bottom: 20px; }}
                .kpi-card {{ background: #1e1e1e; padding: 20px; border-radius: 8px; width: 18%; text-align: center; border-left: 4px solid #00E676; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
                .kpi-card.bad {{ border-left: 4px solid #FF5252; }}
                .kpi-title {{ font-size: 12px; opacity: 0.7; text-transform: uppercase; }}
                .kpi-value {{ font-size: 28px; font-weight: bold; margin-top: 5px; }}
                .table-container {{ margin-top: 30px; overflow-x: auto; }}
                table {{ width: 100%; border-collapse: collapse; background: #1e1e1e; font-size: 14px; }}
                th, td {{ padding: 15px; text-align: left; border-bottom: 1px solid #333; }}
                th {{ background-color: #252525; color: #00E676; font-weight: 600; }}
                tr:hover {{ background-color: #2a2a2a; }}
                .win {{ color: #00E676; font-weight: bold; }}
                .loss {{ color: #FF5252; font-weight: bold; }}
                .tag {{ background: #333; padding: 2px 6px; border-radius: 4px; font-size: 11px; margin-right: 4px; }}
            </style>
        </head>
        <body>
            <h1>SMC Algo | Institutional Dashboard</h1>
            <div class="kpi-container">
                <div class="kpi-card">
                    <div class="kpi-title">NET PROFIT</div>
                    <div class="kpi-value {'win' if total_profit >= 0 else 'loss'}">${total_profit:.2f}</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-title">Win Rate</div>
                    <div class="kpi-value">{win_rate:.1f}%</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-title">Trades</div>
                    <div class="kpi-value">{total_trades}</div>
                </div>
                 <div class="kpi-card">
                    <div class="kpi-title">Profit Factor</div>
                    <div class="kpi-value">{profit_factor:.2f}</div>
                </div>
                 <div class="kpi-card">
                    <div class="kpi-title">Avg Win/Loss</div>
                    <div class="kpi-value">${avg_win:.0f} / ${avg_loss:.0f}</div>
                </div>
            </div>
            <div id="charts">
                {fig.to_html(full_html=False, include_plotlyjs='cdn')}
                {setup_fig.to_html(full_html=False, include_plotlyjs=False)}
            </div>
            <div class="table-container">
                <h3>📜 Trade History</h3>
                {df[['Date', 'Ticket', 'Symbol', 'Type', 'Outcome', 'Setup', 'Score', 'Profit']].sort_values(by='Date', ascending=False).to_html(classes="table", index=False)}
            </div>
        </body>
        </html>
        """)
    
    print(f"SUCCESS Report: {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_dashboard(load_data())
