
import MetaTrader5 as mt5
import pandas as pd
import time
from strategy.smc_strategy import SMCStrategy
from utils.helpers import load_config
import sys
from datetime import datetime
from loguru import logger

# Désactiver les logs verbeux pour la console de monitoring
logger.remove()
logger.add(sys.stderr, level="INFO")

# Encodage pour les emojis
sys.stdout.reconfigure(encoding='utf-8')

def monitor_btc():
    symbol = 'BTCUSDm'
    threshold = 80.0
    
    print(f"🚀 [MONITORING ACTIVÉ] Surveillance d'élite BTCUSDm...")
    print(f"🎯 Seuil d'alerte : {threshold}% de confiance (Crypto Agnostic Mode)")
    
    if not mt5.initialize():
        print("❌ Erreur d'initialisation MT5")
        return

    config = load_config('config/settings.yaml')
    strategy = SMCStrategy(config)
    
    try:
        while True:
            # Récupérer les données
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 200)
            if rates is not None:
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s')
                df.set_index('time', inplace=True)
                
                # Tick actuel
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    price_info = {
                        'bid': tick.bid, 
                        'ask': tick.ask, 
                        'spread': (tick.ask - tick.bid) / 0.01
                    }
                    
                    # Analyse
                    analysis = strategy.analyze(df, symbol=symbol)
                    signal = strategy.generate_signal(df, symbol=symbol, analysis=analysis, current_tick_price=price_info)
                    
                    bias = analysis.get('bias', 'NEUTRAL')
                    zone = analysis.get('pd_zone').current_zone.value if analysis.get('pd_zone') else 'N/A'
                    
                    # Log ligne de statut
                    status_line = f"[{datetime.now().strftime('%H:%M:%S')}] PRIX: {tick.bid:.2f} | Biais: {bias} | Zone: {zone}"
                    
                    if signal:
                        conf = signal.confidence
                        print(f"{status_line} | 🔥 CONF: {conf:.1f}%")
                        
                        if conf >= threshold:
                            print("\n" + "🚨"*10)
                            print(f"🔥 ALERTE SETUP D'ÉLITE DÉTECTÉ ({conf:.1f}%)")
                            print(f"📌 Direction: {signal.signal_type.name}")
                            print(f"📝 Raisons: {', '.join(signal.reasons[:3])}...")
                            print("🚨"*10 + "\n")
                    else:
                        print(f"{status_line} | ⏳ Scan...", end='\r')

            time.sleep(10) # Scan toutes les 10 secondes

    except KeyboardInterrupt:
        print("\nStopping BTC monitor...")
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    monitor_btc()
