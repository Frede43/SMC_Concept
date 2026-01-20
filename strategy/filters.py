"""
Trading Filters
Filtres de confirmation pour les signaux de trading
"""

import pandas as pd
from datetime import datetime, time
from typing import Dict, Any, Optional, Tuple
from loguru import logger
import pytz

from core.killzones import KillzoneDetector


class TradingFilters:
    """
    Filtres pour valider les signaux de trading.

    Inclut:
    - Filtre de Killzones (SMC sessions)
    - Filtre de session (London, NY, Asian) - legacy
    - Filtre de spread
    - Filtre de volatilité (ATR)
    - Filtre de tendance
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config.get("filters", {})
        self.symbols_config = config.get("symbols", [])
        self.timezone = pytz.timezone("Europe/London")

        # Initialiser le détecteur de Killzones
        kz_config = self.config.get("killzones", {})
        self.killzone_detector = KillzoneDetector(
            timezone_offset=kz_config.get("timezone_offset", 0),
            enabled=kz_config.get("enabled", False),
        )
        self.use_killzones = kz_config.get("enabled", False)

    def check_all_filters(
        self, df: pd.DataFrame, current_spread: float = 0, symbol: str = None
    ) -> tuple:
        """
        Vérifie tous les filtres.

        Returns:
            (passed, reasons): Tuple avec résultat et liste des raisons
        """
        passed = True
        reasons = []

        # Vérifier si crypto (pour exemption killzone)
        is_crypto = False
        if symbol:
            sym_cfg = self._get_symbol_config(symbol)
            is_crypto = sym_cfg.get("is_crypto", False)
            # Détection manuelle si non configuré
            if not is_crypto:
                s_upper = symbol.upper()
                is_crypto = any(
                    c in s_upper for c in ["BTC", "ETH", "SOL", "XRP", "LTC", "BNB", "CRYPTO"]
                )

        # NOUVEAU: Killzones filter (prioritaire sur sessions)
        if self.use_killzones:
            if is_crypto:
                reasons.append("Crypto 24/7 - Killzones ignorées ✓")
            else:
                kz_ok, kz_msg = self.check_killzones(df)
                if not kz_ok:
                    passed = False
                    reasons.append(kz_msg)
                else:
                    reasons.append(kz_msg)
        elif self.config.get("sessions", {}).get("enabled", False):
            # Legacy session filter
            session_ok, session_name = self.check_session()
            if not session_ok:
                passed = False
                reasons.append(f"Hors session de trading")
            else:
                reasons.append(f"Session {session_name} active ✓")

        # Spread filter
        if symbol:
            symbol_config = self._get_symbol_config(symbol)
            max_spread = symbol_config.get("max_spread", 50)
            if current_spread > max_spread:
                passed = False
                reasons.append(f"Spread trop élevé: {current_spread} > {max_spread}")

        # Volatility filter
        if self.config.get("volatility", {}).get("enabled", False):
            vol_ok, vol_msg = self.check_volatility(df)
            if not vol_ok:
                passed = False
            reasons.append(vol_msg)

        return passed, reasons

    def check_killzones(self, df: pd.DataFrame = None) -> Tuple[bool, str]:
        """
        Vérifie si on est dans une killzone de trading SMC.

        Returns:
            (can_trade, message)
        """
        info = self.killzone_detector.get_killzone_info(df)

        if info.can_trade:
            session_name = info.current_session.value.replace("_", " ").title()
            msg = f"🎯 Killzone {session_name} active ✓"
            if info.asian_range:
                msg += f" | Asian Range: {info.asian_range.low:.5f}-{info.asian_range.high:.5f}"
            return True, msg
        else:
            return False, info.message

    def get_asian_range(self, df: pd.DataFrame = None):
        """Retourne le range asiatique calculé."""
        if not self.use_killzones:
            return None

        if self.killzone_detector.current_asian_range is None and df is not None:
            self.killzone_detector.calculate_asian_range(df)

        return self.killzone_detector.current_asian_range

    def check_session(self, current_time: datetime = None) -> tuple:
        """Vérifie si on est dans une session de trading valide (legacy)."""
        if current_time is None:
            current_time = datetime.now(self.timezone)

        current_hour = current_time.hour
        current_minute = current_time.minute
        current_mins = current_hour * 60 + current_minute

        sessions = self.config.get("sessions", {})

        # London session
        if sessions.get("london", {}).get("enabled", False):
            start = self._parse_time(sessions["london"].get("start", "08:00"))
            end = self._parse_time(sessions["london"].get("end", "12:00"))
            if start <= current_mins <= end:
                return True, "London"

        # New York session
        if sessions.get("new_york", {}).get("enabled", False):
            start = self._parse_time(sessions["new_york"].get("start", "13:00"))
            end = self._parse_time(sessions["new_york"].get("end", "17:00"))
            if start <= current_mins <= end:
                return True, "New York"

        # Asian session
        if sessions.get("asian", {}).get("enabled", False):
            start = self._parse_time(sessions["asian"].get("start", "00:00"))
            end = self._parse_time(sessions["asian"].get("end", "03:00"))
            if start <= current_mins <= end:
                return True, "Asian"

        return False, None

    def _parse_time(self, time_str: str) -> int:
        """Convertit 'HH:MM' en minutes depuis minuit."""
        parts = time_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])

    def check_volatility(self, df: pd.DataFrame, period: int = 14) -> tuple:
        """Vérifie si la volatilité est dans les limites acceptables."""
        if len(df) < period:
            return True, "Pas assez de données pour ATR"

        # Calcul ATR
        high = df["high"]
        low = df["low"]
        close = df["close"].shift(1)

        tr1 = high - low
        tr2 = abs(high - close)
        tr3 = abs(low - close)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        avg_atr = tr.rolling(period * 3).mean().iloc[-1]

        vol_config = self.config.get("volatility", {})
        min_mult = vol_config.get("min_atr_multiplier", 0.5)
        max_mult = vol_config.get("max_atr_multiplier", 2.0)

        if atr < avg_atr * min_mult:
            return False, f"Volatilité trop basse"
        elif atr > avg_atr * max_mult:
            return False, f"Volatilité trop haute"

        return True, "Volatilité normale ✓"

    def check_trend_alignment(self, ltf_bias: str, htf_bias: str) -> bool:
        """Vérifie l'alignement des tendances."""
        if not self.config.get("trend", {}).get("enabled", False):
            return True

        if not self.config.get("trend", {}).get("use_htf_bias", True):
            return True

        return ltf_bias == htf_bias

    def _get_symbol_config(self, symbol: str) -> Dict:
        """Récupère la config d'un symbole."""
        for s in self.symbols_config:
            if s.get("name") == symbol:
                return s
        return {}
