"""
HISTORY INSPECTOR
Analyse les trades terminés aujourd'hui pour en extraire des leçons SMC.
"""
import sys
from pathlib import Path
import yaml
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, time, timedelta
from loguru import logger

# Ajouter le répertoire racine au path
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from broker.mt5_connector import MT5Connector

def analyze_history():
    # Charger la config
    with open("config/settings.yaml", 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
        
    # Connexion MT5
    connector = MT5Connector(config)
    if not connector.connect():
        logger.error("Impossible de se connecter à MT5")
        return

    # Définir la période (aujourd'hui)
    from_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    to_date = datetime.now()
    
    # Récupérer l'historique des DEALS (les exécutions réelles)
    history_deals = mt5.history_deals_get(from_date, to_date)
    
    if not history_deals:
        print(f"\n[!] AUCUN TRADE TERMINÉ AUJOURD'HUI ({from_date.strftime('%Y-%m-%d')})")
        mt5.shutdown()
        return

    # Filtrer pour ne garder que les sorties de positions (Entry Out)
    # Dans MT5, un deal avec entry IN_OUT ou OUT est une fermeture ou modification
    # Mais le plus simple est de regarder les deals avec un profit != 0
    closed_trades = [d for d in history_deals if d.entry in [1, 2] and d.magic != 0] # 1=OUT, 2=IN/OUT (Partial)

    if not closed_trades:
        print("\n[!] AUCUNE FERMETURE DE POSITION DÉTECTÉE (MAGIC != 0)")
        mt5.shutdown()
        return

    print(f"\n[INFO] ANALYSE DE {len(closed_trades)} TRADES TERMINÉS AUJOURD'HUI")
    print("=" * 80)
    print(f"{'Heure':<20} | {'Symbole':<10} | {'Type':<5} | {'Profit($)':>10} | {'Commentaire'}")
    print("-" * 80)

    total_profit = 0
    wins = 0
    losses = 0

    for deal in closed_trades:
        symbol = deal.symbol
        profit = deal.profit + deal.commission + deal.swap
        total_profit += profit
        
        # Déterminer si c'était un BUY ou SELL initial
        # Si le deal de sortie est un SELL, la position était BUY
        # Mais mt5.history_deals_get ne donne pas directement l'ordre d'origine facilement sans chercher le ticket
        # On va simplifier en regardant le profit
        status = "WIN" if profit > 0 else "LOSS"
        if profit > 0: wins += 1
        else: losses += 1
        
        deal_time = datetime.fromtimestamp(deal.time).strftime('%H:%M:%S')
        
        # Commentaire Expert
        comment = ""
        if profit > 0:
            comment = "Prise de profit exécutée. La cible de liquidité a probablement été atteinte."
        else:
            comment = "Stop Loss touché. Probablement une invalidation de la structure ou un sweep plus profond."
            
        print(f"{deal_time:<20} | {symbol:<10} | {status:<5} | {profit:>10.2f} | {comment}")

    print("-" * 80)
    win_rate = (wins / len(closed_trades)) * 100 if closed_trades else 0
    print(f"Bilan Journée : {total_profit:>10.2f}$ | Win Rate: {win_rate:.1f}% ({wins}W / {losses}L)")
    print("=" * 80)

    mt5.shutdown()

if __name__ == "__main__":
    analyze_history()
