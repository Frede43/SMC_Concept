"""
EXEMPLE D'OPTIMISATION NUMBA - Hot-Paths SMC
Montre comment ajouter JIT compilation sur fonctions critiques

Installation: pip install numba

Gain attendu: x2 à x5 sur fonctions optimisées
"""

import numpy as np
import pandas as pd
from numba import njit, prange
import time


# ==================== EXEMPLE 1: FVG DETECTION ====================

def detect_fvg_python(highs, lows, min_gap):
    """Version Python standard (LENTE)"""
    n = len(highs)
    bullish_fvg = []
    bearish_fvg = []
    
    for i in range(2, n):
        # Bullish FVG
        gap = lows[i] - highs[i-2]
        if gap >= min_gap:
            bullish_fvg.append(i)
        
        # Bearish FVG
        gap = lows[i-2] - highs[i]
        if gap >= min_gap:
            bearish_fvg.append(i)
    
    return bullish_fvg, bearish_fvg


@njit
def detect_fvg_numba(highs, lows, min_gap):
    """Version Numba JIT compilée (RAPIDE x3-x5)"""
    n = len(highs)
    bullish_fvg = np.zeros(n, dtype=np.int32)
    bearish_fvg = np.zeros(n, dtype=np.int32)
    
    bull_count = 0
    bear_count = 0
    
    for i in range(2, n):
        # Bullish FVG
        gap = lows[i] - highs[i-2]
        if gap >= min_gap:
            bullish_fvg[bull_count] = i
            bull_count += 1
        
        # Bearish FVG
        gap = lows[i-2] - highs[i]
        if gap >= min_gap:
            bearish_fvg[bear_count] = i
            bear_count += 1
    
    return bullish_fvg[:bull_count], bearish_fvg[:bear_count]


# ==================== EXEMPLE 2: LIQUIDITY SWEEP DETECTION ====================

@njit
def detect_liquidity_sweeps_numba(highs, lows, closes, lookback=20, wick_threshold=0.5):
    """
    Détecte les Liquidity Sweeps avec Numba JIT.
    
    Sweep = Wick > threshold * candle body + rejection
    """
    n = len(highs)
    sweeps = np.zeros(n, dtype=np.int8)  # 1=bullish sweep, -1=bearish sweep
    
    for i in range(lookback, n):
        # Trouver swing high/low sur lookback
        swing_high = highs[i-lookback]
        swing_low = lows[i-lookback]
        
        for j in range(i-lookback+1, i):
            if highs[j] > swing_high:
                swing_high = highs[j]
            if lows[j] < swing_low:
                swing_low = lows[j]
        
        # Candle actuelle
        candle_range = highs[i] - lows[i]
        upper_wick = highs[i] - max(closes[i], closes[i-1] if i > 0 else closes[i])
        lower_wick = min(closes[i], closes[i-1] if i > 0 else closes[i]) - lows[i]
        
        # Bullish Sweep (sweep lows puis rejection)
        if lows[i] < swing_low and lower_wick > wick_threshold * candle_range:
            sweeps[i] = 1
        
        # Bearish Sweep (sweep highs puis rejection)
        elif highs[i] > swing_high and upper_wick > wick_threshold * candle_range:
            sweeps[i] = -1
    
    return sweeps


# ==================== EXEMPLE 3: MSS DETECTION ====================

@njit
def detect_mss_numba(highs, lows, closes, lookback=20):
    """
    Market Structure Shift detection avec Numba.
    
    MSS = Break of significant swing high/low
    """
    n = len(highs)
    mss = np.zeros(n, dtype=np.int8)  # 1=bullish MSS, -1=bearish MSS
    
    for i in range(lookback, n):
        # Rolling high/low
        period_high = highs[i-lookback]
        period_low = lows[i-lookback]
        
        for j in range(i-lookback+1, i):
            if highs[j] > period_high:
                period_high = highs[j]
            if lows[j] < period_low:
                period_low = lows[j]
        
        # Bullish MSS: Break above recent high
        if highs[i] > period_high and closes[i] > closes[i-1]:
            mss[i] = 1
        
        # Bearish MSS: Break below recent low
        elif lows[i] < period_low and closes[i] < closes[i-1]:
            mss[i] = -1
    
    return mss


# ==================== EXEMPLE 4: PARALLEL PROCESSING ====================

@njit(parallel=True)
def calculate_indicators_parallel(highs, lows, closes, volumes):
    """
    Calcule plusieurs indicateurs en parallèle avec Numba.
    
    parallel=True active le multithreading automatique
    """
    n = len(closes)
    
    # Pré-allouer arrays
    atr = np.zeros(n)
    rsi = np.zeros(n)
    ema_fast = np.zeros(n)
    ema_slow = np.zeros(n)
    
    # ATR calculation (simplified)
    for i in prange(1, n):  # prange = parallel range
        true_range = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        atr[i] = (atr[i-1] * 13 + true_range) / 14  # 14-period ATR
    
    # EMA Fast (simplified)
    alpha_fast = 2.0 / (12 + 1)
    ema_fast[0] = closes[0]
    for i in range(1, n):
        ema_fast[i] = closes[i] * alpha_fast + ema_fast[i-1] * (1 - alpha_fast)
    
    # EMA Slow (simplified)
    alpha_slow = 2.0 / (26 + 1)
    ema_slow[0] = closes[0]
    for i in range(1, n):
        ema_slow[i] = closes[i] * alpha_slow + ema_slow[i-1] * (1 - alpha_slow)
    
    return atr, rsi, ema_fast, ema_slow


# ==================== BENCHMARK ====================

