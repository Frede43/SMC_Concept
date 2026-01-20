import pandas as pd
import numpy as np
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List, Tuple
from loguru import logger
from collections import deque

# Anti-Tilt System logic
try:
    from strategy.anti_tilt import AntiTiltSystem, PositionSizeResult

    ANTI_TILT_AVAILABLE = True
except ImportError:
    ANTI_TILT_AVAILABLE = False
    logger.warning("   Anti-Tilt System non disponible")


@dataclass
class PositionSize:
    lot_size: float
    risk_amount: float
    pip_value: float
    stop_loss_pips: float


@dataclass
class TradeStats:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_profit: float
    daily_profit: float
    daily_trades: int
    max_drawdown: float


class RiskManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get("risk", {})
        self.risk_per_trade = self.config.get("risk_per_trade", 1.0)
        self.max_lots_forex = self.config.get("max_lots_forex", 10.0)
        self.max_lots_xauusd = self.config.get("max_lots_xauusd", 50.0)
        self.use_fixed_lot = self.config.get("use_fixed_lot", False)
        self.fixed_lot_size = self.config.get("fixed_lot_size", 0.01)
        self.max_open_trades = self.config.get("max_open_trades", 3)
        self.max_trades_per_symbol = self.config.get("max_trades_per_symbol", 1)
        self.max_daily_trades = self.config.get("max_daily_trades", 5)
        self.max_daily_loss = self.config.get("max_daily_loss", 3.0)
        self.cooldown_after_loss = self.config.get("cooldown_after_loss", 60)
        self.cooldown_after_win = self.config.get("cooldown_after_win", 15)
        self.max_consecutive_losses = self.config.get("max_consecutive_losses", 3)
        self.use_trailing = self.config.get("trailing_stop", True)
        self.trailing_distance = self.config.get("trailing_dist", 10.0)
        self.trailing_start = self.config.get("trailing_trigger", 10.0)
        self.use_break_even = self.config.get("break_even", True)
        self.be_pips = self.config.get("break_even_trigger", 10.0)

        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.open_trades = 0
        self.open_trades_by_symbol = {}
        self.loss_cooldowns = {}
        self.win_cooldowns = {}
        self.consecutive_losses = {}
        self.last_reset_date = None

        self.use_anti_tilt = self.config.get("use_anti_tilt", True)
        self.use_kelly = self.config.get("use_kelly", False)
        self.kelly_fraction = self.config.get("kelly_fraction", 0.25)
        self.kelly_lookback = self.config.get("kelly_lookback", 20)
        self.trade_history = deque(maxlen=100)
        self.peak_equity = 0.0
        self.current_equity = 0.0
        self.current_drawdown_pct = 0.0

        if self.use_anti_tilt and ANTI_TILT_AVAILABLE:
            self.anti_tilt = AntiTiltSystem(
                {
                    "base_risk_percent": self.risk_per_trade,
                    "max_daily_loss_percent": self.max_daily_loss,
                    "max_daily_trades": self.max_daily_trades,
                }
            )
        else:
            self.anti_tilt = None

    def calculate_position_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        symbol: str = "EURUSD",
        symbol_info: Dict = None,
    ) -> PositionSize:
        if account_balance <= 0:
            logger.error(f"Account Balance Zero/Negative (${account_balance:.2f})")
            return PositionSize(0.01, 0, 0, 0)

        if self.use_fixed_lot:
            pip_val = self._get_pip_value(symbol)
            sl_pips = abs(entry_price - stop_loss) / pip_val if pip_val > 0 else 0
            return PositionSize(self.fixed_lot_size, 0, pip_val, sl_pips)

        risk_amount = account_balance * (self.risk_per_trade / 100)
        pip_value = (
            symbol_info.get("pip_size", self._get_pip_value(symbol))
            if symbol_info
            else self._get_pip_value(symbol)
        )
        pip_val_per_lot = (
            symbol_info.get("pip_value_per_lot", self._get_pip_value_per_lot(symbol))
            if symbol_info
            else self._get_pip_value_per_lot(symbol)
        )

        sl_pips = abs(entry_price - stop_loss) / pip_value if pip_value > 0 else 10
        if sl_pips == 0:
            sl_pips = 1

        lot_size = (
            risk_amount / (sl_pips * pip_val_per_lot) if (sl_pips * pip_val_per_lot) > 0 else 0.01
        )
        lot_size = max(0.01, min(self.max_lots_forex, round(lot_size, 2)))

        # 🛡️ TRIPLE PROTECTION HARD CAP - Prévention bug liquidation compte
        # Protection 1: Cap basé sur capital (pour petits comptes <1000$)
        if account_balance < 1000:
            SMALL_ACCOUNT_MAX_LOT = 0.10
            lot_size = min(lot_size, SMALL_ACCOUNT_MAX_LOT)
            if lot_size >= SMALL_ACCOUNT_MAX_LOT:
                logger.warning(
                    f"🛡️ Small account protection: Lot capped to {SMALL_ACCOUNT_MAX_LOT} (capital: ${account_balance:.2f})"
                )

        # Protection 2: Cap basé sur symbole (crypto/indices plus volatils)
        symbol_upper = symbol.upper()
        if "BTC" in symbol_upper or "ETH" in symbol_upper:
            CRYPTO_MAX_LOT = 0.05  # Crypto très volatile
            lot_size = min(lot_size, CRYPTO_MAX_LOT)
            if lot_size >= CRYPTO_MAX_LOT:
                logger.warning(f"🛡️ Crypto protection: {symbol} lot capped to {CRYPTO_MAX_LOT}")
        elif "US30" in symbol_upper or "USTEC" in symbol_upper or "NAS100" in symbol_upper:
            INDEX_MAX_LOT = 0.10  # Indices
            lot_size = min(lot_size, INDEX_MAX_LOT)
            if lot_size >= INDEX_MAX_LOT:
                logger.warning(f"🛡️ Index protection: {symbol} lot capped to {INDEX_MAX_LOT}")

        # Protection 3: Cap absolu global (sécurité ultime)
        ABSOLUTE_MAX_LOT = 1.0  # JAMAIS dépasser en aucune circonstance
        if lot_size > ABSOLUTE_MAX_LOT:
            logger.error(
                f"🚨 CRITICAL: Lot size {lot_size} exceeds ABSOLUTE MAX {ABSOLUTE_MAX_LOT}! Bug detected!"
            )
            logger.error(
                f"🚨 Details: symbol={symbol}, balance=${account_balance}, risk_amount=${risk_amount}, sl_pips={sl_pips}, pip_val_per_lot={pip_val_per_lot}"
            )
            lot_size = ABSOLUTE_MAX_LOT

        # Validation finale
        if lot_size <= 0 or lot_size != lot_size:  # NaN check
            logger.error(
                f"🚨 CRITICAL: Invalid lot_size calculated: {lot_size}. Using minimum 0.01"
            )
            lot_size = 0.01

        return PositionSize(lot_size, risk_amount, pip_value, sl_pips)

    def _get_pip_value(self, symbol: str) -> float:
        s = symbol.upper()
        if "BTC" in s:
            return 1.0
        if "ETH" in s:
            return 1.0
        if "XAU" in s:
            return 0.01
        if "JPY" in s:
            return 0.01
        return 0.0001

    def _get_pip_value_per_lot(self, symbol: str) -> float:
        s = symbol.upper()
        if "BTC" in s or "ETH" in s:
            return 1.0
        if "XAU" in s:
            return 1.0
        if "JPY" in s:
            return 1000.0
        return 10.0

    def calculate_trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        current_sl: float,
        direction: str,
        symbol: str = "EURUSD",
    ) -> Optional[float]:
        if not self.use_trailing:
            return None
        pip_val = self._get_pip_value(symbol)
        t_start = self.trailing_start * pip_val
        t_dist = self.trailing_distance * pip_val
        if direction.upper() == "BUY":
            if current_price - entry_price >= t_start:
                new_sl = current_price - t_dist
                if new_sl > current_sl:
                    return new_sl
        else:
            if entry_price - current_price >= t_start:
                new_sl = current_price + t_dist
                if new_sl < current_sl:
                    return new_sl
        return None

    def calculate_break_even(
        self,
        entry_price: float,
        current_price: float,
        current_sl: float,
        direction: str,
        symbol: str = "EURUSD",
    ) -> Optional[float]:
        if not self.use_break_even:
            return None
        pip_val = self._get_pip_value(symbol)
        trigger = self.be_pips * pip_val
        if direction.upper() == "BUY":
            if current_price - entry_price >= trigger:
                if current_sl < entry_price:
                    return entry_price
        else:
            if entry_price - current_price >= trigger:
                if current_sl > entry_price:
                    return entry_price
        return None

    def calculate_position_size_dynamic(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        symbol: str,
        mt5_api: Any,
    ) -> PositionSize:
        """Calcule la taille de position en utilisant les données dynamiques du broker via MT5."""
        symbol_info = (
            mt5_api.get_symbol_info(symbol) if hasattr(mt5_api, "get_symbol_info") else None
        )
        return self.calculate_position_size(
            account_balance, entry_price, stop_loss, symbol, symbol_info
        )

    def can_open_trade(self, symbol: str) -> Tuple[bool, List[str]]:
        """Vérifie si un nouveau trade peut être ouvert selon les règles de gestion du risque."""
        reasons = []
        now = datetime.now()

        # 0. Réinitialisation quotidienne
        current_date = date.today()
        if self.last_reset_date != current_date:
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.last_reset_date = current_date
            logger.info("🔄 RiskManager: Daily stats reset")

        # 1. Vérifier la limite de perte quotidienne
        if self.daily_pnl <= -self.max_daily_loss:
            reasons.append(
                f"Daily loss limit reached ({self.daily_pnl:.2f}% <= -{self.max_daily_loss}%)"
            )

        # 2. Vérifier le nombre de trades ouverts au total
        if self.open_trades >= self.max_open_trades:
            reasons.append(f"Max open trades reached ({self.open_trades}/{self.max_open_trades})")

        # 3. Vérifier le nombre de trades ouverts par symbole
        symbol_trades = self.open_trades_by_symbol.get(symbol, 0)
        if symbol_trades >= self.max_trades_per_symbol:
            reasons.append(
                f"Max trades for {symbol} reached ({symbol_trades}/{self.max_trades_per_symbol})"
            )

        # 4. Vérifier la limite de trades quotidiens
        if self.daily_trades >= self.max_daily_trades:
            reasons.append(
                f"Max daily trades reached ({self.daily_trades}/{self.max_daily_trades})"
            )

        # 5. Vérifier le cooldown après perte
        if symbol in self.loss_cooldowns:
            if now < self.loss_cooldowns[symbol]:
                remaining = (self.loss_cooldowns[symbol] - now).total_seconds() / 60
                reasons.append(
                    f"Cooldown active for {symbol} after loss ({remaining:.1f} min remaining)"
                )

        # 6. Vérifier les pertes consécutives (Kill Switch par symbole)
        if self.consecutive_losses.get(symbol, 0) >= self.max_consecutive_losses:
            reasons.append(
                f"Max consecutive losses reached for {symbol} ({self.consecutive_losses[symbol]})"
            )

        if reasons:
            return False, reasons
        return True, []

    def on_trade_opened(self, symbol: str):
        """Met à jour l'état après l'ouverture d'un trade."""
        self.open_trades += 1
        self.open_trades_by_symbol[symbol] = self.open_trades_by_symbol.get(symbol, 0) + 1
        self.daily_trades += 1
        logger.debug(f"📈 Trade ouvert sur {symbol}. Total ouverts: {self.open_trades}")

    def on_trade_closed(self, pnl_percent: float, symbol: str):
        """Met à jour l'état après la fermeture d'un trade."""
        self.open_trades = max(0, self.open_trades - 1)
        if symbol in self.open_trades_by_symbol:
            self.open_trades_by_symbol[symbol] = max(0, self.open_trades_by_symbol[symbol] - 1)

        self.daily_pnl += pnl_percent

        # Gérer les cooldowns et pertes consécutives
        if pnl_percent < 0:
            self.consecutive_losses[symbol] = self.consecutive_losses.get(symbol, 0) + 1
            # Appliquer le cooldown après perte
            self.loss_cooldowns[symbol] = datetime.now() + timedelta(
                minutes=self.cooldown_after_loss
            )
            logger.warning(
                f"📉 Perte sur {symbol} ({pnl_percent:.2f}%). Cooldown: {self.cooldown_after_loss}min. Pertes consécutives: {self.consecutive_losses[symbol]}"
            )
        else:
            self.consecutive_losses[symbol] = 0
            # Cooldown plus court après gain
            self.win_cooldowns[symbol] = datetime.now() + timedelta(minutes=self.cooldown_after_win)
            logger.info(f"📈 Gain sur {symbol} ({pnl_percent:.2f}%). Reset pertes consécutives.")

    def get_stats(self) -> TradeStats:
        """Retourne un objet TradeStats avec les performances actuelles."""
        total = len(self.trade_history)
        wins = sum(1 for t in self.trade_history if t.get("is_win", False))
        losses = total - wins
        win_rate = (wins / total * 100) if total > 0 else 0
        total_pnl = sum(t.get("pnl", 0) for t in self.trade_history)

        return TradeStats(
            total_trades=total,
            winning_trades=wins,
            losing_trades=losses,
            win_rate=win_rate,
            total_profit=total_pnl,
            daily_profit=self.daily_pnl,
            daily_trades=self.daily_trades,
            max_drawdown=self.current_drawdown_pct,
        )

    def update_equity(self, current_equity: float, trade_pnl: float = None, is_win: bool = None):
        self.current_equity = current_equity
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
        if self.peak_equity > 0:
            self.current_drawdown_pct = (self.peak_equity - current_equity) / self.peak_equity * 100
        if is_win is not None:
            self.trade_history.append({"pnl": trade_pnl, "is_win": is_win})

    def get_anti_tilt_status(self) -> Dict:
        return {
            "equity": {
                "current": self.current_equity,
                "peak": self.peak_equity,
                "drawdown": self.current_drawdown_pct,
            },
            "daily_trades": self.daily_trades,
            "daily_pnl": self.daily_pnl,
            "open_trades": self.open_trades,
            "consecutive_losses": self.consecutive_losses,
        }
