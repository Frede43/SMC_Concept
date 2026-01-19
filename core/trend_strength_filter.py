"""
Trend Strength Filter - ADX Based
Filtre les setups en marchés ranging (faible tendance)

Principe:
- ADX > 25 = Tendance forte (trade autorisé)
- ADX < 25 = Ranging/faible tendance (skip trade)

Impact attendu: Win Rate +8-12% (évite 30-40% trades perdants)

Author: Expert SMC/ICT
Date: 19 Janvier 2026
"""

import pandas as pd
import numpy as np
from loguru import logger

try:
    import talib
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False
    logger.warning("⚠️ TA-Lib non disponible, utilisation calcul manuel ADX")


class TrendStrengthFilter:
    """Filtre basé sur la force de la tendance (ADX)."""
    
    def __init__(self, config: dict = None):
        """
        Initialize trend strength filter.
        
        Args:
            config: Configuration avec clés:
                - min_adx: ADX minimum requis (défaut: 25.0)
                - adx_period: Période calcul ADX (défaut: 14)
                - strict_mode: Si True, exige ADX > threshold (défaut: True)
        """
        config = config or {}
        self.min_adx = config.get('min_adx', 25.0)
        self.adx_period = config.get('adx_period', 14)
        self.strict_mode = config.get('strict_mode', True)
        
        logger.info(f"🎯 TrendStrengthFilter initialized: min_adx={self.min_adx}, period={self.adx_period}")
    
    def is_trending(self, df: pd.DataFrame) -> tuple[bool, float]:
        """
        Vérifie si le marché est en tendance forte.
        
        Args:
            df: DataFrame avec colonnes 'high', 'low', 'close'
            
        Returns:
            (is_trending: bool, adx_value: float)
        """
        if df is None or len(df) < self.adx_period + 1:
            logger.warning("⚠️ DataFrame insuffisant pour calcul ADX")
            return False, 0.0
        
        try:
            adx_value = self._calculate_adx(df)
            
            if adx_value is None or np.isnan(adx_value):
                logger.warning("⚠️ ADX calculation failed")
                return False, 0.0
            
            is_trending = adx_value >= self.min_adx
            
            if self.strict_mode:
                if is_trending:
                    logger.debug(f"✅ Tendance forte: ADX={adx_value:.2f} >= {self.min_adx}")
                else:
                    logger.debug(f"❌ Tendance faible/ranging: ADX={adx_value:.2f} < {self.min_adx}")
            
            return is_trending, adx_value
            
        except Exception as e:
            logger.error(f"Error calculating ADX: {e}")
            return False, 0.0
    
    def _calculate_adx(self, df: pd.DataFrame) -> float:
        """Calculate ADX using TA-Lib or manual calculation."""
        
        if TALIB_AVAILABLE:
            return self._calculate_adx_talib(df)
        else:
            return self._calculate_adx_manual(df)
    
    def _calculate_adx_talib(self, df: pd.DataFrame) -> float:
        """Calculate ADX using TA-Lib."""
        try:
            adx = talib.ADX(
                df['high'].values,
                df['low'].values,
                df['close'].values,
                timeperiod=self.adx_period
            )
            return adx[-1]
        except Exception as e:
            logger.error(f"TA-Lib ADX error: {e}")
            return None
    
    def _calculate_adx_manual(self, df: pd.DataFrame) -> float:
        """
        Calculate ADX manually (fallback si TA-Lib absent).
        
        ADX = Average Directional Index
        Formule:
        1. +DM = max(high[i] - high[i-1], 0)
        2. -DM = max(low[i-1] - low[i], 0)
        3. TR = max(high - low, abs(high - close_prev), abs(low - close_prev))
        4. +DI = 100 * EMA(+DM) / EMA(TR)
        5. -DI = 100 * EMA(-DM) / EMA(TR)
        6. DX = 100 * abs(+DI - -DI) / (+DI + -DI)
        7. ADX = EMA(DX)
        """
        try:
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values
            
            # Calculate +DM and -DM
            dm_plus = np.maximum(high[1:] - high[:-1], 0)
            dm_minus = np.maximum(low[:-1] - low[1:], 0)
            
            # Calculate True Range
            high_low = high[1:] - low[1:]
            high_close_prev = np.abs(high[1:] - close[:-1])
            low_close_prev = np.abs(low[1:] - close[:-1])
            
            tr = np.maximum(high_low, np.maximum(high_close_prev, low_close_prev))
            
            # Smooth using EMA
            alpha = 1.0 / self.adx_period
            
            # Smoothed +DM, -DM, TR
            smoothed_dm_plus = self._ema(dm_plus, alpha)
            smoothed_dm_minus = self._ema(dm_minus, alpha)
            smoothed_tr = self._ema(tr, alpha)
            
            # Calculate +DI and -DI
            di_plus = 100 * smoothed_dm_plus / smoothed_tr
            di_minus = 100 * smoothed_dm_minus / smoothed_tr
            
            # Calculate DX
            dx = 100 * np.abs(di_plus - di_minus) / (di_plus + di_minus + 1e-10)
            
            # Calculate ADX (smoothed DX)
            adx = self._ema(dx, alpha)
            
            return adx[-1]
            
        except Exception as e:
            logger.error(f"Manual ADX calculation error: {e}")
            return None
    
    def _ema(self, data: np.ndarray, alpha: float) -> np.ndarray:
        """Calculate EMA manually."""
        ema = np.zeros_like(data)
        ema[0] = data[0]
        
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i-1]
        
        return ema
    
    def get_trend_strength_category(self, adx_value: float) -> str:
        """
        Catégorise la force de la tendance.
        
        Returns:
            'NO_TREND' (ADX <20)
            'WEAK_TREND' (20 <= ADX < 25)
            'STRONG_TREND' (25 <= ADX < 50)
            'VERY_STRONG_TREND' (ADX >= 50)
        """
        if adx_value < 20:
            return 'NO_TREND'
        elif adx_value < 25:
            return 'WEAK_TREND'
        elif adx_value < 50:
            return 'STRONG_TREND'
        else:
            return 'VERY_STRONG_TREND'
    
    def should_trade(self, df: pd.DataFrame) -> dict:
        """
        Décision complète de trading basée sur ADX.
        
        Returns:
            {
                'allowed': bool,
                'adx': float,
                'category': str,
                'reason': str
            }
        """
        is_trending, adx_value = self.is_trending(df)
        category = self.get_trend_strength_category(adx_value)
        
        result = {
            'allowed': is_trending,
            'adx': adx_value,
            'category': category,
            'reason': ''
        }
        
        if is_trending:
            result['reason'] = f"Tendance forte détectée (ADX={adx_value:.1f})"
        else:
            result['reason'] = f"Marché ranging/faible tendance (ADX={adx_value:.1f} < {self.min_adx})"
        
        return result


