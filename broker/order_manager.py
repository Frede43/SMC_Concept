"""
Order Manager
Gestion des ordres et positions
"""

import MetaTrader5 as mt5
from typing import Optional, Dict, Any
from loguru import logger
from dataclasses import dataclass


@dataclass
class OrderResult:
    success: bool
    ticket: Optional[int]
    message: str
    price: Optional[float] = None


class OrderManager:
    """
    Gestionnaire d'ordres pour MetaTrader 5.
    
    Fonctionnalités:
    - Ouvrir des positions (market orders)
    - Placer des ordres en attente
    - Modifier SL/TP
    - Fermer des positions
    """
    
    def __init__(self, magic_number: int = 123456):
        self.magic_number = magic_number
        
    def open_market_order(self, symbol: str, order_type: str, volume: float,
                         sl: float = 0, tp: float = 0, comment: str = "") -> OrderResult:
        """
        Ouvre un ordre au marché.
        
        Args:
            symbol: Symbole à trader
            order_type: "BUY" ou "SELL"
            volume: Taille du lot
            sl: Stop loss (0 = pas de SL)
            tp: Take profit (0 = pas de TP)
            comment: Commentaire de l'ordre
        """
        # Vérifier le symbole
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return OrderResult(False, None, f"Symbol {symbol} not found")
        
        if not symbol_info.visible:
            if not mt5.symbol_select(symbol, True):
                return OrderResult(False, None, f"Failed to select {symbol}")
        
        # Récupérer le prix actuel
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return OrderResult(False, None, "Failed to get tick data")
        
        # Déterminer le type d'ordre et le prix
        if order_type.upper() == "BUY":
            mt5_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            mt5_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        
        # ✅ FIX: Validation pré-ordre - SL/TP obligatoire
        if sl == 0 or tp == 0:
            logger.warning(f"⚠️ SL ou TP = 0 pour {symbol}! Ordre risqué sans stop-loss!")
        
        # ✅ FIX: Smart Validation & Correction (Spread & Side Protection)
        current_spread = tick.ask - tick.bid
        # Minimum distance acceptable: Spread * 1.2 ou StopsLevel du broker
        stops_level = symbol_info.trade_stops_level * symbol_info.point
        min_accepted_dist = max(current_spread * 1.2, stops_level)
        
        modified_stops = False
        
        if order_type.upper() == "BUY":
            # Validation SL (Doit être SOUS le prix)
            if sl > 0:
                # 1. Vérifier le sens
                if sl >= price:
                    logger.warning(f"⚠️ SL BUY invalide ({sl} >= {price}) -> Correction auto")
                    # On place le SL à une distance sûre (par défaut 2x spread)
                    sl = price - (min_accepted_dist * 2.0)
                    modified_stops = True
                
                # 2. Vérifier la distance min (Spread)
                elif (price - sl) < min_accepted_dist:
                    logger.warning(f"⚠️ SL BUY trop proche (Spread: {current_spread}) -> Ajustement")
                    sl = price - min_accepted_dist
                    modified_stops = True

            # Validation TP (Doit être SUR le prix)
            if tp > 0:
                # 1. Vérifier le sens
                if tp <= price:
                    logger.warning(f"⚠️ TP BUY invalide ({tp} <= {price}) -> Correction auto")
                    tp = price + (min_accepted_dist * 2.0)
                    modified_stops = True
                
                # 2. Vérifier la distance min
                elif (tp - price) < min_accepted_dist:
                    logger.warning(f"⚠️ TP BUY trop proche -> Ajustement")
                    tp = price + min_accepted_dist
                    modified_stops = True
                    
        else: # SELL
            # Validation SL (Doit être SUR le prix)
            if sl > 0:
                # 1. Vérifier le sens
                if sl <= price:
                    logger.warning(f"⚠️ SL SELL invalide ({sl} <= {price}) -> Correction auto")
                    sl = price + (min_accepted_dist * 2.0)
                    modified_stops = True
                
                # 2. Vérifier la distance min
                elif (sl - price) < min_accepted_dist:
                    logger.warning(f"⚠️ SL SELL trop proche (Spread: {current_spread}) -> Ajustement")
                    sl = price + min_accepted_dist
                    modified_stops = True

            # Validation TP (Doit être SOUS le prix)
            if tp > 0:
                # 1. Vérifier le sens
                if tp >= price:
                    logger.warning(f"⚠️ TP SELL invalide ({tp} >= {price}) -> Correction auto")
                    tp = price - (min_accepted_dist * 2.0)
                    modified_stops = True
                
                # 2. Vérifier la distance min
                elif (price - tp) < min_accepted_dist:
                    logger.warning(f"⚠️ TP SELL trop proche -> Ajustement")
                    tp = price - min_accepted_dist
                    modified_stops = True
        
        if modified_stops:
            # Ré-arrondir les stops selon la précision du symbole
            digits = symbol_info.digits
            if sl > 0: sl = round(sl, digits)
            if tp > 0: tp = round(tp, digits)
            logger.info(f"🔧 Stops corrigés: SL={sl}, TP={tp} (Price: {price})")

        # Warning spread extrême
        max_spread_check = symbol_info.point * 100
        if current_spread > max_spread_check:
            logger.warning(f"⚠️ Spread critique sur {symbol}: {current_spread/symbol_info.point:.1f} points")
        
        # Arrondir le volume selon les spécifications du symbole
        volume = max(symbol_info.volume_min, min(volume, symbol_info.volume_max))
        # Arrondi correct selon le step
        if symbol_info.volume_step > 0:
            steps = round(volume / symbol_info.volume_step)
            volume = steps * symbol_info.volume_step
        
        # Formater pour respecter les décimales requises (souvent 2)
        volume_decimals = 2 
        if symbol_info.volume_step < 0.1: volume_decimals = 2
        if symbol_info.volume_step < 0.01: volume_decimals = 3 # Rare
        
        volume = round(volume, volume_decimals)
        
        logger.info(f"Sending order: {order_type} {volume} {symbol} @ {price} | SL: {sl} | TP: {tp}")
        
        
        # Essayer avec différents modes de remplissage et RETRY LOGIC
        filling_modes = [
            mt5.ORDER_FILLING_FOK,    # Fill or Kill = 0
            mt5.ORDER_FILLING_IOC,    # Immediate or Cancel = 1  
            mt5.ORDER_FILLING_RETURN, # Return remaining = 2
        ]
        
        # Liste des erreurs temporaires qui méritent un retry
        RETRYABLE_ERRORS = [
            mt5.TRADE_RETCODE_REQUOTE,
            mt5.TRADE_RETCODE_CONNECTION,
            mt5.TRADE_RETCODE_TIMEOUT,
            mt5.TRADE_RETCODE_PRICE_OFF,
            mt5.TRADE_RETCODE_PRICE_CHANGED
        ]
        
        max_retries = 3
        
        for attempt in range(max_retries):
            # Rafraîchir le prix avant chaque tentative (sauf la première)
            if attempt > 0:
                import time
                time.sleep(0.5) # Petit délai de 500ms
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    if order_type.upper() == "BUY":
                        price = tick.ask
                    else:
                        price = tick.bid
                    logger.debug(f"🔄 Retry {attempt+1}/{max_retries}: Price updated to {price}")

            # Essayer chaque filling mode
            for filling_mode in filling_modes:
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": float(volume),
                    "type": mt5_type,
                    "price": price,
                    "sl": float(sl) if sl else 0.0,
                    "tp": float(tp) if tp else 0.0,
                    "deviation": 50,
                    "magic": self.magic_number,
                    "comment": comment or "SMC Bot",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": filling_mode,
                }
                
                result = mt5.order_send(request)
                
                if result is None:
                    continue
                
                # --- SUCCÈS ---
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    # 📊 SLIPPAGE CHECK
                    executed_price = result.price
                    requested_price = price
                    slippage_points = abs(executed_price - requested_price) / symbol_info.point
                    
                    if slippage_points > 20: # Warning si > 20 points (2 pips)
                        logger.warning(f"⚠️ HIGH SLIPPAGE: {slippage_points:.1f} points (Req: {requested_price} -> Exec: {executed_price})")
                    else:
                        logger.info(f"✅ Slippage: {slippage_points:.1f} points")

                    logger.info(f"✅ Order executed: Ticket #{result.order}")
                    return OrderResult(True, result.order, "Order executed", result.price)
                
                # --- ÉCHEC ---
                # Si erreur "Unsupported filling mode", on passe au filling suivant
                if "filling" in result.comment.lower() or "unsupported" in result.comment.lower():
                    logger.debug(f"Filling mode {filling_mode} rejected, trying next...")
                    continue
                
                # Si erreur temporaire, on sort de la boucle filling pour retenter avec le nouveau prix (boucle principale)
                if result.retcode in RETRYABLE_ERRORS:
                    logger.warning(f"⚠️ Transient Error: {result.comment} (RetCode: {result.retcode}). Retrying...")
                    break # Break filling loop, triggering next 'attempt' loop
                
                # Si erreur fatale (Solde insuffisant, etc.), on arrête tout
                return OrderResult(False, None, f"Order failed: {result.comment} (RetCode: {result.retcode})")
        
        return OrderResult(False, None, f"Order failed after {max_retries} retries.")
    
    def place_pending_order(self, symbol: str, order_type: str, volume: float,
                           price: float, sl: float = 0, tp: float = 0,
                           comment: str = "") -> OrderResult:
        """
        Place un ordre en attente.
        
        Args:
            order_type: "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"
        """
        type_map = {
            "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
            "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
            "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
            "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP
        }
        
        mt5_type = type_map.get(order_type.upper())
        if mt5_type is None:
            return OrderResult(False, None, f"Invalid order type: {order_type}")
        
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": float(volume),
            "type": mt5_type,
            "price": float(price),
            "sl": float(sl) if sl else 0.0,
            "tp": float(tp) if tp else 0.0,
            "deviation": 20,
            "magic": self.magic_number,
            "comment": comment or "SMC Bot Pending",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        
        result = mt5.order_send(request)
        
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            msg = result.comment if result else str(mt5.last_error())
            return OrderResult(False, None, f"Pending order failed: {msg}")
        
        logger.info(f"Pending order placed: Ticket #{result.order}")
        return OrderResult(True, result.order, "Pending order placed", price)
    
    def modify_position(self, ticket: int, sl: float = None, tp: float = None) -> OrderResult:
        """Modifie le SL/TP d'une position."""
        position = mt5.positions_get(ticket=ticket)
        if not position:
            return OrderResult(False, None, f"Position {ticket} not found")
        
        pos = position[0]
        
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": pos.symbol,
            "sl": float(sl) if sl is not None else pos.sl,
            "tp": float(tp) if tp is not None else pos.tp,
        }
        
        result = mt5.order_send(request)
        
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            msg = result.comment if result else str(mt5.last_error())
            return OrderResult(False, None, f"Modify failed: {msg}")
        
        logger.info(f"Position {ticket} modified - SL: {sl}, TP: {tp}")
        return OrderResult(True, ticket, "Position modified")
    
    def close_position(self, ticket: int) -> OrderResult:
        """Ferme une position par son ticket."""
        position = mt5.positions_get(ticket=ticket)
        if not position:
            return OrderResult(False, None, f"Position {ticket} not found")
        
        pos = position[0]
        
        # Déterminer le type d'ordre inverse
        if pos.type == mt5.ORDER_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = mt5.symbol_info_tick(pos.symbol).bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(pos.symbol).ask
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": self.magic_number,
            "comment": "Close by SMC Bot",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            msg = result.comment if result else str(mt5.last_error())
            return OrderResult(False, None, f"Close failed: {msg}")
        
        logger.info(f"Position {ticket} closed")
        return OrderResult(True, ticket, "Position closed", result.price)
    
    def partial_close(self, ticket: int, close_percent: float = 50) -> OrderResult:
        """
        Ferme partiellement une position (prises de profits partielles).
        
        Args:
            ticket: Ticket de la position
            close_percent: Pourcentage à fermer (par défaut 50%)
        """
        position = mt5.positions_get(ticket=ticket)
        if not position:
            return OrderResult(False, None, f"Position {ticket} not found")
        
        pos = position[0]
        
        # Calculer le volume à fermer
        volume_to_close = pos.volume * (close_percent / 100)
        
        # Récupérer les infos du symbole pour le volume step
        symbol_info = mt5.symbol_info(pos.symbol)
        if symbol_info:
            # Arrondir au volume step
            volume_to_close = round(volume_to_close / symbol_info.volume_step) * symbol_info.volume_step
            volume_to_close = max(symbol_info.volume_min, volume_to_close)
            volume_to_close = min(volume_to_close, pos.volume)  # Ne pas fermer plus que disponible
        
        volume_to_close = round(volume_to_close, 2)
        
        if volume_to_close <= 0:
            return OrderResult(False, None, "Volume to close too small")
        
        # Déterminer le type d'ordre inverse
        if pos.type == mt5.ORDER_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = mt5.symbol_info_tick(pos.symbol).bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(pos.symbol).ask
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": pos.symbol,
            "volume": volume_to_close,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": self.magic_number,
            "comment": f"Partial {close_percent}% SMC Bot",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            msg = result.comment if result else str(mt5.last_error())
            return OrderResult(False, None, f"Partial close failed: {msg}")
        
        remaining = pos.volume - volume_to_close
        logger.info(f"✅ Partial close {ticket}: closed {volume_to_close} lots ({close_percent}%), remaining: {remaining} lots")
        return OrderResult(True, ticket, f"Partial close: {volume_to_close} lots closed", result.price)

    
    def close_all_positions(self, symbol: str = None) -> int:
        """Ferme toutes les positions (optionnellement filtrées par symbole)."""
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()
        
        if not positions:
            return 0
        
        closed = 0
        for pos in positions:
            if pos.magic == self.magic_number or self.magic_number == 0:
                result = self.close_position(pos.ticket)
                if result.success:
                    closed += 1
        
        logger.info(f"Closed {closed} positions")
        return closed
    
    def delete_pending_order(self, ticket: int) -> OrderResult:
        """Supprime un ordre en attente."""
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": ticket,
        }
        
        result = mt5.order_send(request)
        
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            msg = result.comment if result else str(mt5.last_error())
            return OrderResult(False, None, f"Delete failed: {msg}")
        
        logger.info(f"Pending order {ticket} deleted")
        return OrderResult(True, ticket, "Order deleted")
