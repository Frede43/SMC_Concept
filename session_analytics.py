"""
📊 SESSION ANALYTICS CLI
Affiche les statistiques de performance par session de trading

Usage:
    python session_analytics.py          # Affiche le rapport complet
    python session_analytics.py --export # Exporte en CSV
    python session_analytics.py --json   # Export JSON
"""

import sys
import argparse
from pathlib import Path

# Ajouter le répertoire racine au path
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from utils.session_tracker import SessionPerformanceTracker, get_session_tracker
from utils.correlation_guard import CorrelationGuard, get_correlation_guard
from loguru import logger

# Configuration du logger
logger.remove()
logger.add(sys.stderr, level="WARNING")


def main():
    parser = argparse.ArgumentParser(description="📊 Session Analytics CLI")
    parser.add_argument("--export", action="store_true", help="Exporter en CSV")
    parser.add_argument("--json", action="store_true", help="Exporter en JSON")
    parser.add_argument("--exposure", action="store_true", help="Afficher rapport d'exposition")
    parser.add_argument("--recommendations", action="store_true", help="Afficher recommendations")
    parser.add_argument("--import-days", type=int, help="Importer l'historique MT5 des N derniers jours")
    
    args = parser.parse_args()
    
    # Fix output encoding for Windows
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
    
    tracker = get_session_tracker()
    
    if args.import_days:
        import_history(tracker, args.import_days)
        # Après import, afficher le rapport par défaut si aucune autre option n'est spécifiée
        if not (args.export or args.json or args.exposure or args.recommendations):
            args.export = False # Just to be safe, continue to print report logic
        else:
            return

    if args.export:
        tracker.export_to_csv()
        print("✅ Données exportées vers logs/session_analysis.csv")
        return
    
    if args.json:
        import json
        summary = {
            'sessions': tracker.get_session_summary(),
            'strategies': tracker.get_strategy_session_matrix(),
            'hourly': tracker.get_hourly_heatmap(),
            'recommendations': tracker.get_recommendations()
        }
        print(json.dumps(summary, indent=2, default=str))
        return
    
    if args.exposure:
        guard = get_correlation_guard()
        guard.print_exposure_report()
        return
    
    if args.recommendations:
        recs = tracker.get_recommendations()
        print("\n💡 RECOMMANDATIONS BASÉES SUR L'ANALYSE:")
        print("=" * 50)
        for rec in recs:
            print(f"  {rec}")
        print()
        return
    
    # Par défaut: afficher le rapport complet
    tracker.print_report()
    
    # Afficher aussi un résumé des meilleures sessions
    print("\n📈 TOP SESSIONS (min 5 trades):")
    print("-" * 40)
    best = tracker.get_best_sessions(min_trades=5)
    if best:
        for name, wr, trades in best[:3]:
            emoji = "🥇" if wr > 60 else "🥈" if wr > 50 else "🥉"
            print(f"  {emoji} {name.upper()}: {wr:.1f}% WR ({trades} trades)")
    else:
        print("  Pas assez de données")
    
    print()


def import_history(tracker, days: int):
    """Importe l'historique depuis MT5."""
    try:
        import MetaTrader5 as mt5
        from datetime import datetime, timedelta
        
        print(f"🔌 Connexion à MT5 pour import historique ({days} jours)...")
        if not mt5.initialize():
            logger.error(f"❌ Échec connexion MT5: {mt5.last_error()}")
            return

        end = datetime.now()
        start = end - timedelta(days=days)
        
        print(f"📥 Récupération deals depuis {start.strftime('%Y-%m-%d')}...")
        deals = mt5.history_deals_get(start, end)
        
        if deals is None:
            print("⚠️ Erreur récupération deals ou historique vide.")
            return
            
        if len(deals) == 0:
            print("ℹ️ Aucun deal trouvé sur cette période.")
            return

        print(f"🔍 Analyse de {len(deals)} deals...")
        count = 0
        new_trades = 0
        
        # Cache des tickets existants pour éviter doublons
        # On suppose que 'ticket' dans le tracker correspond au 'position_id' MT5
        existing_tickets = {int(t['ticket']) for t in tracker.trades if 'ticket' in t}
        
        # Grouper les deals par position_id
        deals_by_pos = {}
        for deal in deals:
            if deal.position_id not in deals_by_pos:
                deals_by_pos[deal.position_id] = []
            deals_by_pos[deal.position_id].append(deal)
            
        for pos_id, pos_deals in deals_by_pos.items():
            if pos_id in existing_tickets:
                continue
                
            if pos_id == 0: # Deals non liés à une position (ex: balance operations)
                continue

            # Trouver Entry (In) et Exit (Out)
            in_deals = [d for d in pos_deals if d.entry == 0] # DEAL_ENTRY_IN
            out_deals = [d for d in pos_deals if d.entry == 1] # DEAL_ENTRY_OUT
            
            if not in_deals or not out_deals:
                # Position incomplète ou ouverte
                continue
                
            entry_deal = in_deals[0]
            exit_deal = out_deals[-1] # La dernière sortie ferme la position
            
            # Calculer profit total (somme de tous les deals de la position)
            total_profit = sum(d.profit + d.swap + d.commission for d in pos_deals)
            
            # Essayer de deviner la stratégie depuis les commentaires
            comment = entry_deal.comment if entry_deal.comment else ""
            strategy = "imported"
            if "SB" in comment or "Silver" in comment: strategy = "silver_bullet"
            elif "PDL" in comment: strategy = "pdl_sweep"
            elif "Asian" in comment: strategy = "asian_sweep"
            elif "SMT" in comment: strategy = "smt"
            
            trade_data = {
                'ticket': pos_id,
                'symbol': entry_deal.symbol,
                'direction': 'BUY' if entry_deal.type == 0 else 'SELL', # 0=BUY
                'entry_time': datetime.fromtimestamp(entry_deal.time),
                'exit_time': datetime.fromtimestamp(exit_deal.time),
                'profit': total_profit,
                'strategy': strategy,
                'session': None # Le tracker le calculera via l'heure
            }
            
            tracker.record_trade(trade_data)
            new_trades += 1
            
        print(f"✅ Import terminé: {new_trades} nouveaux trades ajoutés.")
        
    except Exception as e:
        logger.error(f"❌ Erreur critique import: {e}")
        import traceback
        traceback.print_exc()
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
