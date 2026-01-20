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

        # ----- CRITÈRE 0 (Pré-requis) : VOLUME SUFFISANT (RVOL) -----
        # Filtre anti-fakeout week-end
        vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
        if vol_col in df.columns:
            current_vol = current[vol_col]
            # Calcul moyenne mobile volume sur 20 périodes (sur le DF complet)
            avg_vol = df[vol_col].rolling(20).mean().iloc[-1]

            if avg_vol > 0:
                rvol = current_vol / avg_vol
                if rvol < 0.7:
                    logger.warning(
                        f"   ❌ SELL BLOQUÉ : Volume trop faible (RVOL: {rvol:.2f} < 0.7) - Faux mouvement probable"
                    )
                    return False, f"❌ Low Volume (RVOL: {rvol:.2f})"

        # ----- CRITÈRE 1 : Bougie de Rejet (Wick supérieur dominant) -----
        upper_wick = current["high"] - max(current["open"], current["close"])
        lower_wick = min(current["open"], current["close"]) - current["low"]
        body = abs(current["close"] - current["open"])

        # Bougie de rejet = mèche sup > 2x le corps ET corps rouge
        is_bearish = current["close"] < current["open"]
        has_rejection_wick = upper_wick > (body * 2) and upper_wick > (atr_value * 0.3)

        if is_bearish and has_rejection_wick:
            logger.info(
                f"   ✅ Confirmation : Bougie de Rejet détectée (Wick: {upper_wick:.1f} vs Body: {body:.1f})"
            )
            return True, "Rejection candle confirmed"

        # ----- CRITÈRE 2 : Pause du Momentum (Consolidation) -----
        # Les 3 dernières bougies ont un range < ATR/2 (marché essoufflé)
        ranges = [
            prev_2["high"] - prev_2["low"],
            prev_1["high"] - prev_1["low"],
            current["high"] - current["low"],
        ]
        avg_range = np.mean(ranges)

        if avg_range < (atr_value / 2):
            logger.info(
                f"   ✅ Confirmation : Pause du momentum (Avg Range: {avg_range:.1f} < ATR/2: {atr_value/2:.1f})"
            )
            return True, "Momentum pause detected"

        # ----- CRITÈRE 3 : Série de bougies baissières (début de retournement) -----
        # Les 2 dernières closes sont descendantes
        if prev_1["close"] < prev_2["close"] and current["close"] < prev_1["close"]:
            logger.info(f"   ✅ Confirmation : Série baissière commencée (Downtrend initiation)")
            return True, "Bearish sequence started"

        # Aucune confirmation trouvée
        logger.warning(
            f"   ❌ SELL BLOQUÉ : Zone Premium Extrême ({premium_percent:.1f}%) sans confirmation de rejet"
        )
        return False, f"❌ No rejection in extreme Premium ({premium_percent:.1f}%)"

    def check_buy_confirmation(
        self, df: pd.DataFrame, premium_percent: float, atr_value: float
    ) -> Tuple[bool, str]:
        """
        Vérifie si un BUY dans une zone Discount extrême a une confirmation.

        Returns:
            (allowed, reason)
        """
        if not self.enabled:
            return True, "Momentum filter disabled"

        # Si Discount > 10%, pas besoin de confirmation stricte
        if premium_percent > self.extreme_discount_threshold:
            return True, "Discount zone not extreme"

        # Zone EXTRÊME détectée
        logger.info(
            f"   🔍 Zone Discount Extrême ({premium_percent:.1f}%). Vérification confirmation..."
        )

        if len(df) < 5:
            return False, "❌ Données insuffisantes pour confirmation"

        last_candles = df.tail(5)
        current = last_candles.iloc[-1]
        prev_1 = last_candles.iloc[-2]
        prev_2 = last_candles.iloc[-3]

        # ----- CRITÈRE 0 (Pré-requis) : VOLUME SUFFISANT (RVOL) -----
        vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
        if vol_col in df.columns:
            current_vol = current[vol_col]
            avg_vol = df[vol_col].rolling(20).mean().iloc[-1]

            if avg_vol > 0:
                rvol = current_vol / avg_vol
                if rvol < 0.7:
                    logger.warning(
                        f"   ❌ BUY BLOQUÉ : Volume trop faible (RVOL: {rvol:.2f} < 0.7) - Faux mouvement probable"
                    )
                    return False, f"❌ Low Volume (RVOL: {rvol:.2f})"

        # ----- CRITÈRE 1 : Bougie de Rebond (Wick inférieur dominant) -----
        upper_wick = current["high"] - max(current["open"], current["close"])
        lower_wick = min(current["open"], current["close"]) - current["low"]
        body = abs(current["close"] - current["open"])

        is_bullish = current["close"] > current["open"]
        has_bounce_wick = lower_wick > (body * 2) and lower_wick > (atr_value * 0.3)

        if is_bullish and has_bounce_wick:
            logger.info(
                f"   ✅ Confirmation : Bougie de Rebond détectée (Wick: {lower_wick:.1f} vs Body: {body:.1f})"
            )
            return True, "Bounce candle confirmed"

        # ----- CRITÈRE 2 : Pause du Momentum -----
        ranges = [
            prev_2["high"] - prev_2["low"],
            prev_1["high"] - prev_1["low"],
            current["high"] - current["low"],
        ]
        avg_range = np.mean(ranges)

        if avg_range < (atr_value / 2):
            logger.info(f"   ✅ Confirmation : Pause du momentum (Avg Range: {avg_range:.1f})")
            return True, "Momentum pause detected"

        # ----- CRITÈRE 3 : Série de bougies haussières -----
        if prev_1["close"] > prev_2["close"] and current["close"] > prev_1["close"]:
            logger.info(f"   ✅ Confirmation : Série haussière commencée")
            return True, "Bullish sequence started"

        logger.warning(
            f"   ❌ BUY BLOQUÉ : Zone Discount Extrême ({premium_percent:.1f}%) sans confirmation de rebond"
        )
        return False, f"❌ No bounce in extreme Discount ({premium_percent:.1f}%)"