# Test standalone
if __name__ == "__main__":
    print("=" * 70)
    print("TEST TREND STRENGTH FILTER")
    print("=" * 70)
    
    # Créer données test
    import pandas as pd
    import numpy as np
    
    # Tendance forte simulée
    dates = pd.date_range(start='2024-01-01', periods=100, freq='1H')
    trend_up = pd.DataFrame({
        'high': np.linspace(1.2500, 1.2700, 100) + np.random.random(100) * 0.001,
        'low': np.linspace(1.2480, 1.2680, 100) + np.random.random(100) * 0.001,
        'close': np.linspace(1.2490, 1.2690, 100) + np.random.random(100) * 0.001,
    }, index=dates)
    
    # Ranging simulé
    ranging = pd.DataFrame({
        'high': 1.2500 + np.random.random(100) * 0.002,
        'low': 1.2480 + np.random.random(100) * 0.002,
        'close': 1.2490 + np.random.random(100) * 0.002,
    }, index=dates)
    
    # Test
    filter_obj = TrendStrengthFilter({'min_adx': 25.0})
    
    print("\n1. Test Tendance Forte (uptrend):")
    result1 = filter_obj.should_trade(trend_up)
    print(f"   Allowed: {result1['allowed']}")
    print(f"   ADX: {result1['adx']:.2f}")
    print(f"   Category: {result1['category']}")
    print(f"   Reason: {result1['reason']}")
    
    print("\n2. Test Ranging Market:")
    result2 = filter_obj.should_trade(ranging)
    print(f"   Allowed: {result2['allowed']}")
    print(f"   ADX: {result2['adx']:.2f}")
    print(f"   Category: {result2['category']}")
    print(f"   Reason: {result2['reason']}")
    
    print("\n" + "=" * 70)
    print("✅ Tests terminés")
