"""
⚡ MOMENTUM CONFIRMATION FILTER
Empêche les entrées contre un momentum fort dans les zones extrêmes.

Principe ICT :
"Ne vendez pas une extension finale sans voir un rejet.
 N'achetez pas une chute finale sans voir un rebond."
"""

from typing import Tuple, Optional
import pandas as pd
import numpy as np
from loguru import logger


class MomentumConfirmationFilter:
    """
    Filtre de confirmation pour éviter les entrées prématurées
    dans les zones Premium/Discount extrêmes.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.enabled = self.config.get("momentum_confirmation", {}).get("enabled", True)

        # Seuils configurables (DURCISSEMENT SUITE AUX ÉCHECS)
        self.extreme_premium_threshold = 80.0  # Au-delà de 80% = extrême (Avant: 90)
        self.extreme_discount_threshold = 20.0  # En-dessous de 20% = extrême (Avant: 10)

    def check_sell_confirmation(
        self, df: pd.DataFrame, premium_percent: float, atr_value: float
    ) -> Tuple[bool, str]:
        """
        Vérifie si un SELL dans une zone Premium extrême a une confirmation.

        Returns:
            (allowed, reason)
        """
        if not self.enabled:
            return True, "Momentum filter disabled"

        # Si Premium < 90%, pas besoin de confirmation stricte
        if premium_percent < self.extreme_premium_threshold:
            return True, "Premium zone not extreme"

        # Zone EXTRÊME détectée, on exige une confirmation
        logger.info(
            f"   🔍 Zone Premium Extrême ({premium_percent:.1f}%). Vérification confirmation..."
        )

        # Récupérer les 3 dernières bougies closes
        if len(df) < 5:
            return False, "❌ Données insuffisantes pour confirmation"

        last_candles = df.tail(5)
        current = last_candles.iloc[-1]
        prev_1 = last_candles.iloc[-2]
        prev_2 = last_candles.iloc[-3]

        # ----- CRITÈRE 0 (Pré-requis) : VOLUME SUFFISANT (RVOL STRICT) -----
        # 🚀 EXPERT FIX: On veut voir l'institution sur la bougie de signal (current), pas avant.
        vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
        if vol_col in df.columns:
            # On vérifie le volume de la bougie ACTUELLE (celle qui fait le signal)
            curr_vol = current[vol_col]
            avg_vol = df[vol_col].rolling(20).mean().iloc[-2] # Moyenne sur les préc, pas incluant current

            if avg_vol > 0:
                rvol = curr_vol / avg_vol
                # 🔥 STRICT MODE: "Chasseur de Mouvements Puissants" = RVOL > 1.5
                if rvol < 1.5:
                    logger.warning(
                        f"   ❌ SELL BLOQUÉ : Volume trop faible (RVOL: {rvol:.2f} < 1.5). Pas de puissance."
                    )
                    return False, f"❌ Low Power (RVOL: {rvol:.2f})"

        # ----- CRITÈRE 1 : Confirmation Structurelle (Micro-BOS / Breakout) -----
        # Le prix doit casser le plus bas précédent pour valider le retournement
        # "Au lieu d'entrer dans la zone à l'aveugle, on attend la cassure"
        
        has_micro_bos = current["close"] < prev_1["low"]
        
        if not has_micro_bos:
             logger.warning(f"   ❌ SELL BLOQUÉ : Pas de cassure structurelle (Close {current['close']} > Low {prev_1['low']})")
             return False, "❌ No Micro-BOS (Wait for break)"

        # ----- CRITÈRE 2 : Confirmation de Force (Engulfing ou Marubozu) -----
        is_bearish = current["close"] < current["open"]
        body = abs(current["close"] - current["open"])
        full_range = current["high"] - current["low"]
        
        # A) Engulfing Bearish
        prev_body = abs(prev_1["close"] - prev_1["open"])
        is_engulfing = is_bearish and body > prev_body and current["close"] < prev_1["low"]

        # B) Marubozu
        is_strong_candle = is_bearish and (body / full_range > 0.6) if full_range > 0 else False

        if is_engulfing or is_strong_candle or has_micro_bos:
             # Si on a le Micro-BOS + Volume, on est bon, l'engulfing est un bonus
             return True, "Strong Breakout Confirmed"
        
        return False, "Weak Signal"

    def check_buy_confirmation(
        self, df: pd.DataFrame, premium_percent: float, atr_value: float
    ) -> Tuple[bool, str]:
        """
        Vérifie si un BUY dans une zone Discount extrême a une confirmation.
        Returns: (allowed, reason)
        """
        if not self.enabled:
            return True, "Momentum filter disabled"

        # Si Discount > 20%, pas besoin de confirmation stricte
        if premium_percent > self.extreme_discount_threshold:
            return True, "Discount zone not extreme"

        logger.info(
            f"   🔍 Zone Discount Extrême ({premium_percent:.1f}%). Vérification confirmation..."
        )

        if len(df) < 5:
            return False, "❌ Données insuffisantes pour confirmation"

        last_candles = df.tail(5)
        current = last_candles.iloc[-1]
        prev_1 = last_candles.iloc[-2]

        # ----- CRITÈRE 0 (Pré-requis) : VOLUME SUFFISANT (RVOL STRICT) -----
        vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
        if vol_col in df.columns:
            curr_vol = current[vol_col]
            avg_vol = df[vol_col].rolling(20).mean().iloc[-2]

            if avg_vol > 0:
                rvol = curr_vol / avg_vol
                # 🔥 STRICT MODE: RVOL > 1.5
                if rvol < 1.5:
                    logger.warning(
                        f"   ❌ BUY BLOQUÉ : Volume trop faible (RVOL: {rvol:.2f} < 1.5). Pas de puissance."
                    )
                    return False, f"❌ Low Power (RVOL: {rvol:.2f})"

        # ----- CRITÈRE 1 : Confirmation Structurelle (Micro-BOS / Breakout) -----
        # Le prix doit casser le plus haut précédent
        has_micro_bos = current["close"] > prev_1["high"]
        
        if not has_micro_bos:
             logger.warning(f"   ❌ BUY BLOQUÉ : Pas de cassure structurelle (Close {current['close']} < High {prev_1['high']})")
             return False, "❌ No Micro-BOS (Wait for break)"

        # ----- CRITÈRE 2 : Confirmation de Force -----
        is_bullish = current["close"] > current["open"]
        body = abs(current["close"] - current["open"])
        full_range = current["high"] - current["low"]

        # A) Engulfing Bullish
        prev_body = abs(prev_1["close"] - prev_1["open"])
        is_engulfing = is_bullish and body > prev_body and current["close"] > prev_1["high"]

        # B) Marubozu
        is_strong_candle = is_bullish and (body / full_range > 0.6) if full_range > 0 else False

        if is_engulfing or is_strong_candle or has_micro_bos:
             return True, "Strong Breakout Confirmed"

        return False, "Weak Signal"
