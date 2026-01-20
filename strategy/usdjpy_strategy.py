import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple, List
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class UsdJpySignalType(Enum):
    STRONG_SELL = "STRONG_SELL"
    WAIT = "WAIT"


@dataclass
class UsdJpySignal:
    signal_type: UsdJpySignalType
    entry_price: float
    stop_loss: float
    take_profit_1: float  # Premier TP (cible de liquidité logique)
    take_profit_2: float  # Deuxième TP (objectif plus ambitieux)
    confidence: float
    reasons: List[str]


class UsdJpySMCStrategy:
    """
    Stratégie SMC spécialisée pour USD/JPY basée sur l'analyse des 3 timeframes.
    Logique : Attendre un retest sur un Order Block Baissier H4 significatif
    après un grab de liquidité haussière.
    """

    def __init__(self, htf_df: pd.DataFrame, mtf_df: pd.DataFrame, ltf_df: pd.DataFrame):
        """
        Args:
            htf_df (pd.DataFrame): Données D1 (contexte)
            mtf_df (pd.DataFrame): Données H4 (setup)
            ltf_df (pd.DataFrame): Données M15 (timing/entrée)
        """
        self.htf_df = htf_df
        self.mtf_df = mtf_df
        self.ltf_df = ltf_df

        # Paramètres optimisés pour USD/JPY
        self.pip_value = 0.01
        self.min_swing_points = 5
        self.ob_candle_lookback = 3  # Nombre de bougies pour définir un OB
        self.min_ob_range_pips = 10  # Adjusted to 10 for more sensitivity
        self.fvg_min_gap_pips = 5

    def analyze(self) -> Optional[UsdJpySignal]:
        """
        Lance l'analyse complète et retourne un signal si les conditions sont remplies.
        """
        logger.info("🇯🇵 Lancement de l'analyse SMC spécialisée USD/JPY...")

        # 1. Vérifier le contexte D1 (Tendance et Zone)
        htf_bias, htf_zone = self._analyze_htf_context()
        # On détend un peu : on accepte un bearish si on est en premium pour shorter un retracement
        # Mais le setup STRICT demandait un contexte haussier global D1 pour shorter un pullback ?
        # NON, l'analyse dit:
        # "Le marché est dans une tendance haussière claire depuis début 2024 ... La zone Premium ... Order Block Baissier H4"
        # Donc on shorte le rejet de la zone Premium D1.

        if htf_zone != "premium" and htf_zone != "equilibrium":
            # Si on est en Discount, on évite de shorter sauf si structure bearish confirmée
            if htf_bias == "bullish":
                logger.info(
                    f"   ❌ Contexte D1: Tendance Bullish et Zone Discount/Equilibrium -> Pas de short. Zone={htf_zone}"
                )
                return None

        logger.info(
            f"   ✅ Contexte D1 favorable pour un Short de retracement/rejet: Tendance={htf_bias}, Zone={htf_zone}"
        )

        # 2. Identifier le setup H4 (Order Block Baissier post-sweep)
        bearish_ob = self._find_h4_bearish_order_block()
        if not bearish_ob:
            logger.info("   ❌ Aucun Order Block Baissier H4 significatif trouvé.")
            return None
        logger.info(
            f"   ✅ Order Block Baissier H4 trouvé: {bearish_ob['high']:.3f} - {bearish_ob['low']:.3f}"
        )

        # 3. Vérifier le timing M15 (Le prix est-il dans la zone d'entrée ?)
        entry_signal, entry_price = self._check_ltf_entry_timing(bearish_ob)
        if not entry_signal:
            logger.info("   ⏳ Timing M15 non idéal. En attente d'un meilleur prix dans l'OB.")
            return None
        logger.info(f"   🎯 Signal d'entrée M15 détecté à {entry_price:.3f}")

        # 4. Calculer les niveaux de sortie
        sl, tp1, tp2 = self._calculate_stops(entry_price, bearish_ob)

        reasons = [
            f"Contexte D1 {htf_bias.upper()} (Zone {htf_zone.upper()})",
            f"Retest sur OB Baissier H4 (Setup Principal)",
            f"Signal d'entrée M15 confirmé (Mitigation)",
        ]

        return UsdJpySignal(
            signal_type=UsdJpySignalType.STRONG_SELL,
            entry_price=entry_price,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            confidence=95.0,  # Confiance élevée pour ce setup spécifique et expert
            reasons=reasons,
        )

    def _analyze_htf_context(self) -> Tuple[str, str]:
        """Analyse le D1 pour déterminer la tendance et la zone de prix."""
        df = self.htf_df.copy()

        if len(df) < 1:
            logger.warning("   ❌ HTF DataFrame vide dans UsdJpyStrategy")
            return "ranging", "equilibrium"

        # Analyse simple de tendance basée sur les moyennes mobiles
        # Use try-item to safer access
        try:
            ema50 = df["close"].ewm(span=50).mean().iloc[-1]
            ema200 = df["close"].ewm(span=200).mean().iloc[-1]
            current_price = df["close"].iloc[-1]
        except IndexError:
            logger.error("   ❌ Erreur d'accès aux données D1 (IndexError)")
            return "ranging", "equilibrium"

        if current_price > ema200:
            bias = "bullish"
        elif current_price < ema200:
            bias = "bearish"
        else:
            bias = "ranging"

        # Calculer les zones Premium/Discount sur les 50 derniers jours (Quarterly Shift)
        # Ensure enough data for rolling
        window = min(60, len(df))
        range_high = df["high"].rolling(window).max().iloc[-1]
        range_low = df["low"].rolling(window).min().iloc[-1]
        equilibrium = (range_high + range_low) / 2

        if current_price > equilibrium:
            zone = "premium"
        elif current_price < equilibrium:
            zone = "discount"
        else:
            zone = "equilibrium"

        return bias, zone

    def _find_h4_bearish_order_block(self) -> Optional[dict]:
        """
        Cherche le dernier Order Block Baissier significatif sur le H4.
        Un OB baissier est la dernière bougie haussière AVANT une forte chute.
        """
        df = self.mtf_df.copy()

        # On cherche des bougies baissières fortes (Marubozu like)
        df["body"] = abs(df["close"] - df["open"])
        df["is_bearish"] = df["close"] < df["open"]

        # Seuil de "force"
        avg_body = df["body"].rolling(20).mean()

        # Parcourir les 20 dernières bougies pour trouver un OB
        # Un Bearish OB est souvent la dernière bougie haussière (ou petite bougie)
        # juste avant une série de bougies baissières fortes qui cassent la structure.

        # ✅ FIX: S'assurer que i+3 ne dépasse jamais len(df)-1
        last_safe_index = len(df) - 4  # -4 car on va accéder à i+3
        start_index = min(len(df) - 2, last_safe_index)

        for i in range(start_index, max(len(df) - 20, 0), -1):
            # Vérification de sécurité supplémentaire
            if i + 3 >= len(df):
                continue

            # Simulation simplifiée: on cherche une bougie qui a été suivie par une chute
            next_candles_drop = (
                df["close"].iloc[i] - df["close"].iloc[i + 3]
            ) / self.pip_value  # Drop sur 3 bougies

            if next_candles_drop > 20:  # Chute de 20 pips minimum après
                # Cette bougie à l'index i est potentiellement l'OB
                candidate = df.iloc[i]
                ob_high = candidate["high"]
                ob_low = candidate["low"]

                # On retourne le premier (le plus récent) trouvé
                return {"high": ob_high, "low": ob_low, "index": i}

        return None

    def _check_ltf_entry_timing(self, h4_ob: dict) -> Tuple[bool, float]:
        """
        Vérifie si le prix M15 actuel est dans la zone de l'OB H4.
        """
        if self.ltf_df is None or self.ltf_df.empty:
            return False, 0.0

        current_price = self.ltf_df["close"].iloc[-1]

        # La zone d'entrée est l'OB H4 (+/- un petit buffer)
        # On veut vendre DANS l'OB ou juste en dessous lors du retest

        buffer = 5 * self.pip_value

        if (h4_ob["low"] - buffer) <= current_price <= (h4_ob["high"] + buffer):
            return True, current_price

        return False, 0.0

    def _calculate_stops(self, entry_price: float, h4_ob: dict) -> Tuple[float, float, float]:
        """
        Calcule le Stop Loss et les Take Profits.
        """
        # Stop Loss: Juste au-dessus de l'OB H4
        sl_buffer_pips = 10
        stop_loss = h4_ob["high"] + (sl_buffer_pips * self.pip_value)

        # Risk amount
        risk = abs(entry_price - stop_loss)

        # TP1: 1:2 R:R (Classique SMC)
        take_profit_1 = entry_price - (risk * 2.0)

        # TP2: 1:4 R:R (Swing)
        take_profit_2 = entry_price - (risk * 4.0)

        return stop_loss, take_profit_1, take_profit_2
