"""
EXEMPLE DE MIGRATION VECTORBT - SMC Strategy
Montre comment migrer votre stratégie SMC vers VectorBT pour x10-x50 vitesse

⚠️ PROOF OF CONCEPT - Adapter à votre stratégie complète
"""

# Installation requise:
# pip install vectorbt

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import yaml

try:
    import vectorbt as vbt
    VECTORBT_AVAILABLE = True
except ImportError:
    VECTORBT_AVAILABLE = False
    print("[X] VectorBT non installe. Installez avec: pip install vectorbt")


def smc_strategy_vectorized(data: pd.DataFrame, config: dict) -> tuple:
    """
    Version vectorisée simplifiée de la stratégie SMC.
    
    Démontre les concepts clés:
    - FVG Detection vectorisée
    - MSS Detection vectorisée  
    - Premium/Discount zones vectorisées
    - Signal generation vectorisée
    
    Returns:
        (entries, exits) - Boolean Series pour achats/ventes
    """
    
    # Paramètres
    min_fvg_pips = config.get('min_fvg_pips', 5)
    pip_value = config.get('pip_value', 0.0001)
    min_gap = min_fvg_pips * pip_value
    
    # Préparer arrays NumPy (ultra-rapide)
    highs = data['High'].values
    lows = data['Low'].values
    closes = data['Close'].values
    opens = data['Open'].values
    
    n = len(data)
    
    # ==================== FVG DETECTION VECTORISÉE ====================
    # Bullish FVG: low[i] > high[i-2]
    # Détection en une ligne au lieu d'une loop
    
    bullish_fvg = np.zeros(n, dtype=bool)
    bearish_fvg = np.zeros(n, dtype=bool)
    
    if n >= 3:
        # Vectorized comparison (toutes les bougies en une passe)
        bull_gaps = lows[2:] - highs[:-2]
        bear_gaps = lows[:-2] - highs[2:]
        
        # Trouver où gaps > min
        bull_valid = bull_gaps >= min_gap
        bear_valid = bear_gaps >= min_gap
        
        # Créer signal FVG à l'index de la 3ème bougie
        bullish_fvg[2:] = bull_valid
        bearish_fvg[2:] = bear_valid
    
    # ==================== MSS DETECTION VECTORISÉE ====================
    # Market Structure Shift = Break of Structure
    # Version simplifiée: Nouveau high/low sur N bougies
    
    lookback = 20
    mss_bullish = np.zeros(n, dtype=bool)
    mss_bearish = np.zeros(n, dtype=bool)
    
    # Rolling max/min avec pandas (vectorisé en interne)
    rolling_high = data['High'].rolling(lookback).max().shift(1).values
    rolling_low = data['Low'].rolling(lookback).min().shift(1).values
    
    # MSS = Break au-dessus du max récent (bullish) ou en-dessous du min (bearish)
    mss_bullish = highs > rolling_high
    mss_bearish = lows < rolling_low
    
    # ==================== PREMIUM/DISCOUNT ZONES ====================
    # Calculer high/low sur 50 dernières bougies
    swing_lookback = 50
    swing_high = data['High'].rolling(swing_lookback).max().values
    swing_low = data['Low'].rolling(swing_lookback).min().values
    swing_range = swing_high - swing_low
    
    # Zones
    equilibrium = (swing_high + swing_low) / 2
    premium_threshold = equilibrium + (swing_range * 0.25)  # 75% du range
    discount_threshold = equilibrium - (swing_range * 0.25)  # 25% du range
    
    in_premium = closes > premium_threshold
    in_discount = closes < discount_threshold
    
    # ==================== SIGNAL GENERATION ====================
    # BUY: FVG Bullish + MSS Bullish + In Discount
    # SELL: FVG Bearish + MSS Bearish + In Premium
    
    buy_signals = bullish_fvg & mss_bullish & in_discount
    sell_signals = bearish_fvg & mss_bearish & in_premium
    
    # Combiner en signal unique (1=Buy, -1=Sell, 0=Hold)
    # VectorBT utilise des boolean series séparés pour entries/exits
    entries = buy_signals
    exits = sell_signals  # Simplification: exit sur signal opposé
    
    print(f"📊 Signals générés (vectorisé):")
    print(f"   Buy signals: {buy_signals.sum()}")
    print(f"   Sell signals: {sell_signals.sum()}")
    
    return pd.Series(entries, index=data.index), pd.Series(exits, index=data.index)


