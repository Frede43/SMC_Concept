
import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime
from core.market_structure import MarketStructure, Trend
from core.killzones import KillzoneDetector
from core.premium_discount import PremiumDiscountZones
import sys

# Configure output for live monitoring
sys.stdout.reconfigure(encoding='utf-8')

def monitor_us30():
    symbol = "US30m"
    print(f"🚀 Démarrage du monitoring institutionnel pour {symbol}...")
    
    if not mt5.initialize():
        print("Erreur initialisation MT5")
        return

    # Configuration des détecteurs
    ms = MarketStructure(swing_strength=3)
    pd_calc = PremiumDiscountZones(pip_value=0.1) # US30 pip = 0.1
    kz_detector = KillzoneDetector(timezone_offset=2)

    try:
        while True:
            # 1. Récupérer les données M1 pour la structure fine
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 100)
            if rates is None or len(rates) == 0:
                print("Erreur récupération données")
                time.sleep(10)
                continue
                
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('time', inplace=True)
            
            # 2. Récupérer les données M15 pour le Asian Range
            rates_m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 100)
            if rates_m15 is None:
                time.sleep(5)
                continue
            df_m15 = pd.DataFrame(rates_m15)
            df_m15['time'] = pd.to_datetime(df_m15['time'], unit='s')
            df_m15.set_index('time', inplace=True)
            
            # 3. Analyse Structure M1
            ms.analyze(df)
            trend = ms.current_trend
            
            # 4. Premium/Discount
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                time.sleep(5)
                continue
            current_price = tick.bid
            pd_zone = pd_calc.calculate(df_m15)
            
            # 5. Asian Range
            asian_range = kz_detector.calculate_asian_range(df_m15)
            
            # 6. Check Liquidity Sweep
            dist_pts = (current_price - asian_range.high) / 0.1
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] PRIX: {current_price:.1f} | Trend M1: {trend.value} | Zone: {pd_zone.current_zone.value} ({pd_zone.current_percentage:.1f}%)", end='\r')
            
            # Alerte Sweep
            if current_price > asian_range.high:
                print(f"\n🎯 [ALERTE] US30m au-dessus du High Asiatique ({asian_range.high:.1f}) ! Dist: +{dist_pts:.1f} pts")
                print(f"🔥 ATTENTION : On cherche un CHoCH M1 baissier pour valider l'entrée vendeuse.")
            
            # Alerte Reversal
            if trend == Trend.BEARISH and pd_zone.current_percentage > 80:
                 print(f"\n🚨 [SIGNAL] US30m CHoCH Baissier détecté en zone de surchauffe ({pd_zone.current_percentage:.1f}%) !")
                 print(f"💡 Direction: SELL | Target: Equilibrium ({pd_zone.equilibrium:.1f})")

            time.sleep(5)

    except KeyboardInterrupt:
        print("\nArrêt du monitoring.")
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    monitor_us30()
