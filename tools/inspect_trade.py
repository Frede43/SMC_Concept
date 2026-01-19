
import sys
import os
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime

# Ajouter la racine au path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker.mt5_connector import MT5Connector

# Config
CONFIG = {
    'mt5': {
        'login': int(os.getenv('MT5_LOGIN', 0)),
        'password': os.getenv('MT5_PASSWORD', ''),
        'server': os.getenv('MT5_SERVER', ''),
        'path': os.getenv('MT5_PATH', r"C:\Program Files\MetaTrader 5\terminal64.exe")
    }
}

def get_deal_reason_str(reason_enum):
    reasons = {
        mt5.DEAL_REASON_CLIENT: "Manuelle (Client)",
        mt5.DEAL_REASON_MOBILE: "Mobile",
        mt5.DEAL_REASON_WEB: "Web",
        mt5.DEAL_REASON_EXPERT: "Expert Advisor (Bot)",
        mt5.DEAL_REASON_SL: "Stop Loss / Trailing Stop",
        mt5.DEAL_REASON_TP: "Take Profit",
        mt5.DEAL_REASON_SO: "Stop Out (Liquidation)",
        mt5.DEAL_REASON_ROLLOVER: "Rollover",
        mt5.DEAL_REASON_VMARGIN: "Variation Margin",
        mt5.DEAL_REASON_SPLIT: "Split"
    }
    return reasons.get(reason_enum, f"Inconnu ({reason_enum})")

def inspect_trade(ticket_id):
    print(f"\n🔍 INSPECTION DU TRADE #{ticket_id}")
    print("=" * 60)
    
    connector = MT5Connector(CONFIG)
    if not connector.connect():
        print("❌ Echec connexion MT5")
        return

    # Récupérer l'historique des deals pour ce ticket de position
    # On cherche large dans le temps (depuis hier)
    from_date = datetime(2026, 1, 9)
    to_date = datetime.now()
    
    deals = mt5.history_deals_get(position=ticket_id)
    
    if deals is None or len(deals) == 0:
        print("❌ Aucun historique trouvé pour ce ticket. Vérifiez le numéro.")
        # Essayer de chercher par ticket de deal si l'user a confondu
        deals = mt5.history_deals_get(ticket=ticket_id)
        if deals:
            print("⚠️ Le ticket fourni était un ID de DEAL, pas de POSITION. Analyse du deal...")
    
    if deals and len(deals) > 0:
        # Convertir en DataFrame pour affichage propre
        df = pd.DataFrame(list(deals), columns=deals[0]._asdict().keys())
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        print(f"Trouvé {len(deals)} transactions liées à cette position :")
        
        entry_deal = df.iloc[0]
        exit_deal = df.iloc[-1]
        
        # ENTRY
        print("\n🟢 ENTRÉE (ENTRY)")
        print(f"   Time : {entry_deal['time']}")
        print(f"   Prix : {entry_deal['price']}")
        print(f"   Vol  : {entry_deal['volume']}")
        print(f"   Comm : {entry_deal['comment']}")
        
        # EXIT
        print("\n🔴 SORTIE (EXIT)")
        if len(deals) > 1:
            print(f"   Time : {exit_deal['time']}")
            print(f"   Prix : {exit_deal['price']}")
            print(f"   P/L  : {exit_deal['profit']} (Swap: {exit_deal['swap']}, Comm: {exit_deal['commission']})")
            print(f"   Reason: {get_deal_reason_str(exit_deal['reason'])}")
            print(f"   Comm : {exit_deal['comment']}")
            
            # Analyse TP
            tp_initial = 90882.51714 # Récupéré de votre prompt
            diff_tp = tp_initial - exit_deal['price']
            
            print("\n📊 ANALYSE DU PRIX DE SORTIE")
            print(f"   Sortie Réelle : {exit_deal['price']:.5f}")
            print(f"   TP Théorique  : {tp_initial:.5f}")
            print(f"   Différence    : {diff_tp:.5f}")
            
            if exit_deal['reason'] == mt5.DEAL_REASON_TP:
                print("   ✅ C'EST UN TAKE PROFIT CONFIRMÉ PAR LE BROKER.")
            elif exit_deal['reason'] == mt5.DEAL_REASON_SL:
                print("   ⚠️ C'EST UN STOP LOSS ou TRAILING STOP.")
                if exit_deal['profit'] > 0:
                    print("   ➜ C'était probablement un TRAILING STOP (Stop Suiveur) qui a sécurisé les gains.")
            elif exit_deal['reason'] == mt5.DEAL_REASON_EXPERT:
                print("   🤖 FERMÉ PAR LE BOT (Logique interne: Weekend, Anti-Tilt, ou autre).")
            else:
                print(f"   ℹ️ Fermé par : {get_deal_reason_str(exit_deal['reason'])}")
                
        else:
            print("   ⚠️ Pas de deal de sortie trouvé (Position peut-être encore ouverte ?)")
            # Vérifier positions ouvertes
            open_pos = mt5.positions_get(ticket=ticket_id)
            if open_pos:
                print("   ✅ OUI, la position est TOUJOURS OUVERTE actuellement.")
                print(f"   Profit Latent: {open_pos[0].profit}")
            else:
                print("   ❌ Position introuvable (Ni ouverte, ni historique complet).")

    connector.disconnect()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        tid = int(sys.argv[1])
    else:
        tid = 2170394667 # Par défaut celui du prompt
        
    inspect_trade(tid)