def run_vectorbt_backtest(symbol: str = 'EURUSDm', start_date: datetime = None, end_date: datetime = None):
    """
    Lance un backtest VectorBT avec la stratégie SMC vectorisée.
    
    ULTRA-RAPIDE: 2 ans de M15 en 30 secondes à 2 minutes.
    """
    
    if not VECTORBT_AVAILABLE:
        print("❌ Impossible de lancer - VectorBT non installé")
        return None
    
    print("\n" + "="*70)
    print("🚀 BACKTEST VECTORBT - SMC Strategy")
    print("="*70 + "\n")
    
    # Dates par défaut
    if end_date is None:
        end_date = datetime.now()
    if start_date is None:
        start_date = end_date - timedelta(days=365)  # 1 an
    
    # ==================== CHARGER DONNÉES ====================
    print(f"📥 Chargement données {symbol}...")
    print(f"   Période: {start_date.date()} → {end_date.date()}")
    
    # Option 1: Charger depuis vos fichiers Parquet
    ROOT_DIR = Path(__file__).parent
    cache_key = f"{symbol}_M15_{start_date.date()}_{end_date.date()}"
    parquet_file = ROOT_DIR / 'backtest' / 'data' / f"{cache_key}.parquet"
    
    if parquet_file.exists():
        print(f"   ✅ Chargé depuis cache: {parquet_file.name}")
        data = pd.read_parquet(parquet_file)
    else:
        # Option 2: Télécharger via MT5 (votre DataManager)
        print(f"   ⚠️ Cache non trouvé, utiliser prepare_backtest_data.py d'abord")
        print(f"   OU télécharger via yfinance pour demo:")
        
        # Exemple avec yfinance (pour Forex, utiliser votre MT5)
        # import yfinance as yf
        # ticker = symbol.replace('m', '').replace('USD', 'USD=X')
        # data = yf.download(ticker, start=start_date, end=end_date, interval='15m')
        
        return None
    
    # Normaliser colonnes (VectorBT utilise majuscules)
    if 'open' in data.columns:
        data = data.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
    
    print(f"   📊 {len(data):,} bougies chargées")
    
    # ==================== CONFIGURATION ====================
    config_path = ROOT_DIR / 'config' / 'settings.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    strategy_config = {
        'min_fvg_pips': 5,
        'pip_value': 0.0001,
        'sl_multiplier': 1.5,
        'tp_multiplier': 3.0,
    }
    
    # ==================== GÉNÉRATION SIGNAUX ====================
    print(f"\n⚡ Génération signaux SMC (vectorisé)...")
    import time
    t0 = time.time()
    
    entries, exits = smc_strategy_vectorized(data, strategy_config)
    
    t1 = time.time()
    print(f"   ✅ Signaux générés en {t1-t0:.2f}s (VECTORISÉ)")
    
    # ==================== BACKTEST VECTORBT ====================
    print(f"\n🔄 Lancement backtest VectorBT...")
    t0 = time.time()
    
    # Portfolio simulation (ultra-rapide)
    pf = vbt.Portfolio.from_signals(
        close=data['Close'],
        entries=entries,
        exits=exits,
        init_cash=10000,
        fees=0.0002,  # 2 pips spread (0.02%)
        slippage=0.0001,  # 1 pip slippage
        freq='15min'
    )
    
    t1 = time.time()
    print(f"   ✅ Backtest complété en {t1-t0:.2f}s")
    
    # ==================== RÉSULTATS ====================
    print("\n" + "="*70)
    print("📊 RÉSULTATS")
    print("="*70 + "\n")
    
    stats = pf.stats()
    
    # Afficher métriques clés
    print(f"💰 PERFORMANCE:")
    print(f"   Total Return: {stats['Total Return [%]']:.2f}%")
    print(f"   Total Trades: {stats['Total Trades']}")
    print(f"   Win Rate: {stats['Win Rate [%]']:.2f}%")
    print(f"   Max Drawdown: {stats['Max Drawdown [%]']:.2f}%")
    print(f"   Sharpe Ratio: {stats['Sharpe Ratio']:.3f}")
    
    print(f"\n💵 TRADES:")
    print(f"   Winning Trades: {stats['Total Winning Trades']}")
    print(f"   Losing Trades: {stats['Total Losing Trades']}")
    print(f"   Avg Win: ${stats['Avg Winning Trade [%]']:.2f}")
    print(f"   Avg Loss: ${stats['Avg Losing Trade [%]']:.2f}")
    
    # ==================== VISUALISATION ====================
    print(f"\n📈 Génération graphiques...")
    
    # Créer répertoire résultats
    results_dir = ROOT_DIR / 'backtest' / 'results' / 'vectorbt'
    results_dir.mkdir(parents=True, exist_ok=True)
    
    # Equity curve
    fig = pf.plot()
    fig_file = results_dir / f'equity_curve_{symbol}_{start_date.date()}.html'
    fig.write_html(str(fig_file))
    print(f"   ✅ Equity curve: {fig_file}")
    
    # Sauvegarder stats complètes
    stats_file = results_dir / f'stats_{symbol}_{start_date.date()}.txt'
    with open(stats_file, 'w') as f:
        f.write(str(stats))
    print(f"   ✅ Stats complètes: {stats_file}")
    
    print("\n" + "="*70)
    print("✅ BACKTEST VECTORBT TERMINÉ")
    print("="*70 + "\n")
    
    return pf, stats


