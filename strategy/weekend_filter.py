"""
Weekend Filter Module
Gère la pause du trading pendant le week-end et la fermeture des positions vendredi.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Tuple
from loguru import logger


class WeekendFilter:
    """
    Filtre pour gérer le trading autour du week-end.

    Fonctionnalités:
    - Arrêter les nouveaux trades le vendredi soir
    - Optionnellement fermer les positions avant le week-end
    - Pause complète samedi-dimanche
    - Reprise automatique le lundi
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config.get("weekend_filter", {})
        self.enabled = self.config.get("enabled", True)
        self.timezone_offset = self.config.get("timezone_offset", 2)  # UTC+2 par défaut

        # Vendredi
        self.friday_stop_hour = self.config.get("friday_stop_new_trades_hour", 21)
        self.friday_close_hour = self.config.get("friday_close_positions_hour", 22)
        self.friday_close_enabled = self.config.get("friday_close_positions", False)

        # Lundi
        self.monday_start_hour = self.config.get("monday_start_hour", 1)

        # Week-end mode
        self.weekend_mode = self.config.get("weekend_mode", "pause")

        logger.info(
            f"WeekendFilter initialized - Enabled: {self.enabled}, "
            f"Friday stop: {self.friday_stop_hour}h, Monday start: {self.monday_start_hour}h"
        )

    def _get_local_time(self) -> datetime:
        """Retourne l'heure locale selon le timezone configuré."""
        utc_now = datetime.utcnow()
        local_time = utc_now + timedelta(hours=self.timezone_offset)
        return local_time

    def is_weekend(self) -> bool:
        """Vérifie si c'est le week-end (samedi ou dimanche)."""
        local_time = self._get_local_time()
        # 5 = Samedi, 6 = Dimanche
        return local_time.weekday() in [5, 6]

    def is_friday_evening(self) -> bool:
        """Vérifie si c'est vendredi soir (après l'heure d'arrêt)."""
        local_time = self._get_local_time()
        # 4 = Vendredi
        return local_time.weekday() == 4 and local_time.hour >= self.friday_stop_hour

    def is_monday_early(self) -> bool:
        """Vérifie si c'est lundi matin tôt (avant l'heure de reprise)."""
        local_time = self._get_local_time()
        # 0 = Lundi
        return local_time.weekday() == 0 and local_time.hour < self.monday_start_hour

    def is_holiday(self) -> bool:
        """Vérifie si c'est un jour férié (Noël, Nouvel An)."""
        local_time = self._get_local_time()

        # Jours fériés fixes (Mois, Jour)
        # Note: Le Forex est généralement fermé le 25/12 et 01/01
        holidays = [
            (12, 25),  # Noël
            (1, 1),  # Nouvel An
        ]

        return (local_time.month, local_time.day) in holidays

    def can_trade(self) -> Tuple[bool, str]:
        """
        Vérifie si le trading est autorisé.

        Returns:
            Tuple (can_trade: bool, reason: str)
        """
        if not self.enabled:
            return True, "Weekend filter disabled"

        local_time = self._get_local_time()
        day_name = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"][
            local_time.weekday()
        ]
        time_str = local_time.strftime("%H:%M")

        # Samedi ou Dimanche
        if self.is_weekend():
            return False, f"⏸️ Week-end ({day_name} {time_str}) - Marché fermé"

        # Vendredi soir
        if self.is_friday_evening():
            return False, f"⏸️ Vendredi soir ({time_str}) - Arrêt avant week-end"

        # Jour férié
        if self.is_holiday():
            return False, f"🎄 Jour férié ({day_name} {time_str}) - Marché fermé"

        # Lundi trop tôt
        if self.is_monday_early():
            return False, f"⏸️ Lundi matin ({time_str}) - Attente ouverture marché"

        return True, f"✅ Trading autorisé ({day_name} {time_str})"

    def should_close_positions(self) -> Tuple[bool, str]:
        """
        Vérifie si on doit fermer les positions (vendredi soir).

        Returns:
            Tuple (should_close: bool, reason: str)
        """
        if not self.enabled or not self.friday_close_enabled:
            return False, "Auto-close disabled"

        local_time = self._get_local_time()

        # Vendredi après l'heure de fermeture
        if local_time.weekday() == 4 and local_time.hour >= self.friday_close_hour:
            return (
                True,
                f"🔒 Vendredi {local_time.strftime('%H:%M')} - Fermeture positions avant week-end",
            )

        return False, "Not time to close"

    def get_status(self) -> Dict[str, Any]:
        """Retourne le status complet du filtre."""
        local_time = self._get_local_time()
        can_trade, trade_reason = self.can_trade()
        should_close, close_reason = self.should_close_positions()

        return {
            "enabled": self.enabled,
            "local_time": local_time.strftime("%Y-%m-%d %H:%M:%S"),
            "day": ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"][
                local_time.weekday()
            ],
            "can_trade": can_trade,
            "trade_reason": trade_reason,
            "should_close_positions": should_close,
            "close_reason": close_reason,
            "is_weekend": self.is_weekend(),
            "is_friday_evening": self.is_friday_evening(),
            "is_monday_early": self.is_monday_early(),
        }

    def get_next_trading_time(self) -> str:
        """Retourne l'heure de la prochaine session de trading."""
        local_time = self._get_local_time()

        if self.is_holiday():
            next_day = local_time + timedelta(days=1)
            return f"Demain {next_day.strftime('%d/%m')} (si non-ferié/week-end)"

        if self.is_weekend():
            # Calculer le temps jusqu'à lundi
            days_until_monday = (7 - local_time.weekday()) % 7
            if days_until_monday == 0:
                days_until_monday = 1  # Si dimanche, c'est demain

            next_trading = local_time.replace(
                hour=self.monday_start_hour, minute=0, second=0
            ) + timedelta(days=days_until_monday)

            return next_trading.strftime("%A %d/%m à %H:%M")

        if self.is_friday_evening():
            # Lundi prochain
            days_until_monday = 3  # Vendredi + 3 = Lundi
            next_trading = local_time.replace(
                hour=self.monday_start_hour, minute=0, second=0
            ) + timedelta(days=days_until_monday)

            return next_trading.strftime("%A %d/%m à %H:%M")

        if self.is_monday_early():
            # Plus tard ce lundi
            next_trading = local_time.replace(hour=self.monday_start_hour, minute=0, second=0)
            return next_trading.strftime("%A %d/%m à %H:%M")

        return "Maintenant"


def test_weekend_filter():
    """Test du filtre week-end."""
    config = {
        "weekend_filter": {
            "enabled": True,
            "timezone_offset": 2,
            "friday_stop_new_trades_hour": 21,
            "friday_close_positions_hour": 22,
            "friday_close_positions": False,
            "monday_start_hour": 1,
            "weekend_mode": "pause",
        }
    }

    wf = WeekendFilter(config)
    status = wf.get_status()

    print("=" * 60)
    print("WEEKEND FILTER STATUS")
    print("=" * 60)
    for key, value in status.items():
        print(f"{key}: {value}")
    print(f"\nProchaine session: {wf.get_next_trading_time()}")
    print("=" * 60)


if __name__ == "__main__":
    test_weekend_filter()
