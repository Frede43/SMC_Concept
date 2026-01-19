
import MetaTrader5 as mt5
import pandas as pd
from strategy.smc_strategy import SMCStrategy
from utils.helpers import load_config
import sys
from datetime import datetime

# Encodage pour les emojis
sys.stdout.reconfigure(encoding='utf-8')

def scan_btc():
    symbol = 'BTCUSDm'
    print(f"🔍 Scan immédiat de {symbol} en cours...")
    
    if not mt5.initialize():
        print("❌ Erreur d'initialisation MT5")
        return

    config = load_config('config/settings.yaml')
    strategy = SMCStrategy(config)
    
    # Récupérer les données
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 500)
    if rates is None:
        print(f"❌ Impossible de récupérer les données pour {symbol}")
        return
        
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    
    # Tick actuel
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print(f"❌ Impossible de récupérer le tick pour {symbol}")
        return
        
    price_info = {
        'bid': tick.bid, 
        'ask': tick.ask, 
        'spread': (tick.ask - tick.bid) / 0.01
    }
    
    # Analyse
    analysis = strategy.analyze(df, symbol=symbol)
    signal = strategy.generate_signal(df, symbol=symbol, analysis=analysis, current_tick_price=price_info)
    
    print("\n" + "="*50)
    print(f"📊 RAPPORT DE SCAN SMC - {symbol}")
    print(f"⏰ Heure: {datetime.now().strftime('%H:%M:%S')}")
    print("="*50)
    print(f"💰 Prix Actuel : {tick.bid}")
    print(f"🌍 Zone P/D    : {analysis.get('pd_zone').current_zone.value if analysis.get('pd_zone') else 'N/A'}")
    print(f"📈 Tendance LTF: {analysis.get('trend')}")
    print(f"🎯 Biais Global: {analysis.get('bias')}")
    
    if signal:
        print(f"\n🚀 SIGNAL DÉTECTÉ : {signal.signal_type.name}")
        print(f"🔥 Confiance : {signal.confidence:.1f}%")
        print(f"📝 Raisons :")
        for r in signal.reasons:
            print(f"   - {r}")
    else:
        print("\n⏳ Statut : Aucun signal d'élite détecté pour le moment.")
        print(f"💡 Note : Le bot surveille un signal avec une confiance > 80% (Crypto Security)")
    
    print("="*50)
    mt5.shutdown()

if __name__ == "__main__":
    scan_btc()
