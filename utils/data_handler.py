"""
Data Handler
Gestion et préparation des données OHLC
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple
from loguru import logger


class DataHandler:
    """
    Gestion des données de marché.
    
    Fonctionnalités:
    - Validation des données
    - Calcul d'indicateurs techniques
    - Resampling des timeframes
    """
    
    @staticmethod
    def validate_ohlc(df: pd.DataFrame) -> bool:
        """Valide qu'un DataFrame contient les colonnes OHLC requises."""
        required = ['open', 'high', 'low', 'close']
        missing = [col for col in required if col not in df.columns]
        
        if missing:
            logger.warning(f"Missing columns: {missing}")
            return False
        
        if df.empty:
            logger.warning("DataFrame is empty")
            return False
        
        return True
    
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calcule l'Average True Range."""
        high = df['high']
        low = df['low']
        close = df['close'].shift(1)
        
        tr1 = high - low
        tr2 = abs(high - close)
        tr3 = abs(low - close)
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr
    
    @staticmethod
    def calculate_ema(series: pd.Series, period: int) -> pd.Series:
        """Calcule l'Exponential Moving Average."""
        return series.ewm(span=period, adjust=False).mean()
    
    @staticmethod
    def calculate_sma(series: pd.Series, period: int) -> pd.Series:
        """Calcule la Simple Moving Average."""
        return series.rolling(window=period).mean()
    
    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calcule le RSI."""
        delta = df['close'].diff()
        
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    @staticmethod
    def resample_timeframe(df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
        """
        Resample les données vers un timeframe supérieur.
        
        Args:
            df: DataFrame avec index DatetimeIndex
            target_tf: Timeframe cible ('H1', 'H4', 'D1', etc.)
        """
        tf_map = {
            'M5': '5T',
            'M15': '15T',
            'M30': '30T',
            'H1': '1H',
            'H4': '4H',
            'D1': '1D',
            'W1': '1W'
        }
        
        rule = tf_map.get(target_tf)
        if rule is None:
            logger.warning(f"Unknown timeframe: {target_tf}")
            return df
        
        resampled = df.resample(rule).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum' if 'volume' in df.columns else 'first'
        }).dropna()
        
        return resampled
    
    @staticmethod
    def get_swing_points(df: pd.DataFrame, strength: int = 5) -> Tuple[list, list]:
        """Identifie les swing highs et lows."""
        swing_highs = []
        swing_lows = []
        
        for i in range(strength, len(df) - strength):
            # Check swing high
            is_high = True
            for j in range(1, strength + 1):
                if df.iloc[i]['high'] <= df.iloc[i-j]['high'] or df.iloc[i]['high'] <= df.iloc[i+j]['high']:
                    is_high = False
                    break
            if is_high:
                swing_highs.append({
                    'index': i,
                    'price': df.iloc[i]['high'],
                    'time': df.index[i] if isinstance(df.index, pd.DatetimeIndex) else i
                })
            
            # Check swing low
            is_low = True
            for j in range(1, strength + 1):
                if df.iloc[i]['low'] >= df.iloc[i-j]['low'] or df.iloc[i]['low'] >= df.iloc[i+j]['low']:
                    is_low = False
                    break
            if is_low:
                swing_lows.append({
                    'index': i,
                    'price': df.iloc[i]['low'],
                    'time': df.index[i] if isinstance(df.index, pd.DatetimeIndex) else i
                })
        
        return swing_highs, swing_lows
    
    @staticmethod
    def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """Ajoute des indicateurs techniques au DataFrame."""
        df = df.copy()
        
        # ATR
        df['atr'] = DataHandler.calculate_atr(df)
        
        # EMAs
        df['ema_20'] = DataHandler.calculate_ema(df['close'], 20)
        df['ema_50'] = DataHandler.calculate_ema(df['close'], 50)
        df['ema_200'] = DataHandler.calculate_ema(df['close'], 200)
        
        # RSI
        df['rsi'] = DataHandler.calculate_rsi(df)
        
        return df
