"""
Intermarket Analyzer - Analyse des corrélations inter-marchés
Analyse DXY, VIX, Yields, Indices pour contexte macro

Author: SMC Bot Team
Date: 2026-01-07
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from loguru import logger
import pandas as pd
import numpy as np

# yfinance pour données gratuites
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    logger.warning("⚠️ yfinance non installé. Installez avec: pip install yfinance")


class IntermarketAnalyzer:
    """
    Analyse les corrélations inter-marchés pour contexte directionnel.
    
    Règles fondamentales du Forex/Commodities:
    - DXY ↑ → EUR/GBP ↓, Gold ↓
    - VIX ↑ (Risk-off) → USD/JPY ↓, USD/CHF ↑, Gold ↑
    - US30 ↑ (Risk-on) → USD/JPY ↑, Commodities ↑
    - US10Y ↑ → USD ↑ (carry trade)
    
    Usage:
        >>> analyzer = IntermarketAnalyzer(config)
        >>> score = analyzer.get_score("EURUSD")  # -100 à +100
        >>> # Score positif = Intermarket bullish
        >>> # Score négatif = Intermarket bearish
    
    Attributes:
        config (Dict): Configuration du bot
        enabled (bool): Si l'analyseur est activé
        cache (Dict): Cache des données de marché
    """
    
    # Corrélations théoriques (basées sur l'économie)
    # Format: {symbole: {asset_corrélé: coefficient}}
    CORRELATIONS = {
        "EURUSD": {
            "DXY": -0.95,      # Dollar Index (inverse très fort)
            "US10Y": -0.60,    # Yields US → USD strength
            "VIX": 0.30,       # Risk-off léger positif EUR (safe haven modéré)
        },
        "EURUSDm": {
            "DXY": -0.95,
            "US10Y": -0.60,
            "VIX": 0.30,
        },
        "GBPUSD": {
            "DXY": -0.92,      # Corrélation DXY très forte
            "US10Y": -0.55,
            "VIX": 0.25,       # Moins safe haven qu'EUR
        },
        "GBPUSDm": {
            "DXY": -0.92,
            "US10Y": -0.55,
            "VIX": 0.25,
        },
        "USDJPY": {
            "US30": 0.70,      # Risk-on proxy fort
            "VIX": -0.75,      # Risk-off = JPY strength (safe haven)
            "US10Y": 0.65,     # Carry trade (yields hauts → JPY faible)
        },
        "USDJPYm": {
            "US30": 0.70,
            "VIX": -0.75,
            "US10Y": 0.65,
        },
        "XAUUSD": {
            "DXY": -0.85,      # USD strength = Gold weakness
            "US10Y": -0.70,    # Real yields négatif = Gold bullish
            "VIX": 0.60,       # Safe haven fort
        },
        "XAUUSDm": {
            "DXY": -0.85,
            "US10Y": -0.70,
            "VIX": 0.60,
        },
        "XAGUSD": {
            "DXY": -0.75,
            "XAUUSD": 0.80,    # Suit l'or
            "VIX": 0.50,
        },
        "XAGUSDm": {
            "DXY": -0.75,
            "XAUUSD": 0.80,
            "VIX": 0.50,
        },
        "AUDUSD": {
            "DXY": -0.85,
            "US30": 0.60,      # Risk-on currency
            "VIX": -0.55,      # Risk-off = AUD faible
        },
        "AUDUSDm": {
            "DXY": -0.85,
            "US30": 0.60,
            "VIX": -0.55,
        },
    }
    
    # Mapping des assets aux symboles yfinance
    ASSET_TO_YFINANCE = {
        "DXY": "DX-Y.NYB",     # Dollar Index
        "VIX": "^VIX",         # Volatilité
        "US10Y": "^TNX",       # Treasury 10 ans
        "US30": "^DJI",        # Dow Jones
        "USTEC": "^IXIC",      # NASDAQ
        "SPX": "^GSPC",        # S&P 500
        "XAUUSD": "GC=F",      # Gold Futures
    }
    
    def __init__(self, config: Dict, mt5_api=None):
        """
        Initialise l'analyseur intermarket.
        
        Args:
            config: Configuration complète du bot
            mt5_api: Client MT5Connector pour données temps réel
        """
        self.config = config
        self.mt5_api = mt5_api
        intermarket_config = config.get('fundamental', {}).get('intermarket', {})
        
        self.enabled = intermarket_config.get('enabled', False)
        self.risk_off_vix_threshold = intermarket_config.get('risk_off_vix_threshold', 20)
        
        # Liste des symboles MT5 pour DXY
        self.mt5_dxy_symbols = ['DXYm', 'USDX', 'USDXm', 'DXY', 'USDXOFm']
        
        # Cache des données (clé: asset, valeur: DataFrame)
        self.cache = {}
        self.cache_expiry = timedelta(minutes=15)  # Rafraîchir toutes les 15min
        self.last_fetch = {}
        
        if not self.enabled:
            logger.info("🔗 Intermarket Analyzer: DÉSACTIVÉ (config)")
            return
        
        logger.info(f"🔗 Intermarket Analyzer: ACTIVÉ")
        if self.mt5_api:
            logger.info("   📈 Source: MT5 (Hybride temps réel)")
        else:
            logger.info("   📈 Source: yfinance uniquement")
        logger.info(f"   🚨 VIX Risk-off threshold: {self.risk_off_vix_threshold}")
    
    def get_score(self, symbol: str) -> float:
        """
        Calcule un score intermarket (-100 à +100).
        
        Méthode:
        1. Récupérer trends des actifs corrélés (DXY, VIX, etc.)
        2. Appliquer les corrélations configurées
        3. Pondérer pour obtenir score final
        
        Args:
            symbol: Symbole à analyser (ex: "EURUSD")
        
        Returns:
            Score -100 (bearish fort) à +100 (bullish fort)
        
        Example:
            >>> score = analyzer.get_score("EURUSD")
            >>> if score > 50:
            ...     print("Intermarket bullish fort pour EUR")
            >>> elif score < -50:
            ...     print("Intermarket bearish fort")
        """
        if not self.enabled or symbol not in self.CORRELATIONS:
            return 0.0
        
        try:
            corr_config = self.CORRELATIONS[symbol]
            total_score = 0.0
            weights_sum = 0.0
            details = []
            
            for asset, correlation_coef in corr_config.items():
                # Récupérer la tendance de l'actif corrélé (-1, 0, +1)
                asset_trend = self._get_asset_trend(asset)
                
                if asset_trend is None:
                    continue  # Skip si pas de données
                
                # Score = tendance * corrélation
                # Exemple: DXY bullish (+1) * corr EURUSD (-0.95) = -0.95
                contribution = asset_trend * correlation_coef
                
                weight = abs(correlation_coef)
                total_score += contribution * weight
                weights_sum += weight
                
                # Détails pour logging
                trend_str = "↑" if asset_trend > 0 else ("↓" if asset_trend < 0 else "→")
                details.append(f"{asset}{trend_str}")
            
            # Normaliser et ramener à -100/+100
            if weights_sum > 0:
                normalized_score = (total_score / weights_sum) * 100
            else:
                normalized_score = 0.0
            
            logger.debug(f"🔗 {symbol} Intermarket: {normalized_score:.1f} "
                        f"({', '.join(details)})")
            
            return normalized_score
            
        except Exception as e:
            logger.error(f"🔗 Erreur Intermarket {symbol}: {e}")
            return 0.0
    
    def _get_asset_trend(self, asset: str) -> Optional[float]:
        """
        Détermine la tendance d'un actif (-1, 0, +1).
        
        Méthode: EMA 50 vs EMA 200 (Golden/Death Cross)
        - Prix > EMA200 et EMA50 > EMA200 → +1 (bullish)
        - Prix < EMA200 et EMA50 < EMA200 → -1 (bearish)
        - Sinon → 0 (ranging/neutre)
        
        Args:
            asset: Nom de l'asset (DXY, VIX, US10Y, etc.)
        
        Returns:
            -1 (bearish), 0 (neutre), +1 (bullish), None (erreur)
        """
        try:
            # Vérifier cache
            cache_key = asset
            if cache_key in self.cache:
                last_fetch = self.last_fetch.get(cache_key)
                if last_fetch and (datetime.now() - last_fetch) < self.cache_expiry:
                    df = self.cache[cache_key]
                else:
                    df = self._fetch_asset_data(asset)
            else:
                df = self._fetch_asset_data(asset)
            
            if df is None or df.empty:
                return None
            
            # Calculer EMAs
            df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
            df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
            
            # Dernières valeurs
            current_price = df['Close'].iloc[-1]
            ema50 = df['EMA50'].iloc[-1]
            ema200 = df['EMA200'].iloc[-1]
            
            # Déterminer tendance
            if current_price > ema200 and ema50 > ema200:
                trend = 1.0  # Bullish
            elif current_price < ema200 and ema50 < ema200:
                trend = -1.0  # Bearish
            else:
                trend = 0.0  # Neutre/Ranging
            
            logger.debug(f"🔗 {asset}: Price={current_price:.2f}, "
                        f"EMA50={ema50:.2f}, EMA200={ema200:.2f} → Trend={trend}")
            
            return trend
            
        except Exception as e:
            logger.debug(f"🔗 Erreur trend {asset}: {e}")
            return None
    
    def _fetch_asset_data(self, asset: str) -> Optional[pd.DataFrame]:
        """
        Récupère les données d'un asset via MT5 (si possible) ou yfinance.
        """
        # 1. Tenter MT5 pour le DXY (plus réactif)
        if asset == "DXY" and self.mt5_api:
            for mt5_sym in self.mt5_dxy_symbols:
                try:
                    df = self.mt5_api.get_rates(mt5_sym, "D1", 250)
                    if df is not None and not df.empty:
                        # Harmoniser colonnes MT5 vers yfinance pour _get_asset_trend
                        df = df.rename(columns={'close': 'Close', 'high': 'High', 'low': 'Low', 'open': 'Open'})
                        self.cache[asset] = df
                        self.last_fetch[asset] = datetime.now()
                        return df
                except Exception as e:
                    continue

        # 2. Fallback yfinance
        if not YFINANCE_AVAILABLE:
            return None
            
        try:
            # Mapper au symbole yfinance
            yf_symbol = self.ASSET_TO_YFINANCE.get(asset, asset)
            
            logger.debug(f"🔗 Fetch yfinance: {asset} ({yf_symbol})")
            
            # Télécharger 6 mois de données (pour EMA200)
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(period="6mo", interval="1d")
            
            if df.empty:
                logger.warning(f"🔗 Pas de données yfinance pour {asset}")
                return None
            
            # Mettre en cache
            self.cache[asset] = df
            self.last_fetch[asset] = datetime.now()
            
            return df
            
        except Exception as e:
            logger.warning(f"🔗 Erreur fetch {asset}: {e}")
            return None
    
    def get_risk_sentiment(self) -> str:
        """
        Détermine le sentiment risk-on / risk-off global.
        
        Indicateurs:
        - VIX > 20 → Risk-off
        - DXY bullish + VIX élevé → Flight to safety
        - US30 > EMA200 + VIX < 15 → Risk-on
        
        Returns:
            "RISK_ON", "RISK_OFF", ou "NEUTRAL"
        
        Example:
            >>> sentiment = analyzer.get_risk_sentiment()
            >>> if sentiment == "RISK_OFF":
            ...     print("Éviter pairs risquées (AUD, NZD)")
        """
        if not self.enabled:
            return "NEUTRAL"
        
        try:
            # Récupérer VIX
            vix_value = self._get_current_value("VIX")
            
            if vix_value is None:
                return "NEUTRAL"
            
            # Règles simples
            if vix_value > self.risk_off_vix_threshold:
                logger.info(f"🔗 Risk Sentiment: RISK-OFF (VIX={vix_value:.1f})")
                return "RISK_OFF"
            elif vix_value < 15:
                logger.info(f"🔗 Risk Sentiment: RISK-ON (VIX={vix_value:.1f})")
                return "RISK_ON"
            else:
                logger.info(f"🔗 Risk Sentiment: NEUTRAL (VIX={vix_value:.1f})")
                return "NEUTRAL"
            
        except Exception as e:
            logger.error(f"🔗 Erreur risk sentiment: {e}")
            return "NEUTRAL"
    
    def _get_current_value(self, asset: str) -> Optional[float]:
        """
        Récupère la valeur actuelle d'un asset.
        
        Args:
            asset: Nom de l'asset
        
        Returns:
            Valeur en float ou None
        """
        try:
            df = self._fetch_asset_data(asset)
            if df is not None and not df.empty:
                return df['Close'].iloc[-1]
            return None
        except:
            return None
    
    def get_dxy_bias(self) -> str:
        """
        Retourne le biais du Dollar Index (simplifié).
        
        Returns:
            "BULLISH", "BEARISH", ou "NEUTRAL"
        """
        if not self.enabled:
            return "NEUTRAL"
        
        dxy_trend = self._get_asset_trend("DXY")
        
        if dxy_trend is None:
            return "NEUTRAL"
        elif dxy_trend > 0:
            return "BULLISH"
        elif dxy_trend < 0:
            return "BEARISH"
        else:
            return "NEUTRAL"
    
    def get_analysis_summary(self, symbol: str) -> Dict:
        """
        Retourne un résumé complet de l'analyse intermarket.
        
        Args:
            symbol: Symbole à analyser
        
        Returns:
            Dict avec:
                - score: Score intermarket
                - assets: Dict des trends par asset
                - risk_sentiment: Risk-on/off
                - dxy_bias: Bias DXY
        
        Example:
            >>> summary = analyzer.get_analysis_summary("EURUSD")
            >>> {
            ...     'score': -45.2,
            ...     'assets': {'DXY': 1.0, 'US10Y': 0.5, 'VIX': 0.0},
            ...     'risk_sentiment': 'NEUTRAL',
            ...     'dxy_bias': 'BULLISH'
            ... }
        """
        if not self.enabled or symbol not in self.CORRELATIONS:
            return {
                'score': 0.0,
                'assets': {},
                'risk_sentiment': 'NEUTRAL',
                'dxy_bias': 'NEUTRAL'
            }
        
        # Score principal
        score = self.get_score(symbol)
        
        # Trends des assets individuels
        assets_trends = {}
        corr_config = self.CORRELATIONS[symbol]
        for asset in corr_config.keys():
            trend = self._get_asset_trend(asset)
            if trend is not None:
                assets_trends[asset] = trend
        
        # Sentiments
        risk_sentiment = self.get_risk_sentiment()
        dxy_bias = self.get_dxy_bias()
        
        return {
            'score': score,
            'assets': assets_trends,
            'risk_sentiment': risk_sentiment,
            'dxy_bias': dxy_bias
        }
    
    def clear_cache(self):
        """Vide le cache (utile pour forcer refresh)."""
        self.cache = {}
        self.last_fetch = {}
        logger.info("🔗 Cache intermarket vidé")
