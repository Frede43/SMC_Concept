
import json
from datetime import datetime, timedelta
from pathlib import Path

def simulate_news():
    cache_path = Path("data/news_cache.json")
    if not cache_path.exists():
        print("Cache file not found, please run the bot first to initialize it.")
        return

    with open(cache_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Création d'une news fictive dans 10 minutes
    now = datetime.now()
    fake_news_time = now + timedelta(minutes=10)
    
    fake_event = {
        "time": fake_news_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "currency": "GBP",
        "impact": "high",
        "event": "🚀 TEST: NEWS FICTIVE EXNESS HIL",
        "forecast": "TEST",
        "previous": "TEST"
    }

    # Insérer au début pour être sûr qu'elle soit vue
    data['events'].insert(0, fake_event)
    data['timestamp'] = now.isoformat() # Forcer le cache à être "frais"

    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    print(f"DONE: News simulee ajoutee a {fake_news_time.strftime('%H:%M:%S')} pour GBP")
    print(f"      Le bot devrait bloquer le trading pendant 15 min avant et 5 min après.")

if __name__ == "__main__":
    simulate_news()
