import sys
import os
import io
from pathlib import Path
import logging

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Configurer le logging pour voir ce qui se passe
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="INFO")

# Ajouter le dossier racine au path pour les imports
sys.path.append(os.getcwd())

from strategy.news_filter import NewsFilter

def check_news():
    print("\n" + "="*60)
    print("🌍 ANALYSE DU CALENDRIER ÉCONOMIQUE (SEMAINE À VENIR)")
    print("="*60)
    
    # Configuration pour voir TOUS les événements (High & Medium)
    config = {
        'filters': {
            'news': {
                'enabled': True,
                'filter_high_impact': True,
                'filter_medium_impact': True,  # On veut tout voir pour l'analyse
                'minutes_before': 30,
                'minutes_after': 30,
                'timezone_offset': 2  # Votre fuseau horaire (GMT+2)
            }
        }
    }

    try:
        # Initialiser le filtre
        nf = NewsFilter(config)
        
        # Forcer la mise à jour pour avoir les données fraîches
        print("\n📡 Connexion aux sources de données (ForexFactory, TradingView, Investing)...")
        nf.force_refresh()
        
        # Afficher le calendrier
        # On modifie légèrement l'affichage pour voir plus loin que 48h par défaut
        events = nf.get_upcoming_events(hours_ahead=168) # 7 jours
        
        if not events:
            print("\n❌ Aucun événement trouvé ou erreur de connexion.")
            print(f"Source utilisée: {nf.api_source}")
            return

        print(f"\n✅ Source des données: {nf.api_source.upper()}")
        print(f"📊 Nombre d'événements trouvés: {len(events)}")
        
        # Affichage groupé par jour
        current_date = None
        for event in sorted(events, key=lambda e: e.time):
            event_date = event.time.date()
            
            if event_date != current_date:
                current_date = event_date
                day_name = event.time.strftime("%A %d %B %Y")
                print(f"\n📅 {day_name}")
                print("-" * 75)
                print(f"{'HEURE':<8} | {'DEV':<4} | {'IMPACT':<8} | {'ÉVÉNEMENT'}")
                print("-" * 75)
            
            # Emojis pour l'impact
            impact_str = event.impact.upper()
            if impact_str == "HIGH":
                emoji = "🔴 HIGH  "
            elif impact_str == "MEDIUM":
                emoji = "🟠 MEDIUM"
            else:
                emoji = "🟢 LOW   "
                continue # On filtre les LOW pour la lisibilité
                
            time_str = event.time.strftime("%H:%M")
            print(f"{time_str:<8} | {event.currency:<4} | {emoji:<8} | {event.event}")

        print("\n" + "="*60)
        print("💡 NOTE: Ce sont les heures locales (GMT+2)")
        print("="*60)

    except Exception as e:
        print(f"\n❌ Erreur lors de la récupération : {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_news()
