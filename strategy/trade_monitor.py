"""
Trade Monitor - Gestion post-trade des positions ouvertes
- Trailing Stop Loss
- Break-even automatique
- Partial Close
"""

import MetaTrader5 as mt5
from loguru import logger
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class TradeManagementConfig:
    # Trailing Stop
    trailing_enabled: bool = True
    trailing_mode: str = 'structure' # 'fixed' ou 'structure' (SMC Pur)
    trailing_activation_pips: float = 20
    trailing_distance_pips: float = 15

    # Break-even
    break_even_enabled: bool = True
    break_even_trigger_rr: float = 1.5
    break_even_offset_pips: float = 2

    # Partial Close
    partial_close_enabled: bool = True
    partial_first_target_rr: float = 2.0
    partial_close_percent: float = 50


class TradeMonitor:
    """
    Surveille et gère les positions ouvertes avec une approche institutionnelle (RR).
    """

    def __init__(self, config: Dict, magic_number: int = 123456):
        self.full_config = config
        self.magic_number = magic_number
        # Mapping correct avec settings.yaml (risk.management)
        risk_mgmt = config.get("risk", {}).get("management", {})

        self.config = TradeManagementConfig(
            trailing_enabled=risk_mgmt.get("trailing_stop", True),
            trailing_activation_pips=20,  # Fallback
            trailing_distance_pips=15,  # Fallback
            break_even_enabled=risk_mgmt.get("break_even_enabled", True),
            break_even_trigger_rr=risk_mgmt.get("break_even_trigger", 1.5),
            break_even_offset_pips=risk_mgmt.get("break_even_offset", 2),
            partial_close_enabled=risk_mgmt.get("partial_close", True),
            partial_first_target_rr=risk_mgmt.get("partial_close_trigger", 2.0),
            partial_close_percent=risk_mgmt.get("partial_close_pct", 0.5) * 100,
        )
        # Trailing triggers in RR if possible
        self.trailing_trigger_rr = risk_mgmt.get("trailing_trigger", 1.5)

        # État des positions gérées
        self.managed_positions: Dict[int, Dict] = {}

        logger.info(
            f"TradeMonitor initialized - Trailing: {self.config.trailing_enabled}, "
            f"Break-even: {self.config.break_even_enabled}"
        )

    def _get_symbol_mgmt_config(self, symbol: str) -> Dict:
        """Récupère les overrides de gestion de trade pour un symbole spécifique."""
        symbols = self.full_config.get("symbols", [])
        symbol_cfg = next((s for s in symbols if s["name"] == symbol), {})
        return symbol_cfg.get("risk_overrides", {})

    def get_pip_size(self, symbol: str) -> float:
        """Retourne la taille d'un pip pour le symbole."""
        info = mt5.symbol_info(symbol)
        if info is None:
            return 0.0001

        # Logique unifiée pour les pips (0.01 pour Or/Crypto/JPY, 0.0001 pour Forex)
        symbol_upper = symbol.upper()
        if any(x in symbol_upper for x in ["JPY", "XAU", "BTC", "ETH"]):
            return 0.01
        return 0.0001

    def get_current_profit_pips(self, position) -> float:
        """Calcule le profit actuel en pips."""
        symbol = position.symbol
        pip_size = self.get_pip_size(symbol)

        if position.type == mt5.ORDER_TYPE_BUY:
            current_price = mt5.symbol_info_tick(symbol).bid
            profit_pips = (current_price - position.price_open) / pip_size
        else:  # SELL
            current_price = mt5.symbol_info_tick(symbol).ask
            profit_pips = (position.price_open - current_price) / pip_size

        return profit_pips

    def check_and_manage_positions(self) -> List[Dict]:
        """
        Vérifie et gère toutes les positions ouvertes.
        Retourne une liste d'actions effectuées.
        """
        actions = []

        positions = mt5.positions_get()
        if positions is None or len(positions) == 0:
            return actions

        for position in positions:
            # Sécurité: Ne gérer que les positions du bot
            if self.magic_number != 0 and position.magic != self.magic_number:
                continue

            ticket = position.ticket
            profit_pips = self.get_current_profit_pips(position)

            # Initialiser le suivi si nouvelle position
            if ticket not in self.managed_positions:
                self.managed_positions[ticket] = {
                    "break_even_done": False,
                    "partial_close_done": False,
                    "highest_profit_pips": 0,
                }

            state = self.managed_positions[ticket]

            # Calcul du RR actuel
            current_rr = 0.0
            sl_dist = abs(position.price_open - position.sl) if position.sl > 0 else 0
            if sl_dist > 0:
                profit_abs = abs(position.price_current - position.price_open)
                current_rr = profit_abs / sl_dist

            # Détection asset class
            is_crypto = any(kw in position.symbol.upper() for kw in ["BTC", "ETH", "SOL", "CRYPTO"])

            # Mettre à jour le profit max
            if profit_pips > state.get("highest_profit_pips", 0):
                state["highest_profit_pips"] = profit_pips

            # 1. Break-even (Priorité RR, fallback Pips)
            if self.config.break_even_enabled and not state["break_even_done"]:
                # Mode Dynamique Crypto: BE plus agressif à 1.0 RR (ou 0.8 RR)
                be_trigger_rr = self.config.break_even_trigger_rr
                if is_crypto:
                    be_trigger_rr = min(be_trigger_rr, 1.0)  # Sécuriser vite les cryptos

                if current_rr >= be_trigger_rr:
                    action = self._apply_break_even(position, current_rr)
                    if action:
                        state["break_even_done"] = True
                        actions.append(action)

            # 2. Trailing Stop
            if self.config.trailing_enabled:
                # Si on a un trigger RR pour le trailing
                if current_rr >= self.trailing_trigger_rr:
                    action = self._check_trailing_stop(position, profit_pips, state)
                    if action:
                        actions.append(action)

            # 3. Partial Close (Prise de profit institutionnelle)
            if self.config.partial_close_enabled and not state.get("partial_close_done", False):
                if current_rr >= self.config.partial_first_target_rr:
                    action = self._apply_partial_close(position, current_rr)
                    if action:
                        state["partial_close_done"] = True
                        actions.append(action)

        return actions

    def _apply_partial_close(self, position, current_rr: float) -> Optional[Dict]:
        """Exécute une clôture partielle sur MT5."""
        symbol = position.symbol
        close_pct = self.config.partial_close_percent

        from broker.order_manager import OrderManager

        om = OrderManager(magic_number=self.magic_number)

        result = om.partial_close(position.ticket, close_percent=close_pct)
        if result.success:
            logger.info(
                f"💰 PARTIAL CLOSE: {symbol} #{position.ticket} - {close_pct:.0f}% fermé à RR {current_rr:.2f}"
            )
            return {
                "action": "partial_close",
                "ticket": position.ticket,
                "symbol": symbol,
                "rr": current_rr,
            }
        return None

    def _apply_break_even(self, position, current_rr: float) -> Optional[Dict]:
        """Applique physiquement le break-even sur MT5."""
        symbol = position.symbol
        pip_size = self.get_pip_size(symbol)
        offset_pips = self.config.break_even_offset_pips

        # Calculer le nouveau SL (entry + offset)
        if position.type == mt5.ORDER_TYPE_BUY:
            new_sl = position.price_open + (offset_pips * pip_size)
            if position.sl >= (new_sl - (0.1 * pip_size)):
                return None
        else:  # SELL
            new_sl = position.price_open - (offset_pips * pip_size)
            if position.sl > 0 and position.sl <= (new_sl + (0.1 * pip_size)):
                return None

        success = self._modify_sl(position.ticket, new_sl, position.tp)
        if success:
            logger.info(
                f"🔒 DYNAMIC BE: {symbol} #{position.ticket} activé à RR {current_rr:.2f} (SL: {new_sl})"
            )
            return {
                "action": "break_even",
                "ticket": position.ticket,
                "symbol": symbol,
                "rr": current_rr,
            }
        return None

    def _find_structure_level(self, symbol: str, direction: int, timeframe=mt5.TIMEFRAME_M15) -> Optional[float]:
        """
        Trouve le dernier niveau structurel valide (Fractal) pour le trailing stop.
        direction: 0 (BUY) -> Cherche dernier Higher Low
        direction: 1 (SELL) -> Cherche dernier Lower High
        """
        try:
            # Récupérer les 30 dernières bougies
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 30)
            if rates is None or len(rates) < 5:
                return None
                
            # Convertir en DataFrame simple ou utiliser numpy
            # On cherche un pattern High-Low-High-Low (Fractal 5 barres classique)
            # Indice -1 est la bougie en cours (non finie), on regarde de -2 à -30
            
            for i in range(2, len(rates) - 2):
                idx = len(rates) - 1 - i
                current = rates[idx]
                
                if direction == 0: # BUY -> Cherche Swing Low (Support)
                    # Pattern: Low[i] < Low[i-1] et Low[i] < Low[i+1]
                    if (current['low'] < rates[idx-1]['low'] and 
                        current['low'] < rates[idx+1]['low'] and
                        current['low'] < rates[idx-2]['low'] and 
                        current['low'] < rates[idx+2]['low']):
                        return current['low']
                        
                else: # SELL -> Cherche Swing High (Résistance)
                    if (current['high'] > rates[idx-1]['high'] and 
                        current['high'] > rates[idx+1]['high'] and
                        current['high'] > rates[idx-2]['high'] and 
                        current['high'] > rates[idx+2]['high']):
                        return current['high']
                        
            return None
        except Exception as e:
            logger.error(f"Erreur structure trailing: {e}")
            return None

    def _check_trailing_stop(self, position, profit_pips: float, state: Dict) -> Optional[Dict]:
        """Vérifie et applique le trailing stop si les conditions sont remplies."""
        symbol = position.symbol
        symbol_overrides = self._get_symbol_mgmt_config(symbol)

        activation_pips = symbol_overrides.get(
            "trailing_start_pips", self.config.trailing_activation_pips
        )
        distance_pips = symbol_overrides.get(
            "trailing_distance_pips", self.config.trailing_distance_pips
        )

        if profit_pips < activation_pips:
            return None

        pip_size = self.get_pip_size(symbol)
        
        # Mode : Structure ou Fixe
        trailing_mode = self.config.trailing_mode
        structure_level = None
        
        if trailing_mode == 'structure':
            structure_level = self._find_structure_level(symbol, position.type)
            if structure_level:
                # Ajouter un petit buffer de sécurité (ex: 2 pips)
                buffer = 2 * pip_size
                if position.type == mt5.ORDER_TYPE_BUY:
                    structure_level -= buffer
                else:
                    structure_level += buffer

        current_tick = mt5.symbol_info_tick(symbol)

        if position.type == mt5.ORDER_TYPE_BUY:
            current_price = current_tick.bid
            
            # Calcul du SL optimal
            if trailing_mode == 'structure' and structure_level and structure_level > position.price_open:
                # Trailing sur structure (si valide et au-dessus de l'entrée pour sécuriser)
                optimal_sl = structure_level
            else:
                # Fallback ou mode fixe
                optimal_sl = current_price - (distance_pips * pip_size)

            # Ne modifier que si le nouveau SL est meilleur (plus haut pour un BUY)
            # Et surtout: ne JAMAIS redescendre le SL
            if optimal_sl > position.sl + (pip_size * 0.5):
                # Vérifier la distance minimale au prix actuel (Stops Level)
                sym_info = mt5.symbol_info(symbol)
                if sym_info:
                    stops_level = sym_info.trade_stops_level * sym_info.point
                    if current_price - optimal_sl < stops_level:
                        return None # Trop proche du prix actuel
                else:
                    return None
                
                success = self._modify_sl(position.ticket, optimal_sl, position.tp)
                if success:
                    mode_str = "STRUCTURE" if trailing_mode == 'structure' and structure_level else "FIXED"
                    logger.info(
                        f"📈 TRAILING ({mode_str}): {symbol} #{position.ticket} - SL trailing à {optimal_sl:.5f}"
                    )
                    return {
                        "action": "trailing_stop",
                        "ticket": position.ticket,
                        "symbol": symbol,
                        "new_sl": optimal_sl,
                        "profit_pips": profit_pips,
                    }
                    
        else:  # mt5.ORDER_TYPE_SELL
            current_price = current_tick.ask
            
            if trailing_mode == 'structure' and structure_level and structure_level < position.price_open:
                optimal_sl = structure_level
            else:
                optimal_sl = current_price + (distance_pips * pip_size)

            # Ne modifier que si le nouveau SL est meilleur (plus bas pour un SELL)
            # SL actuel = 0 signifie pas de SL, donc on peut mettre le nouveau
            if position.sl == 0 or (optimal_sl < position.sl - (pip_size * 0.5)):
                # Vérifier distance min
                sym_info = mt5.symbol_info(symbol)
                if sym_info:
                    stops_level = sym_info.trade_stops_level * sym_info.point
                    if optimal_sl - current_price < stops_level:
                        return None
                else:
                    return None
                    
                success = self._modify_sl(position.ticket, optimal_sl, position.tp)
                if success:
                    mode_str = "STRUCTURE" if trailing_mode == 'structure' and structure_level else "FIXED"
                    logger.info(
                        f"📈 TRAILING ({mode_str}): {symbol} #{position.ticket} - SL trailing à {optimal_sl:.5f}"
                    )
                    return {
                        "action": "trailing_stop",
                        "ticket": position.ticket,
                        "symbol": symbol,
                        "new_sl": optimal_sl,
                        "profit_pips": profit_pips,
                    }

        return None

    def _modify_sl(self, ticket: int, new_sl: float, tp: float) -> bool:
        """Modifie le Stop Loss d'une position."""
        request = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": new_sl, "tp": tp}

        result = mt5.order_send(request)

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        elif result.retcode == mt5.TRADE_RETCODE_NO_CHANGES:
            return True
        else:
            logger.warning(f"⚠️ Échec modification SL #{ticket}: {result.comment}")
            return False

    def cleanup_closed_positions(self) -> List[int]:
        """Nettoie les positions fermées du suivi et retourne les tickets fermés."""
        current_tickets = set()
        positions = mt5.positions_get()

        if positions:
            current_tickets = {p.ticket for p in positions}

        closed_tickets = [t for t in self.managed_positions.keys() if t not in current_tickets]

        for ticket in closed_tickets:
            del self.managed_positions[ticket]
            logger.debug(f"Position #{ticket} fermée, retirée du suivi")

        return closed_tickets

    def get_status(self) -> Dict:
        """Retourne le statut du monitoring."""
        return {
            "managed_positions": len(self.managed_positions),
            "config": {
                "trailing_enabled": self.config.trailing_enabled,
                "break_even_enabled": self.config.break_even_enabled,
                "trailing_activation": f"{self.config.trailing_activation_pips} pips",
                "break_even_trigger": f"{self.config.break_even_trigger_pips} pips",
            },
        }
