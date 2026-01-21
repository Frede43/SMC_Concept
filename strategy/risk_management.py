"""
Risk Management
Gestion du risque et du capital

Version 2.5 - Advanced Features:
- Intégration Anti-Tilt System
- Kelly Criterion adaptatif
- Réduction de risque basée sur le drawdown
- Protection contre les séries de pertes
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List, Tuple
from loguru import logger
from collections import deque

# Import du système Anti-Tilt (optionnel)
try:
    from strategy.anti_tilt import AntiTiltSystem, PositionSizeResult
    ANTI_TILT_AVAILABLE = True
except ImportError:
    ANTI_TILT_AVAILABLE = False
    logger.warning("⚠️ Anti-Tilt System non disponible")


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
    """
    Gestionnaire de risque pour le trading.
    
    Fonctionnalités:
    - Calcul de la taille de position
    - Limites quotidiennes
    - Limite par symbole (anti sur-exposition)
    - Trailing stop
    - Break-even
    - Drawdown management
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get('risk', {})
        self.risk_per_trade = self.config.get('risk_per_trade', 1.0)
        self.max_daily_loss = self.config.get('max_daily_loss', 5.0)
        self.max_daily_trades = self.config.get('max_daily_trades', 5)
        self.max_open_trades = self.config.get('max_open_trades', 3)
        self.max_trades_per_symbol = self.config.get('max_trades_per_symbol', 1)  # NOUVEAU: limite par symbole
        
        # ✅ FIX: Configuration lot fixe (NOUVELLE FONCTIONNALITÉ)
        self.use_fixed_lot = self.config.get('use_fixed_lot', False)
        self.fixed_lot_size = self.config.get('fixed_lot_size', 0.01)
        
        # Trailing stop
        self.use_trailing = self.config.get('use_trailing_stop', True)
        self.trailing_start = self.config.get('trailing_start_pips', 20)
        self.trailing_distance = self.config.get('trailing_distance_pips', 15)
        
        # Break-even
        self.use_break_even = self.config.get('use_break_even', True)
        self.be_pips = self.config.get('break_even_pips', 15)
        self.be_offset = self.config.get('break_even_offset', 2)
        
        # Stats
        self.daily_trades = 0
        self.daily_pnl = 0.0
        self.open_trades = 0
        self.open_trades_by_symbol: Dict[str, int] = {}  # comptage par symbole
        self.loss_cooldowns: Dict[str, datetime] = {}    # temps de pause après perte
        self.win_cooldowns: Dict[str, datetime] = {}     # temps de pause après gain
        self.consecutive_losses: Dict[str, int] = {}     # compteur de pertes consécutives
        
        # Cooldown configurables
        self.cooldown_after_loss = self.config.get('cooldown_after_loss_min', 30)
        self.cooldown_after_win = self.config.get('cooldown_after_win_min', 5)
        self.max_consecutive_losses = 3  # Max 3 pertes consécutives avant pause longue
        
        # Limites de lots personnalisées
        self.max_lots_forex = self.config.get('max_lots_forex', 1.0)
        self.max_lots_xauusd = self.config.get('max_lots_xauusd', 0.5) # ✅ FIX: Initialisation manquante
        
        # 🔗 GROUPES DE CORRÉLATION (Anti-overexposure)
        self.correlation_groups = {
            "USD_POS": ["EURUSDm", "GBPUSDm", "AUDUSDm", "NZDUSDm"], # USD en dénominateur (souvent corrélés)
            "USD_NEG": ["USDJPY", "USDCHF", "USDCAD"],             # USD en numérateur (souvent corrélés entre eux)
            "CRYPTO": ["BTCUSDm", "ETHUSDm", "SOLUSDm"],
            "XAU": ["XAUUSDm"]
        }
        self.max_trades_per_group = self.config.get('max_trades_per_group', 2) # ✅ 2 trades par groupe pour pyramiding
        
        self.last_reset_date = None
        
        # Log configuration
        if self.use_fixed_lot:
            logger.info(f"📊 Mode LOT FIXE activé: {self.fixed_lot_size} lots par trade")
        else:
            logger.info(f"📊 Mode risque dynamique: {self.risk_per_trade}% par trade")
        
        # ====================================================
        # 🆕 v2.5: Système Anti-Tilt et Kelly Criterion
        # ====================================================
        self.use_anti_tilt = self.config.get('use_anti_tilt', True)
        self.use_kelly = self.config.get('use_kelly', False)
        self.kelly_fraction = self.config.get('kelly_fraction', 0.25)  # Quart-Kelly
        self.kelly_lookback = self.config.get('kelly_lookback', 20)
        
        # Historique des trades pour Kelly
        self.trade_history: deque = deque(maxlen=100)
        
        # Peak equity pour calcul du drawdown
        self.peak_equity = 0.0
        self.current_equity = 0.0
        self.current_drawdown_pct = 0.0
        
        # Paliers de réduction du risque basés sur le drawdown
        self.drawdown_risk_levels = {
            5: 0.75,   # -5% DD → risque à 75%
            10: 0.50,  # -10% DD → risque à 50%
            15: 0.25,  # -15% DD → risque à 25%
            20: 0.0,   # -20% DD → STOP TRADING
        }
        
        # Initialiser le système Anti-Tilt si disponible
        self.anti_tilt = None
        if self.use_anti_tilt and ANTI_TILT_AVAILABLE:
            self.anti_tilt = AntiTiltSystem({
                'base_risk_percent': self.risk_per_trade,
                'max_daily_loss_percent': self.max_daily_loss,
                'max_daily_trades': self.max_daily_trades,
                'use_kelly': self.use_kelly,
                'kelly_fraction': self.kelly_fraction,
                'kelly_lookback': self.kelly_lookback
            })
            logger.info("🛡️ Anti-Tilt System activé")
        elif self.use_anti_tilt:
            logger.warning("⚠️ Anti-Tilt System demandé mais non disponible")
        
        # Kelly Criterion stats
        self.kelly_optimal = 0.0
        self.kelly_adjusted = 0.0
        
        # 🧠 v2.6: Smart Risk Scaling (Prop Firm Logic)
        self.use_smart_scaling = self.config.get('use_smart_scaling', True)
        logger.info(f"🧠 Smart Risk Scaling: {'ON' if self.use_smart_scaling else 'OFF'}")
        
    def calculate_position_size(self, account_balance: float, entry_price: float,
                                stop_loss: float, symbol: str = "EURUSD",
                                symbol_info: Dict = None) -> PositionSize:
        """
        Calcule la taille de position basée sur le risque.
        
        Args:
            account_balance: Solde du compte
            entry_price: Prix d'entrée
            stop_loss: Prix du stop loss
            symbol: Symbole tradé
            symbol_info: Informations dynamiques du symbole depuis MT5 (optionnel)
        """
        # ✅ FIX: Si mode lot fixe activé, retourner directement la taille fixe
        if self.use_fixed_lot:
            pip_value = self._get_pip_value(symbol)
            stop_loss_pips = abs(entry_price - stop_loss) / pip_value if pip_value > 0 else 0
            risk_amount = account_balance * (self.risk_per_trade / 100)
            
            logger.info(f"📊 LOT FIXE: {self.fixed_lot_size} lots (config: use_fixed_lot=True)")
            
            return PositionSize(
                lot_size=self.fixed_lot_size,
                risk_amount=risk_amount,
                pip_value=pip_value,
                stop_loss_pips=stop_loss_pips
            )
        
        # Montant à risquer (mode dynamique)
        risk_amount = account_balance * (self.risk_per_trade / 100)
        
        # Utiliser les données dynamiques si disponibles
        if symbol_info:
            pip_value = symbol_info.get('pip_size', self._get_pip_value(symbol))
            pip_value_per_lot = symbol_info.get('pip_value_per_lot', self._get_pip_value_per_lot(symbol))
            max_lots = symbol_info.get('max_lots', self._get_max_lots(symbol))
            min_lots = symbol_info.get('volume_min', 0.01)
            volume_step = symbol_info.get('volume_step', 0.01)
            min_sl_pips = symbol_info.get('min_sl_pips', 10)
            
            logger.debug(f"🔧 Données dynamiques MT5: pip={pip_value}, pip_value/lot=${pip_value_per_lot:.2f}")
        else:
            pip_value = self._get_pip_value(symbol)
            pip_value_per_lot = self._get_pip_value_per_lot(symbol)
            max_lots = self._get_max_lots(symbol)
            min_lots = 0.01
            volume_step = 0.01
            min_sl_pips = 10
            logger.warning(f"⚠️ Pas de données MT5 dynamiques pour {symbol}, utilisation des fallbacks")
        
        # Calculer les pips de SL
        stop_loss_pips = abs(entry_price - stop_loss) / pip_value
        
        # Protection: SL minimum selon les données MT5
        if stop_loss_pips < min_sl_pips:
            logger.warning(f"Stop loss trop petit ({stop_loss_pips:.1f} pips), utilisation du minimum {min_sl_pips} pips")
            stop_loss_pips = min_sl_pips
            
        # 🚨 SECURITÉ HARDCODÉE XAUUSD
        # Empêche d'ouvrir des trades sur l'or avec des SL ridicules (ex: settings par défaut)
        if "XAU" in symbol and stop_loss_pips < 300:
            logger.warning(f"⚠️ SAFETY: Force SL XAU à 300 pips minimum (Reçu: {stop_loss_pips})")
            stop_loss_pips = 300.0
        
        if stop_loss_pips <= 0:
            logger.warning("Invalid stop loss distance")
            return PositionSize(min_lots, risk_amount, pip_value, 0)
        
        # Taille de position
        lot_size = risk_amount / (stop_loss_pips * pip_value_per_lot)
        
        # Arrondir au volume_step
        lot_size = round(lot_size / volume_step) * volume_step
        
        # Appliquer les limites du broker
        lot_size = max(min_lots, min(max_lots, round(lot_size, 2)))
        
        # Appliquer les limites personnalisées du bot
        if "XAU" in symbol:
            lot_size = min(lot_size, self.max_lots_xauusd)
        else:
            lot_size = min(lot_size, self.max_lots_forex)
        
        logger.info(f"📊 Position size: {lot_size} lots (max: {max_lots}), Risk: ${risk_amount:.2f}, "
                   f"SL: {stop_loss_pips:.1f} pips, Pip value/lot: ${pip_value_per_lot:.2f}")
        
        return PositionSize(
            lot_size=lot_size,
            risk_amount=risk_amount,
            pip_value=pip_value,
            stop_loss_pips=stop_loss_pips
        )
    
    def calculate_position_size_dynamic(self, account_balance: float, entry_price: float,
                                        stop_loss: float, symbol: str, mt5_connector) -> PositionSize:
        """
        Calcule la taille de position avec données MT5 100% dynamiques.
        
        Args:
            mt5_connector: Instance de MT5Connector pour récupérer les données
        """
        # Récupérer les données dynamiques depuis MT5
        symbol_info = mt5_connector.get_dynamic_pip_info(symbol)
        
        return self.calculate_position_size(
            account_balance=account_balance,
            entry_price=entry_price,
            stop_loss=stop_loss,
            symbol=symbol,
            symbol_info=symbol_info
        )
    
    def _get_pip_value(self, symbol: str) -> float:
        """Valeurs fallback si pas de données MT5."""
        if "JPY" in symbol:
            return 0.01
        elif "XAU" in symbol:
            return 0.01
        else:
            return 0.0001
    
    def _get_pip_value_per_lot(self, symbol: str) -> float:
        """Valeurs fallback si pas de données MT5."""
        if "XAU" in symbol:
            return 1.0
        elif "JPY" in symbol.upper()[-3:]:
            return 10.0
        else:
            return 10.0
    
    def _get_max_lots(self, symbol: str) -> float:
        """Valeurs fallback si pas de données MT5."""
        if "XAU" in symbol:
            return 0.5
        else:
            return 1.0
    
    def validate_stops(self, entry_price: float, stop_loss: float, 
                      take_profit: float, direction: str, symbol: str = "EURUSD") -> tuple:
        """
        Valide que les stops sont corrects pour la direction du trade.
        
        Returns:
            (is_valid, corrected_sl, corrected_tp, message)
        """
        pip_value = self._get_pip_value(symbol)
        min_distance = 10 * pip_value  # Distance minimum de 10 pips
        
        if direction.upper() == "BUY":
            # Pour un BUY: SL doit être SOUS entry, TP doit être AU-DESSUS
            if stop_loss >= entry_price:
                # Corriger le SL
                corrected_sl = entry_price - min_distance
                logger.warning(f"⚠️ SL corrigé pour BUY: {stop_loss:.5f} -> {corrected_sl:.5f}")
                stop_loss = corrected_sl
            
            if take_profit <= entry_price:
                # Corriger le TP
                risk = entry_price - stop_loss
                corrected_tp = entry_price + (risk * 2)  # RR 1:2
                logger.warning(f"⚠️ TP corrigé pour BUY: {take_profit:.5f} -> {corrected_tp:.5f}")
                take_profit = corrected_tp
                
        else:  # SELL
            # Pour un SELL: SL doit être AU-DESSUS entry, TP doit être SOUS
            if stop_loss <= entry_price:
                corrected_sl = entry_price + min_distance
                logger.warning(f"⚠️ SL corrigé pour SELL: {stop_loss:.5f} -> {corrected_sl:.5f}")
                stop_loss = corrected_sl
            
            if take_profit >= entry_price:
                risk = stop_loss - entry_price
                corrected_tp = entry_price - (risk * 2)
                logger.warning(f"⚠️ TP corrigé pour SELL: {take_profit:.5f} -> {corrected_tp:.5f}")
                take_profit = corrected_tp
        
        # Vérifier distance minimum
        sl_distance = abs(entry_price - stop_loss) / pip_value
        if sl_distance < 5:
            return False, stop_loss, take_profit, "SL trop proche (< 5 pips)"
        
        return True, stop_loss, take_profit, "OK"
    
    def can_open_trade(self, symbol: str = None) -> tuple:
        """
        Vérifie si on peut ouvrir un nouveau trade.
        
        Args:
            symbol: Symbole pour vérifier la limite par paire (optionnel mais recommandé)
        """
        self._check_daily_reset()
        self._sync_open_trades()  # Synchroniser avec MT5
        
        reasons = []
        
        # Vérifier limite globale
        if self.open_trades >= self.max_open_trades:
            reasons.append(f"Max trades ouverts atteint ({self.max_open_trades})")
            return False, reasons
        
        # Vérifier limite par symbole (anti sur-exposition)
        if symbol and self.max_trades_per_symbol > 0:
            symbol_trades = self.open_trades_by_symbol.get(symbol, 0)
            if symbol_trades >= self.max_trades_per_symbol:
                reasons.append(f"Max trades pour {symbol} atteint ({self.max_trades_per_symbol})")
                return False, reasons
        
        # 🔗 Vérifier les corrélations (Optionnel par défaut, activé si max_trades_per_group > 0)
        if symbol and self.max_trades_per_group > 0:
            correlation_ok, corr_reasons = self._check_correlation_group(symbol)
            if not correlation_ok:
                reasons.extend(corr_reasons)
                return False, reasons
        
        if self.daily_trades >= self.max_daily_trades:
            reasons.append(f"Max trades quotidiens atteint ({self.max_daily_trades})")
            return False, reasons
        
        if abs(self.daily_pnl) >= self.max_daily_loss:
            reasons.append(f"Perte quotidienne max atteinte ({self.max_daily_loss}%)")
            return False, reasons
            
        # Vérifier cooldown après perte
        if symbol and symbol in self.loss_cooldowns:
            cooldown_end = self.loss_cooldowns[symbol] + timedelta(minutes=self.cooldown_after_loss)
            if datetime.now() < cooldown_end:
                remaining = (cooldown_end - datetime.now()).total_seconds() / 60
                reasons.append(f"⏱️ Pause après perte sur {symbol} ({remaining:.0f} min restantes)")
                return False, reasons
        
        # Vérifier cooldown après gain (plus court)
        if symbol and symbol in self.win_cooldowns:
            cooldown_end = self.win_cooldowns[symbol] + timedelta(minutes=self.cooldown_after_win)
            if datetime.now() < cooldown_end:
                remaining = (cooldown_end - datetime.now()).total_seconds() / 60
                reasons.append(f"⏱️ Pause après gain sur {symbol} ({remaining:.0f} min restantes)")
                return False, reasons
        
        # Vérifier pertes consécutives (pause longue après 3 pertes)
        if symbol:
            consecutive = self.consecutive_losses.get(symbol, 0)
            if consecutive >= self.max_consecutive_losses:
                reasons.append(f"🛑 {consecutive} pertes consécutives sur {symbol} - Pause longue activée")
                return False, reasons
        
        return True, ["Risque OK ✓"]
    
    def _sync_open_trades(self):
        """Synchronise le comptage des trades ouverts avec MT5."""
        try:
            import MetaTrader5 as mt5
            positions = mt5.positions_get()
            
            if positions is not None:
                self.open_trades = len(positions)
                
                # Compter par symbole
                self.open_trades_by_symbol = {}
                for pos in positions:
                    symbol = pos.symbol
                    self.open_trades_by_symbol[symbol] = self.open_trades_by_symbol.get(symbol, 0) + 1
        except Exception as e:
            logger.debug(f"Could not sync with MT5: {e}")
    
    def _check_daily_reset(self):
        """Reset les compteurs quotidiens si nouveau jour."""
        from datetime import date
        today = date.today()
        
        if self.last_reset_date != today:
            self.daily_trades = 0
            self.daily_pnl = 0.0
            self.last_reset_date = today
            logger.info("Daily stats reset")
    
    def on_trade_opened(self, symbol: str = None):
        """Appelé quand un trade est ouvert."""
        self.daily_trades += 1
        self.open_trades += 1
        
        if symbol:
            self.open_trades_by_symbol[symbol] = self.open_trades_by_symbol.get(symbol, 0) + 1
        
        logger.debug(f"Trade opened. Daily: {self.daily_trades}, Open: {self.open_trades}")
    
    def on_trade_closed(self, pnl_percent: float, symbol: str = None):
        """Appelé quand un trade est fermé."""
        self.open_trades = max(0, self.open_trades - 1)
        self.daily_pnl += pnl_percent
        
        if symbol and symbol in self.open_trades_by_symbol:
            self.open_trades_by_symbol[symbol] = max(0, self.open_trades_by_symbol[symbol] - 1)
            
        # Si c'est une perte
        if pnl_percent < 0 and symbol:
            self.loss_cooldowns[symbol] = datetime.now()
            
            # Incrémenter compteur de pertes consécutives
            self.consecutive_losses[symbol] = self.consecutive_losses.get(symbol, 0) + 1
            consecutive = self.consecutive_losses[symbol]
            
            if consecutive >= self.max_consecutive_losses:
                logger.error(f"🛑 [RISK] {consecutive} pertes consécutives sur {symbol}! Pause de 2h activée.")
                self.loss_cooldowns[symbol] = datetime.now() + timedelta(hours=2)  # Pause longue de 2h
            else:
                logger.warning(f"🔴 [RISK] Perte #{consecutive} sur {symbol} ({pnl_percent:.2f}%). Pause {self.cooldown_after_loss} min.")
        
        # Si c'est un gain
        elif pnl_percent > 0 and symbol:
            self.win_cooldowns[symbol] = datetime.now()
            # Reset du compteur de pertes consécutives
            self.consecutive_losses[symbol] = 0
            logger.info(f"🟢 [RISK] Gain sur {symbol} (+{pnl_percent:.2f}%). Pause {self.cooldown_after_win} min puis OK.")
        
        logger.debug(f"Trade closed. PnL: {pnl_percent:.2f}%, Daily PnL: {self.daily_pnl:.2f}%")

    def _check_correlation_group(self, symbol: str) -> tuple:
        """
        Vérifie si un trade est déjà ouvert dans le même groupe de corrélation.
        
        Returns:
            (is_ok, reasons)
        """
        active_group = None
        group_name = "Inconnu"
        
        # Trouver à quel groupe appartient le symbole
        for name, symbols in self.correlation_groups.items():
            if symbol in symbols:
                active_group = symbols
                group_name = name
                break
        
        if not active_group:
            return True, []
            
        # Compter combien de trades sont ouverts dans ce groupe
        trades_in_group = 0
        opened_symbols = []
        for s, count in self.open_trades_by_symbol.items():
            if s in active_group and count > 0:
                trades_in_group += count
                opened_symbols.append(s)
                
        if trades_in_group >= self.max_trades_per_group:
            msg = f"Limite de corrélation atteinte pour {group_name} ({trades_in_group}/{self.max_trades_per_group} ouvert sur {', '.join(opened_symbols)})"
            return False, [msg]
            
        return True, []
    
    def calculate_trailing_stop(self, entry_price: float, current_price: float,
                                current_sl: float, direction: str, symbol: str = "EURUSD") -> Optional[float]:
        """
        Calcule le nouveau trailing stop.
        
        Args:
            entry_price: Prix d'entrée
            current_price: Prix actuel
            current_sl: Stop-loss actuel
            direction: Direction du trade ("BUY" ou "SELL")
            symbol: Symbole pour calcul dynamique du pip
        
        Returns:
            Nouveau SL ou None si pas de changement
        """
        if not self.use_trailing:
            return None
        
        # ✅ FIX: Pip value dynamique basé sur le symbole
        pip_value = self._get_pip_value(symbol)
        trailing_start = self.trailing_start * pip_value
        trailing_dist = self.trailing_distance * pip_value
        
        if direction.upper() == "BUY":
            profit = current_price - entry_price
            if profit >= trailing_start:
                new_sl = current_price - trailing_dist
                if new_sl > current_sl:
                    return new_sl
        else:
            profit = entry_price - current_price
            if profit >= trailing_start:
                new_sl = current_price + trailing_dist
                if new_sl < current_sl:
                    return new_sl
        
        return None
    
    def calculate_break_even(self, entry_price: float, current_price: float,
                            current_sl: float, direction: str, symbol: str = "EURUSD") -> Optional[float]:
        """
        Calcule le break-even.
        
        Args:
            entry_price: Prix d'entrée
            current_price: Prix actuel
            current_sl: Stop-loss actuel
            direction: Direction du trade ("BUY" ou "SELL")
            symbol: Symbole pour calcul dynamique du pip
        
        Returns:
            Nouveau SL au BE ou None
        """
        if not self.use_break_even:
            return None
        
        # ✅ FIX: Pip value dynamique basé sur le symbole
        pip_value = self._get_pip_value(symbol)
        be_trigger = self.be_pips * pip_value
        be_offset = self.be_offset * pip_value
        
        if direction.upper() == "BUY":
            profit = current_price - entry_price
            if profit >= be_trigger and current_sl < entry_price:
                return entry_price + be_offset
        else:
            profit = entry_price - current_price
            if profit >= be_trigger and current_sl > entry_price:
                return entry_price - be_offset
        
        return None
    
    def get_stats(self) -> TradeStats:
        """Retourne les statistiques de trading."""
        return TradeStats(
            total_trades=len(self.trade_history),
            winning_trades=sum(1 for t in self.trade_history if t.get('is_win', False)),
            losing_trades=sum(1 for t in self.trade_history if not t.get('is_win', True)),
            win_rate=self._calculate_win_rate(),
            total_profit=sum(t.get('pnl', 0) for t in self.trade_history),
            daily_profit=self.daily_pnl,
            daily_trades=self.daily_trades,
            max_drawdown=self.current_drawdown_pct
        )
    
    # ====================================================
    # 🆕 v2.5: Méthodes Kelly Criterion & Anti-Tilt
    # ====================================================
    
    def update_equity(self, current_equity: float, trade_pnl: float = None, 
                      is_win: bool = None, symbol: str = None):
        """
        Met à jour l'equity et les statistiques après un trade.
        
        Args:
            current_equity: Équité actuelle du compte
            trade_pnl: PnL du dernier trade (en $)
            is_win: Si le trade était gagnant
            symbol: Symbole du trade
        """
        self.current_equity = current_equity
        
        # Mettre à jour le peak equity
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
        
        # Calculer le drawdown actuel
        if self.peak_equity > 0:
            self.current_drawdown_pct = (
                (self.peak_equity - current_equity) / self.peak_equity * 100
            )
        
        # Enregistrer le trade si fourni
        if trade_pnl is not None:
            if is_win is None:
                is_win = trade_pnl > 0
            
            self.trade_history.append({
                'pnl': trade_pnl,
                'is_win': is_win,
                'symbol': symbol,
                'time': datetime.now()
            })
            
            # Mettre à jour les statistiques Kelly
            if self.use_kelly and len(self.trade_history) >= 10:
                self._calculate_kelly()
        
        # Mettre à jour le système Anti-Tilt si disponible
        if self.anti_tilt:
            self.anti_tilt.update_equity(current_equity, trade_pnl, is_win)
        
        logger.debug(f"📊 Equity updated: ${current_equity:.2f} | DD: {self.current_drawdown_pct:.1f}%")
    
    def _calculate_kelly(self):
        """Calcule le Kelly Criterion optimal basé sur l'historique récent."""
        recent = list(self.trade_history)[-self.kelly_lookback:]
        
        if len(recent) < 10:
            return
        
        wins = [t for t in recent if t.get('is_win', False)]
        losses = [t for t in recent if not t.get('is_win', True)]
        
        if not wins or not losses:
            return
        
        # Win rate
        W = len(wins) / len(recent)
        
        # Ratio gain/perte moyen
        avg_win = np.mean([t.get('pnl', 0) for t in wins])
        avg_loss = abs(np.mean([t.get('pnl', 0) for t in losses]))
        
        if avg_loss == 0:
            return
        
        R = avg_win / avg_loss
        
        # Formule Kelly: f* = W - (1-W)/R
        kelly = W - ((1 - W) / R)
        
        # Kelly peut être négatif si pas d'edge
        self.kelly_optimal = max(0, kelly * 100)
        
        # Appliquer la fraction de Kelly
        self.kelly_adjusted = self.kelly_optimal * self.kelly_fraction
        
        # Plafonner à 5% maximum
        self.kelly_adjusted = min(self.kelly_adjusted, 5.0)
        
        logger.debug(f"📊 Kelly: W={W:.1%}, R={R:.2f}, "
                    f"Optimal={self.kelly_optimal:.2f}%, Adjusted={self.kelly_adjusted:.2f}%")
    
    def _calculate_win_rate(self) -> float:
        """Calcule le win rate des trades récents."""
        if not self.trade_history:
            return 0.0
        
        wins = sum(1 for t in self.trade_history if t.get('is_win', False))
        return wins / len(self.trade_history)
    
    def get_adjusted_risk_percent(self) -> Tuple[float, str, List[str]]:
        """
        Calcule le risque ajusté en fonction de l'état actuel.
        
        Returns:
            (risk_percent, reason, warnings)
        """
        warnings = []
        
        # Si Anti-Tilt est disponible, utiliser son calcul
        if self.anti_tilt:
            result = self.anti_tilt.get_adjusted_risk()
            return result.adjusted_risk_percent, result.reason, result.warnings
        
        # Sinon, calculer manuellement
        
        # Risque de base
        if self.use_kelly and self.kelly_adjusted > 0:
            base_risk = self.kelly_adjusted
            reason = f"Kelly Criterion ({self.kelly_fraction*100:.0f}%)"
        else:
            base_risk = self.risk_per_trade
            reason = "Fixed Risk"
        
        # Calculer le multiplicateur basé sur le drawdown
        multiplier = 1.0
        for dd_level, mult in sorted(self.drawdown_risk_levels.items()):
            if self.current_drawdown_pct >= dd_level:
                multiplier = mult
        
        if multiplier < 1.0:
            warnings.append(f"⚠️ Risque réduit (DD: {self.current_drawdown_pct:.1f}%)")
        
        if multiplier == 0:
            warnings.append("🛑 Trading paused (DD >= 20%)")
        
        # 🧠 2. Smart Scaling (Win/Loss Streak Adjustment)
        if self.use_smart_scaling:
            recent_trades = list(self.trade_history)[-3:] if self.trade_history else []
            
            # Après une perte: Recovery Mode (-50% risque)
            if recent_trades and not recent_trades[-1].get('is_win', True):
                multiplier *= 0.5
                warnings.append("📉 Scaling DOWN (Last was Loss) -> 50% Risk")
            
            # Après 2 gains consécutifs: Confidence Boost (+25% risque)
            elif len(recent_trades) >= 2 and all(t.get('is_win', False) for t in recent_trades[-2:]):
                multiplier *= 1.25
                # Cap multiplier to avoiding going crazy (max 2.0x base risk)
                if multiplier > 2.0: multiplier = 2.0
                reason += " + Scaling UP (Winning Streak)"
        
        adjusted_risk = base_risk * multiplier
        
        return adjusted_risk, reason, warnings
    
    def get_anti_tilt_status(self) -> Dict:
        """Retourne le status du système Anti-Tilt."""
        if self.anti_tilt:
            return self.anti_tilt.get_status()
        
        # Status simplifié si Anti-Tilt non disponible
        return {
            'equity': {
                'current': self.current_equity,
                'peak': self.peak_equity,
                'drawdown_pct': self.current_drawdown_pct
            },
            'kelly': {
                'optimal': self.kelly_optimal,
                'adjusted': self.kelly_adjusted,
                'enabled': self.use_kelly
            },
            'trades_today': self.daily_trades,
            'anti_tilt_available': ANTI_TILT_AVAILABLE
        }
    
    def reset_peak_equity(self, new_peak: float = None):
        """Reset le peak equity (ex: après ajout de capital)."""
        if new_peak:
            self.peak_equity = new_peak
        else:
            self.peak_equity = self.current_equity
        
        self.current_drawdown_pct = 0.0
        logger.info(f"🔄 Peak equity reset to ${self.peak_equity:.2f}")
        
        if self.anti_tilt:
            self.anti_tilt.reset_stop()