def benchmark_fvg_detection():
    """Compare Python vs Numba pour FVG detection"""
    
    print("\n" + "="*70)
    print("🔥 BENCHMARK: FVG Detection")
    print("="*70 + "\n")
    
    # Générer données test (2 ans M15 = ~70,000 bougies)
    n = 70000
    np.random.seed(42)
    highs = np.random.rand(n) * 100 + 1.1000
    lows = highs - np.random.rand(n) * 0.0050
    min_gap = 0.0005
    
    print(f"Dataset: {n:,} bougies (2 ans M15)")
    print(f"Min gap: {min_gap}\n")
    
    # Test Python standard
    print("1️⃣ Python standard (loop)...")
    t0 = time.time()
    bull_py, bear_py = detect_fvg_python(highs, lows, min_gap)
    t_python = time.time() - t0
    print(f"   Durée: {t_python:.3f}s")
    print(f"   FVGs: {len(bull_py)} bull, {len(bear_py)} bear\n")
    
    # Test Numba JIT (première fois = compilation incluse)
    print("2️⃣ Numba JIT (première fois = avec compilation)...")
    t0 = time.time()
    bull_nb, bear_nb = detect_fvg_numba(highs, lows, min_gap)
    t_numba_compile = time.time() - t0
    print(f"   Durée: {t_numba_compile:.3f}s (compilation incluse)")
    print(f"   FVGs: {len(bull_nb)} bull, {len(bear_nb)} bear\n")
    
    # Test Numba (deuxième fois = déjà compilé)
    print("3️⃣ Numba JIT (runs suivants = compilé)...")
    t0 = time.time()
    for _ in range(10):  # 10 runs pour moyenne
        bull_nb, bear_nb = detect_fvg_numba(highs, lows, min_gap)
    t_numba_avg = (time.time() - t0) / 10
    print(f"   Durée moyenne: {t_numba_avg:.3f}s\n")
    
    # Résultats
    print("="*70)
    print("📊 RÉSULTATS")
    print("="*70 + "\n")
    print(f"Python standard:  {t_python:.3f}s")
    print(f"Numba (compilé):  {t_numba_avg:.3f}s")
    print(f"Speedup:          x{t_python/t_numba_avg:.1f} 🚀\n")
    
    print("💡 Note: Numba compile au premier appel (overhead),")
    print("   mais tous les appels suivants sont ultra-rapides.\n")


# ==================== INTÉGRATION DANS VOTRE CODE ====================

def migration_guide():
    """Guide pour migrer vos fonctions vers Numba"""
    
    print("\n" + "="*70)
    print("📘 GUIDE DE MIGRATION NUMBA")
    print("="*70 + "\n")
    
    print("ÉTAPE 1: Identifier les hot-paths")
    print("-" * 70)
    print("Utilisez profile_backtest.py pour trouver les fonctions > 10% du temps:")
    print("  • FVG detection")
    print("  • Liquidity sweep detection")
    print("  • MSS detection")
    print("  • Order block detection\n")
    
    print("ÉTAPE 2: Adapter le code pour Numba")
    print("-" * 70)
    print("Numba supporte:")
    print("  ✅ NumPy arrays")
    print("  ✅ Boucles for/while")
    print("  ✅ Opérations mathématiques")
    print("  ✅ if/else conditions")
    print("  ❌ Pandas DataFrames (convertir en NumPy)")
    print("  ❌ Listes Python (utiliser np.zeros)")
    print("  ❌ Dictionnaires (utiliser arrays structurés)\n")
    
    print("ÉTAPE 3: Conversion type")
    print("-" * 70)
    print("AVANT (Pandas):")
    print("  def detect_fvg(df):")
    print("      for i, row in df.iterrows():")
    print("          ...\n")
    print("APRÈS (Numba):")
    print("  @njit")
    print("  def detect_fvg(highs, lows):")
    print("      for i in range(len(highs)):")
    print("          ...\n")
    
    print("ÉTAPE 4: Wrapper pour compatibilité")
    print("-" * 70)
    print("Créez un wrapper qui convertit DataFrame → NumPy:")
    print("  def detect_fvg_wrapper(df):")
    print("      highs = df['high'].values")
    print("      lows = df['low'].values")
    print("      result = detect_fvg_numba(highs, lows)")
    print("      return result\n")
    
    print("ÉTAPE 5: Tester et valider")
    print("-" * 70)
    print("  1. Comparer résultats avant/après")
    print("  2. Vérifier que signaux sont identiques")
    print("  3. Mesurer speedup avec benchmark")
    print("  4. Intégrer progressivement\n")
    
    print("="*70)
    print("🎯 FONCTIONS PRIORITAIRES À OPTIMISER")
    print("="*70 + "\n")
    print("core/fair_value_gap.py → detect()  [DÉJÀ VECTORISÉ ✅]")
    print("core/liquidity.py → detect_sweeps()  [À OPTIMISER ⚡]")
    print("core/market_structure.py → detect_bos_choch()  [À OPTIMISER ⚡]")
    print("core/order_blocks.py → detect()  [À OPTIMISER ⚡]\n")


if __name__ == "__main__":
    
    try:
        import numba
        print(f"✅ Numba {numba.__version__} installé\n")
    except ImportError:
        print("❌ Numba non installé")
        print("\nInstallez avec: pip install numba\n")
        exit(1)
    
    # Lancer benchmark
    benchmark_fvg_detection()
    
    # Afficher guide
    migration_guide()
    
    print("\n" + "="*70)
    print("📝 PROCHAINES ÉTAPES")
    print("="*70 + "\n")
    print("1. Profiler votre backtest: python profile_backtest.py")
    print("2. Identifier top 3 fonctions lentes")
    print("3. Convertir ces fonctions avec @njit")
    print("4. Benchmarker amélioration")
    print("5. Intégrer dans backtester principal\n")