def compare_performance():
    """
    Compare la performance entre votre backtester custom et VectorBT.
    """
    
    print("\n" + "="*70)
    print("📊 COMPARAISON PERFORMANCE")
    print("="*70 + "\n")
    
    print("Pour comparer équitablement:")
    print("\n1. Lancer votre backtest custom:")
    print("   python run_backtest_2024.py")
    print("   Noter le temps d'exécution\n")
    
    print("2. Lancer backtest VectorBT:")
    print("   python vectorbt_example.py")
    print("   Noter le temps d'exécution\n")
    
    print("3. Comparer:")
    print("   - Durée totale")
    print("   - Nombre de trades (doivent être similaires)")
    print("   - Win Rate (doivent être proches)")
    print("   - P&L total (vérifier cohérence)\n")
    
    print("Gain attendu VectorBT: x10 à x50 vitesse")
    print("Exemple: 20 min → 30 secondes\n")


if __name__ == "__main__":
    
    if not VECTORBT_AVAILABLE:
        print("\n" + "="*70)
        print("⚠️ INSTALLATION REQUISE")
        print("="*70 + "\n")
        print("VectorBT n'est pas installé. Pour l'installer:")
        print("\n  pip install vectorbt\n")
        print("Puis relancer ce script.")
        exit(1)
    
    # Lancer backtest exemple
    print("\n🎯 Lancement backtest VectorBT exemple...")
    print("   (Version simplifiée pour démonstration)\n")
    
    try:
        pf, stats = run_vectorbt_backtest(
            symbol='EURUSDm',
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 12, 31)
        )
        
        if pf is not None:
            print("\n🎉 SUCCÈS! VectorBT fonctionne.")
            print("\n📝 PROCHAINES ÉTAPES:")
            print("   1. Adapter ce code à votre stratégie complète")
            print("   2. Ajouter tous vos filtres SMC (iFVG, Sweeps, etc.)")
            print("   3. Vectoriser tous les indicateurs")
            print("   4. Comparer résultats avec votre backtest actuel")
            print("   5. Valider équivalence avant migration complète\n")
    
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        print("\nVérifiez:")
        print("  - Les données Parquet sont disponibles (backtest/data/)")
        print("  - Le fichier config/settings.yaml existe")
        print("  - VectorBT est bien installé\n")
        import traceback
        traceback.print_exc()
