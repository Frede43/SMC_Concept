"""
Ultimate SMC Trading Bot - Main Entry Point
Smart Money Concepts Trading Robot

Usage:
    python main.py --mode live      # Trading en temps réel
    python main.py --mode demo      # Mode démo (paper trading)
    python main.py --mode backtest  # Backtesting
    python main.py --mode visual    # Visualisation uniquement
"""

import argparse
import time
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime

# ✅ FIX CRASH EMOJI WINDOWS: Forcer l'encodage UTF-8 pour la console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Ajouter le dossier racine au path
sys.path.insert(0, str(Path(__file__).parent))

from typing import List, Dict, Any
from loguru import logger
from utils.helpers import load_config, print_banner
from utils.logger import setup_logger
from broker.mt5_connector import MT5Connector
from broker.order_manager import OrderManager
from strategy.usdjpy_strategy import UsdJpySMCStrategy, UsdJpySignalType
from strategy.smc_strategy import SMCStrategy, SignalType, TradeSignal
from strategy.filters import TradingFilters
from strategy.risk_management import RiskManager
from strategy.trade_monitor import TradeMonitor
from strategy.news_filter import NewsFilter
from strategy.weekend_filter import WeekendFilter
from utils.live_safety_guard import LiveSafetyGuard, SecurityViolation
from utils.discord_notifier import DiscordNotifier
from utils.trade_journal import TradeJournal
from utils.session_tracker import get_session_tracker, SessionPerformanceTracker
from utils.correlation_guard import get_correlation_guard, CorrelationGuard
from utils.smart_coach import SmartCoach # 🎓 Module Pédagogique
from utils.telegram_notifier import TelegramNotifier # ✈️ Module Telegram

# Dashboard optionnel (nécessite Flask)
try:
    from utils.dashboard import get_dashboard, start_dashboard
    DASHBOARD_AVAILABLE = True
except ImportError:
    DASHBOARD_AVAILABLE = False


class SMCTradingBot:
    """
    Robot de trading Ultimate SMC.
    
    Combine tous les concepts Smart Money pour trader automatiquement.
    """
     
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config = load_config(config_path)
        self.running = False
        
        # Setup logger
        log_level = self.config.get('general', {}).get('log_level', 'INFO')
        setup_logger(log_level)
        
        # Initialiser les composants
        self.mt5 = MT5Connector(self.config)
        self.discord = DiscordNotifier()  # Initialisation Discord
        self.telegram = TelegramNotifier() # Initialisation Telegram
        self.journal = TradeJournal()      # Initialisation Journal CSV
        
        self.order_manager = OrderManager()
        self.strategy = SMCStrategy(self.config, discord_notifier=self.discord, mt5_api=self.mt5)
        self.filters = TradingFilters(self.config)
        self.risk_manager = RiskManager(self.config)
        magic = self.config.get('mt5', {}).get('magic_number', 123456)
        self.trade_monitor = TradeMonitor(self.config, magic_number=magic)
        self.news_filter = NewsFilter(self.config)
        
        # 🆕 NOUVEAUX MODULES D'AMÉLIORATION
        timezone_offset = self.config.get('weekend_filter', {}).get('timezone_offset', 2)
        self.session_tracker = get_session_tracker(timezone_offset=timezone_offset)
        self.correlation_guard = get_correlation_guard(config=self.config)
        
        # Dashboard web (optionnel)
        self.dashboard = None
        if DASHBOARD_AVAILABLE:
            dashboard_config = self.config.get('dashboard', {})
            if dashboard_config.get('enabled', True):
                try:
                    self.dashboard = get_dashboard(port=dashboard_config.get('port', 5000))
                except Exception as e:
                    logger.warning(f"⚠️ Dashboard non disponible: {e}")
        self.weekend_filter = WeekendFilter(self.config)
        
        # Configuration des symboles (sera mise à jour selon le broker actif)
        self.all_symbols = {
            s['name']: s for s in self.config.get('symbols', [])
            if s.get('enabled', True)
        }
        self.symbols = list(self.all_symbols.keys())  # Sera filtré après connexion
        
        # Anti-doublon: Cooldown PERSISTANT
        self.last_trades_file = "last_trades.json"
        self.last_trade_times = self._load_last_trades()
        
        self.timeframes = self.config.get('timeframes', {})
        self.ltf = self.timeframes.get('ltf', 'M15')
        self.mtf = self.timeframes.get('mtf', 'H4')   # ✅ AJOUT MTF pour analyse structure
        self.htf = self.timeframes.get('htf', 'D1')
        
        # Anti-doublon pour les logs de fermeture
        self.processed_closed_tickets = set()
        
    def _load_last_trades(self) -> dict:
        """Charge les timestamps des derniers trades depuis le disque."""
        import json
        import os
        try:
            if os.path.exists(self.last_trades_file):
                with open(self.last_trades_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Erreur chargement last_trades.json: {e}")
        return {}

    def _save_last_trades(self):
        """Sauvegarde les timestamps des derniers trades."""
        import json
        try:
            with open(self.last_trades_file, 'w') as f:
                json.dump(self.last_trade_times, f)
        except Exception as e:
            logger.error(f"Erreur sauvegarde last_trades.json: {e}")
        
    def _check_duplicate_position(self, symbol: str, direction: str, current_price: float, tolerance_pips: float = 5.0) -> bool:
        """
        Vérifie s'il existe déjà une position similaire (même symbole, même direction, prix proche).
        Protection ultime contre les doublons.
        """
        try:
            import MetaTrader5 as mt5
            positions = mt5.positions_get(symbol=symbol)
            if not positions:
                return False
                
            pip_value = 0.01 if "JPY" in symbol or "XAU" in symbol else 0.0001
            tolerance = tolerance_pips * pip_value
            
            target_type = 0 if direction == "BUY" else 1 # 0=BUY, 1=SELL
            
            for pos in positions:
                if pos.type == target_type:
                    # Vérifier si le prix d'ouverture est proche
                    dist = abs(pos.price_open - current_price)
                    if dist < tolerance:
                        logger.warning(f"🚫 Doublon détecté sur MT5: Ticket #{pos.ticket} @ {pos.price_open} (Dist: {dist/pip_value:.1f} pips)")
                        return True
            return False
        except Exception as e:
            logger.error(f"Erreur vérification doublons MT5: {e}")
            return False

    def _update_symbols_for_broker(self):
        """Met à jour la liste des symboles selon le broker actif."""
        broker_symbols = self.mt5.get_active_symbols()
        if broker_symbols:
            # Utiliser uniquement les symboles du broker actif
            self.symbols = [s for s in broker_symbols if s in self.all_symbols]
            logger.info(f"📊 Symboles actifs pour {self.mt5.current_broker}: {', '.join(self.symbols)}")
        else:
            # Fallback: tous les symboles activés
            self.symbols = list(self.all_symbols.keys())
        
    def start(self, mode: str = None):
        """Démarre le bot."""
        print_banner()
        
        # Résoudre le mode: CLI > Config > Default(demo)
        if mode is None:
            mode = self.config.get('general', {}).get('mode', 'demo')
            
        self.execution_mode = mode # Store resolved execution mode
        
        import os
        logger.info(f"Starting Ultimate SMC Bot in {mode.upper()} mode (PID: {os.getpid()})")
        logger.info(f"Timeframes: LTF={self.ltf}, HTF={self.htf}")
        
        # Connecter à MT5 (choisit automatiquement le broker selon le jour)
        if not self.mt5.connect():
            logger.error("Failed to connect to MT5. Exiting.")
            return
            
        # 🔐 SÉCURITÉ LIVE: Vérifier l'environnement avant toute chose
        try:
            # Fix encodage console Windows pour éviter crash sur émojis
            if sys.platform == 'win32':
                sys.stdout.reconfigure(encoding='utf-8')
                
            safety_guard = LiveSafetyGuard(self.mt5, self.config)
            # On passe le mode CLI pour que le garde sache si on est en DEMO ou LIVE
            is_safe = safety_guard.validate_environment(mode_override=mode)
            
            if not is_safe:
                logger.critical("🛑 ÉCHEC VALIDATION SÉCURITÉ. DÉSACTIVEZ LE MODE LIVE OU CORRIGEZ LA CONFIGURATION.")
                return
        except SecurityViolation as e:
            logger.critical(f"🛑 VIOLATION DE SÉCURITÉ: {e}")
            logger.critical("ARRÊT IMMÉDIAT DU BOT.")
            return
        except Exception as e:
            logger.critical(f"🛑 ERREUR CRITIQUE SÉCURITÉ: {e}")
            return
        
        # Mettre à jour les symboles selon le broker connecté
        self._update_symbols_for_broker()
        logger.info(f"Symbols: {', '.join(self.symbols)}")
        
        # Afficher les infos du compte
        account = self.mt5.get_account_info()
        if account:
            logger.info(f"Account: {account['login']}")
            logger.info(f"Balance: ${account['balance']:.2f}")
            logger.info(f"Leverage: 1:{account['leverage']}")
            
            # 📢 NOTIFICATION DISCORD & TELEGRAM STARTUP
            self.discord.notify_startup(mode, account['login'], account['balance'])
            self.telegram.send_message(f"🚀 **SMC Bot Démarré**\nMode: {mode.upper()}\nBalance: ${account['balance']:.2f}")
        
        
        # 🌐 DÉMARRAGE DU DASHBOARD WEB
        if self.dashboard and DASHBOARD_AVAILABLE:
            try:
                self.dashboard.start(threaded=True)
                logger.info(f"🌐 Dashboard web démarré sur http://localhost:5000")
            except Exception as e:
                logger.warning(f"⚠️ Échec démarrage dashboard: {e}")
        
        # 🔔 NOUVEAU: Démarrage des alertes proactives news
        try:
            from utils.proactive_news_alerts import ProactiveNewsAlerts
            self.proactive_alerts = ProactiveNewsAlerts(
                news_filter=self.news_filter,
                discord_notifier=self.discord,
                telegram_notifier=self.telegram,
                config=self.config
            )
            self.proactive_alerts.start()
            logger.info("🔔 Alertes proactives news: ACTIVÉES (notification 4h avant)")
        except Exception as e:
            logger.warning(f"⚠️ Alertes proactives non disponibles: {e}")
            self.proactive_alerts = None
        
        # DIAGNOSTIC: Afficher les données dynamiques MT5 pour chaque symbole
        logger.info("=" * 60)
        logger.info("=" * 60)
        logger.info("📊 DIAGNOSTIC MT5 - Données Dynamiques des Symboles")
        logger.info("=" * 60)
        for symbol in self.symbols:
            # S'assurer que le symbole est visible
            self.mt5.ensure_symbol_visible(symbol)
            info = self.mt5.get_symbol_info(symbol)
            if info:
                logger.info(f"📌 {symbol}:")
                logger.info(f"   Prix: Bid={info['bid']:.5f}, Ask={info['ask']:.5f}")
                logger.info(f"   Digits: {info['digits']}, Point: {info['point']}")
                logger.info(f"   Pip Size: {info['pip_size']}, Pip Value/Lot: ${info['pip_value_per_lot']:.4f}")
                logger.info(f"   Contract: {info['contract_size']}, Tick Value: ${info['tick_value']:.4f}")
                logger.info(f"   Volume: min={info['volume_min']}, max={info['volume_max']}, step={info['volume_step']}")
                logger.info(f"   Stops Level: {info['stops_level']} points")
            else:
                logger.warning(f"❌ Impossible de récupérer les infos pour {symbol}")
        logger.info("=" * 60)
        
        self.running = True
        
        try:
            if mode == "live" or mode == "demo":
                self._run_live_trading()
            elif mode == "visual":
                self._run_visualization()
            elif mode == "backtest":
                self._run_backtest()
            else:
                logger.error(f"Unknown mode: {mode}")
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.exception(f"Bot error: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """Arrête le bot."""
        self.running = False
        self.mt5.disconnect()
        logger.info("Bot stopped")
    
    def _run_live_trading(self):
        """Boucle principale de trading."""
        logger.info("Starting live trading loop...")
        
        while self.running:
            try:
                # 🚨 KILL SWITCH AUTOMATIQUE - PRIORITÉ ABSOLUE
                # Vérifier les limites de risque AVANT toute autre action
                stats = self.risk_manager.get_stats()
                
                # 1. Vérifier daily loss limit
                max_daily_loss = self.config.get('risk', {}).get('max_daily_loss', 2.0)
                if stats.daily_profit < 0:
                    daily_loss_percent = abs(stats.daily_profit)
                    if daily_loss_percent >= max_daily_loss:
                        msg = f"🚨 KILL SWITCH ACTIVÉ - DAILY LOSS LIMIT ATTEINT ({daily_loss_percent:.2f}% / {max_daily_loss}%)"
                        logger.critical("=" * 80)
                        logger.critical(msg)
                        logger.critical("Le bot s'arrête automatiquement pour protéger le capital.")
                        logger.critical("=" * 80)
                        self.discord.notify_error(msg)
                        self.running = False
                        break
                
                # 2. Vérifier consecutive losses
                if hasattr(self.risk_manager, 'consecutive_losses'):
                    # consecutive_losses est un dict {symbol: count}
                    # Vérifier si UN symbole a atteint la limite
                    for symbol, losses in self.risk_manager.consecutive_losses.items():
                        if losses >= 3:
                            msg = f"🚨 KILL SWITCH ACTIVÉ - 3 PERTES CONSÉCUTIVES SUR {symbol}"
                            logger.critical("=" * 80)
                            logger.critical(msg)
                            logger.critical("Protection drawdown activée.")
                            logger.critical("=" * 80)
                            self.discord.notify_error(msg)
                            self.running = False
                            break
                    
                    if not self.running:
                        break # Sortir de la boucle while
                
                # 0. Vérifier le filtre week-end FIRST
                can_trade, reason = self.weekend_filter.can_trade()
                
                # Séparer les symboles crypto (24/7) des symboles forex
                crypto_symbols = [s for s in self.symbols if self._is_crypto(s)]
                forex_symbols = [s for s in self.symbols if not self._is_crypto(s)]
                
                if not can_trade:
                    logger.info(f"{reason}")
                    
                    # Pendant le week-end, trader uniquement les cryptos si disponibles
                    if crypto_symbols:
                        logger.info(f"🪙 Trading crypto uniquement: {', '.join(crypto_symbols)}")
                        
                        # Monitoring positions
                        self._monitor_open_trades()
                        
                        # Traiter uniquement les cryptos
                        for symbol in crypto_symbols:
                            self._process_symbol(symbol)
                        
                        time.sleep(60)  # Check toutes les minutes
                        continue
                    else:
                        next_session = self.weekend_filter.get_next_trading_time()
                        logger.info(f"📅 Prochaine session: {next_session}")
                        
                        # Vérifier si on doit fermer les positions forex (vendredi soir)
                        should_close, close_reason = self.weekend_filter.should_close_positions()
                        if should_close:
                            logger.warning(close_reason)
                            self._close_all_positions_for_weekend()
                        
                        # Attendre plus longtemps pendant le week-end
                        time.sleep(300)  # 5 minutes
                        continue
                
                # 1. Monitoring des positions ouvertes (trailing, break-even)
                self._monitor_open_trades()
                
                # 2. Traiter chaque symbole
                for symbol in self.symbols:
                    self._process_symbol(symbol)
                
                # 3. Nettoyer les positions fermées et gérer le risque
                closed_tickets = self.trade_monitor.cleanup_closed_positions()
                if closed_tickets:
                    self._handle_closed_trades(closed_tickets)
                
                # Attendre avant le prochain cycle
                time.sleep(1)  # Check toutes les secondes (plus réactif)
                
            except Exception as e:
                # ✅ FIX: Meilleur logging avec traceback pour diagnostic
                import traceback
                error_details = traceback.format_exc()
                logger.error(f"Error in trading loop: {e}")
                logger.debug(f"Full traceback:\n{error_details}")
                time.sleep(10)
    
    def _is_crypto(self, symbol: str) -> bool:
        """Vérifie si un symbole est une crypto (trade 24/7)."""
        # Chercher dans la config du symbole
        for s in self.config.get('symbols', []):
            if s.get('name') == symbol:
                return s.get('is_crypto', False) or s.get('trade_weekend', False)
        
        # Fallback: détecter par le nom
        crypto_keywords = ['BTC', 'ETH', 'XRP', 'CRYPTO', 'LTC', 'DOGE', 'SOL']
        return any(kw in symbol.upper() for kw in crypto_keywords)
    
    def _close_all_positions_for_weekend(self):
        """Ferme toutes les positions avant le week-end."""
        positions = self.mt5.get_positions()
        if not positions:
            logger.info("Aucune position à fermer pour le week-end")
            return
        
        logger.warning(f"🔒 Fermeture de {len(positions)} position(s) avant le week-end...")
        
        for pos in positions:
            ticket = pos.get('ticket')
            symbol = pos.get('symbol')
            profit = pos.get('profit', 0)
            
            # 🛡️ PROTECTION CRYPTO: Ne pas fermer les cryptos le week-end
            if self._is_crypto(symbol):
                logger.info(f"🪙 Crypto préservée: {symbol} #{ticket} restera ouverte.")
                continue
            
            result = self.order_manager.close_position(ticket)
            if result.success:
                logger.info(f"✅ Position Forex {symbol} #{ticket} fermée (P&L: ${profit:.2f})")
            else:
                logger.error(f"❌ Échec fermeture {symbol} #{ticket}: {result.message}")
    
    def _handle_closed_trades(self, tickets: List[int]):
        """Gère les aspects risk management des trades fermés."""
        for ticket in tickets:
            # Éviter de traiter plusieurs fois le même ticket
            if ticket in self.processed_closed_tickets:
                continue
                
            try:
                # Récupérer l'historique pour ce ticket
                history = self.mt5.get_trade_history(ticket=ticket)
                
                # ✅ FIX: Vérification robuste pour éviter "DataFrame truth value is ambiguous"
                if history is None:
                    continue
                if hasattr(history, 'empty') and history.empty:
                    continue
                if len(history) == 0:
                    continue
                    
                # Chercher le deal de sortie (entry=1 = OUT)
                deals = history[history['entry'] == 1]
                
                if deals is None or (hasattr(deals, 'empty') and deals.empty) or len(deals) == 0:
                    continue
                    
                deal = deals.iloc[-1]
                symbol = deal['symbol']
                profit = deal['profit']
                
                # Estimer le % de PnL
                account_info = self.mt5.get_account_info()
                balance = account_info['balance'] if account_info else 10000
                pnl_percent = (profit / balance) * 100 if balance > 0 else 0
                
                # Notifier le risk manager
                self.risk_manager.on_trade_closed(pnl_percent, symbol)
                
                status = "PERTE 🛑" if profit < 0 else "GAIN ✅"
                
                # Calculer la durée
                duration = "Inconnue"
                entry_deals = history[history['entry'] == 0]
                if not entry_deals.empty:
                    try:
                        entry_time = entry_deals.iloc[0]['time']
                        exit_time = deal['time']
                        diff = exit_time - entry_time
                        hours, remainder = divmod(diff, 3600)
                        minutes, _ = divmod(remainder, 60)
                        duration = f"{int(hours)}h {int(minutes)}m"
                    except: pass
                
                # 📢 NOTIFICATION DISCORD, TELEGRAM & JOURNAL
                self.discord.notify_trade_close(
                    symbol, "POSITION", profit, pnl_percent, deal['price'], duration
                )
                self.telegram.notify_trade_close(symbol, profit, pnl_percent, deal['price'])
                self.journal.log_exit(ticket, deal['price'], profit, pnl_percent)
                
                # 📊 ENREGISTREMENT SESSION TRACKER
                try:
                    entry_time_dt = None
                    exit_time_dt = None
                    strategy = "unknown"
                    
                    if not entry_deals.empty:
                        entry_time_dt = datetime.fromtimestamp(entry_deals.iloc[0]['time'])
                        exit_time_dt = datetime.fromtimestamp(deal['time'])
                    
                    # Récupérer la stratégie depuis le commentaire si disponible
                    comment = str(deal.get('comment', ''))
                    if 'SB' in comment or 'Silver' in comment:
                        strategy = 'silver_bullet'
                    elif 'PDL' in comment:
                        strategy = 'pdl_sweep'
                    elif 'Asian' in comment:
                        strategy = 'asian_sweep'
                    elif 'SMT' in comment:
                        strategy = 'smt'
                    
                    self.session_tracker.record_trade({
                        'ticket': ticket,
                        'symbol': symbol,
                        'direction': 'BUY' if deal.get('type', 0) == 0 else 'SELL',
                        'entry_time': entry_time_dt,
                        'exit_time': exit_time_dt,
                        'profit': profit,
                        'strategy': strategy
                    })
                except Exception as e:
                    logger.debug(f"Erreur session tracker: {e}")
                
                # 🌐 MISE À JOUR DASHBOARD
                if self.dashboard:
                    status_emoji = "🟢" if profit > 0 else "🔴"
                    self.dashboard.add_alert(f"{status_emoji} {symbol} fermé: ${profit:.2f}")
                
                logger.info(f"📊 Trade Fermé: {symbol} #{ticket} | {status} | Profit: ${profit:.2f} ({pnl_percent:.2f}%)")
                
                # Marquer comme traité
                self.processed_closed_tickets.add(ticket)
                
            except Exception as e:
                logger.error(f"❌ Erreur traitement trade fermé #{ticket}: {e}")
    
    def _monitor_open_trades(self):
        """Surveille et gère les positions ouvertes."""
        # 1. Gestion classique (Trailing, BE)
        actions = self.trade_monitor.check_and_manage_positions()
        
        for action in actions:
            if action['action'] == 'break_even':
                logger.info(f"🔒 Break-even appliqué: {action['symbol']} #{action['ticket']}")
            elif action['action'] == 'trailing_stop':
                logger.info(f"Trailing stop: {action['symbol']} #{action['ticket']} to SL @ {action['new_sl']:.5f}")

        # 2. STRATÉGIE 2: Emergency News Exit
        news_cfg = self.config.get('filters', {}).get('news', {})
        if news_cfg.get('emergency_exit', False):
            exit_horizon = news_cfg.get('exit_minutes_before', 5)
            
            positions = self.mt5.get_positions()
            for pos in positions:
                symbol = pos.get('symbol')
                should_exit, reason = self.news_filter.check_emergency_exit(symbol, exit_horizon)
                
                if should_exit:
                    ticket = pos.get('ticket')
                    logger.critical(f"⚠️ {reason} - FERMETURE D'URGENCE DU TICKET #{ticket}")
                    
                    result = self.order_manager.close_position(ticket)
                    if result.success:
                        self.discord.notify_error(f"⚠️ News Emergency Exit: {symbol} #{ticket} fermé avant impact.")
                        self.telegram.notify_error(f"⚠️ News Emergency Exit: {symbol} #{ticket} fermé avant impact.")
                    else:
                        logger.error(f"❌ Échec fermeture d'urgence #{ticket}: {result.message}")
            
        # 3. Expert Reassurance (Conseil Pro)
        positions = self.mt5.get_positions()
        if positions:
            for pos in positions:
                symbol = pos.get('symbol')
                profit = pos.get('profit', 0)
                if profit < 0:
                    # On ne logue qu'une fois de temps en temps pour ne pas polluer (toutes les 15 min)
                    if datetime.now().minute % 15 == 0 and datetime.now().second < 20: 
                        logger.info(f"🛡️ [PRO] Position {symbol} en drawdown (${profit:.2f}). "
                                   f"Note: Le setup institutionnel est validé. Discipline et patience sont les clés du succès.")
    
    def _process_symbol(self, symbol: str):
        """Traite un symbole."""
        try:
            logger.debug(f"Analyse de {symbol}...")
            
            # =========================================================================
            # 🌑 MANUAL BLACKOUT CALENDAR (INSTITUTIONAL RISK MANAGEMENT)
            # Protection contre les événements majeurs (BoJ, FOMC, NFP)
            # =========================================================================
            current_dt = datetime.now()
            
            # 🚨 23 Jan 2026 : BoJ Interest Rate Decision (Risque Extrême sur JPY)
            if "JPY" in symbol and current_dt.year == 2026 and current_dt.month == 1 and current_dt.day == 23:
                # Bloquer de 00:00 à 14:00 (Toute la session Asie + Londres)
                if 0 <= current_dt.hour < 14:
                    logger.warning(f"⛔ [RISK CALENDAR] {symbol} SUSPENDU (BoJ Interest Rate Decision). Protection Capital.")
                    return
            
            # =========================================================================
            # 🆕 Anti-doublon AMÉLIORÉ: Cooldown configurable entre trades sur même symbole
            import time
            
            # 🆕 Anti-doublon AMÉLIORÉ 2.0: Vérification active des positions ouvertes
            positions = self.mt5.get_positions(symbol=symbol)
            if positions and len(positions) > 0:
                # Si on a déjà une position ouverte il y a moins de 2 minutes
                # Ou si on a une position très proche du prix actuel (pour éviter le stacking accidentel)
                price_data = self.mt5.get_current_price(symbol)
                current_price_val = price_data['bid'] if price_data else 0.0

                for pos in positions:
                    # Vérifier si c'est un trade récent
                    stack_time = self.config.get('risk', {}).get('min_stacking_time_seconds', 300)
                    # Convertir datetime en timestamp si nécessaire
                    pos_time = pos.get('time', 0)
                    if hasattr(pos_time, 'timestamp'):
                        pos_time = pos_time.timestamp()
                        
                    trade_age = time.time() - pos_time
                    if trade_age < stack_time:
                        logger.warning(f"⚠️ Anti-doublon: Trade récent détecté ({int(trade_age)}s < {stack_time}s). Skip.")
                        return

                    # Vérifier si le prix est trop proche (Stacking involontaire)
                    # Si une position existe à moins de X pips, on évite d'en rouvrir une identique
                    if current_price_val > 0:
                        # Obtenir la taille de pip dynamique
                        sym_info = self.mt5.get_symbol_info(symbol)
                        pip_size = sym_info['pip_size'] if sym_info else 0.0001
                        
                        dist_pips = abs(pos['price_open'] - current_price_val) / pip_size
                        
                        stack_dist = self.config.get('risk', {}).get('min_stacking_distance_pips', 15.0)
                        
                        if dist_pips < stack_dist:
                             logger.debug(f"⚠️ Anti-doublon: Position existante trop proche ({dist_pips:.1f} < {stack_dist} pips). Skip.")
                             return

            # Recharger les derniers trades depuis le disque pour synchroniser les processus/instances
            self.last_trade_times = self._load_last_trades()
            
            cooldown_seconds = self.config.get('risk', {}).get('cooldown_same_symbol_seconds', 60) # Augmenté à 60s par défaut
            last_trade = self.last_trade_times.get(symbol, 0)
            elapsed = time.time() - last_trade
            
            if elapsed < cooldown_seconds:
                remaining = int(cooldown_seconds - elapsed)
                logger.info(f"   ⏳ Anti-doublon: Cooldown actif ({remaining}s restantes sur {cooldown_seconds}s)...")
                return
            
            # Vérifier le filtre news en premier
            news_allowed, news_reason = self.news_filter.is_trading_allowed(symbol)
            if not news_allowed:
                logger.info(f"   {news_reason}")
                return
            
            # 🆕 Filtre Lunch Break: Évite les trades pendant faible liquidité (12-13h GMT)
            lunch_config = self.config.get('risk', {}).get('lunch_break_filter', {})
            if lunch_config.get('enabled', False) and lunch_config.get('block_new_trades', True):
                from datetime import datetime
                current_hour = datetime.now().hour
                # Convertir en GMT (approximation: heure locale - 2 pour l'Afrique du Sud)
                timezone_offset = 2  # Ajuster selon votre fuseau horaire
                gmt_hour = (current_hour - timezone_offset) % 24
                
                start_hour = lunch_config.get('start_hour_gmt', 12)
                end_hour = lunch_config.get('end_hour_gmt', 13)
                
                if start_hour <= gmt_hour < end_hour:
                    logger.debug(f"   🍽️ Lunch Break Filter: {gmt_hour}h GMT (pause {start_hour}h-{end_hour}h GMT) - Pas de nouvelles entrées")
                    return
        
            # Récupérer les données
            df_ltf = self.mt5.get_ohlc(symbol, self.ltf, 500)
            df_mtf = self.mt5.get_ohlc(symbol, self.mtf, 200)  # ✅ AJOUT MTF (H4)
            df_htf = self.mt5.get_ohlc(symbol, self.htf, 200)
            
            # --- NOUVEAU: Récupérer données SMT ---
            df_smt = None
            smt_config = self.config.get('smc', {}).get('smt', {})
            if smt_config.get('enabled'):
                pair_config = smt_config.get('pairs', {}).get(symbol)
                if pair_config:
                    corr_symbol = pair_config.get('corr_symbol')
                    if corr_symbol:
                        # S'assurer que le symbole est visible/disponible
                        if self.mt5.ensure_symbol_visible(corr_symbol):
                            logger.debug(f"   Fetching SMT correlation data: {corr_symbol}")
                            df_smt = self.mt5.get_ohlc(corr_symbol, self.ltf, 100)
                            # ✅ FIX: Vérification explicite pour éviter "DataFrame truth value is ambiguous"
                            if df_smt is None or (hasattr(df_smt, 'empty') and df_smt.empty):
                                df_smt = None
                                logger.debug(f"   SMT data empty for {corr_symbol}")
                        else:
                            logger.warning(f"   SMT symbol {corr_symbol} not available on this broker")
            
            if df_ltf is None or df_ltf.empty or df_htf is None or df_htf.empty or df_mtf is None or df_mtf.empty:
                logger.warning(f"Impossible de récupérer les données pour {symbol} (DataFrame vide ou None)")
                return
        
            # Prix actuel
            price_info = self.mt5.get_current_price(symbol)
            if price_info:
                logger.info(f"   Prix: {price_info['bid']:.5f} | Spread: {price_info['spread']:.1f}")
            
            # Vérifier les filtres
            current_spread = price_info['spread'] if price_info else 0
            
            filters_ok, filter_reasons = self.filters.check_all_filters(
                df_ltf, current_spread, symbol
            )
            
            if not filters_ok:
                logger.info(f"   Filtres: {', '.join(filter_reasons)}")
                return
            
            # Vérifier le risk manager (avec limite par symbole)
            can_trade, risk_reasons = self.risk_manager.can_open_trade(symbol)
            if not can_trade:
                logger.info(f"   Risque: {', '.join(risk_reasons)}")
                return
            
            # Analyser avec SMC (une seule fois)
            # ✅ PASSAGE DE DF_MTF (H4) A L'ANALYSE
            analysis = self.strategy.analyze(df_ltf, df_htf, mtf_df=df_mtf, symbol=symbol, df_smt=df_smt)
            
            # Afficher le résumé de l'analyse
            trend = analysis.get('trend')
            trend_bias = analysis.get('trend_bias', 'N/A')  # Biais basé uniquement sur tendance
            combined_bias = analysis.get('bias')  # Biais combiné (tendance + zone)
            pd_zone = analysis.get('pd_zone')
            
            # Log amélioré avec le nouveau système de biais
            trend_str = trend.value if hasattr(trend, 'value') else str(trend)
            zone_str = pd_zone.current_zone.value if pd_zone else 'N/A'
            zone_pct = f"{pd_zone.current_percentage:.1f}%" if pd_zone else 'N/A'
            
            logger.info(f"   Tendance: {trend_str} | Zone: {zone_str} ({zone_pct})")
            logger.info(f"   Biais Combiné: {combined_bias} (Trend: {trend_bias})")
            logger.info(f"   OB: {len(analysis.get('bullish_obs', []))} bull, {len(analysis.get('bearish_obs', []))} bear | Breakers: {len(analysis.get('breaker_blocks', []))}")
            
            # Générer un signal en passant l'analyse existante ET le prix réel (tick)
            # Rafraîchir le tick au dernier moment pour réduire les écarts analyse/exécution
            price_info = self.mt5.get_current_price(symbol)
            signal = self.strategy.generate_signal(
                df_ltf, df_htf, symbol, 
                analysis=analysis,
                current_tick_price=price_info  # ✅ Passe le tick réel (Bid/Ask)
            )

            # --- STRATÉGIE SPÉCIALISÉE USD/JPY ---
            if symbol == "USDJPYm":
                 try:
                    logger.info("🇯🇵 Checking Specialized USD/JPY Setup...")
                    # Créer instance
                    usdjpy_strat = UsdJpySMCStrategy(htf_df=df_htf, mtf_df=df_mtf, ltf_df=df_ltf)
                    special_signal = usdjpy_strat.analyze()
                    
                    if special_signal and special_signal.signal_type == UsdJpySignalType.STRONG_SELL:
                        logger.info(f"🔥🔥🔥 SIGNAL EXPERT USD/JPY DÉTECTÉ: {special_signal.signal_type} 🔥🔥🔥")
                        
                        # Créer un signal prioritaire
                        expert_signal = TradeSignal(
                            signal_type=SignalType.SELL,
                            entry_price=special_signal.entry_price,
                            stop_loss=special_signal.stop_loss,
                            take_profit=special_signal.take_profit_1,
                            confidence=special_signal.confidence,
                            reasons=special_signal.reasons,
                            timestamp=pd.Timestamp.now(),
                            is_secondary=False,
                            lot_multiplier=1.5 # Boost de taille pour setup expert
                        )
                        # Override le signal standard si présent
                        signal = expert_signal
                        
                 except Exception as e:
                    logger.error(f"Erreur stratégie USD/JPY: {e}")
            
            if signal is None:
                logger.info(f"   Pas de signal - Conditions non remplies")
                return
            
            if signal.signal_type == SignalType.NO_SIGNAL:
                return
            
            # Signal trouvé !
            logger.info(f"SIGNAL: {signal.signal_type.value.upper()} {symbol}")
            logger.info(f"   Entry: {signal.entry_price:.5f}")
            logger.info(f"   SL: {signal.stop_loss:.5f}")
            logger.info(f"   TP: {signal.take_profit:.5f}")
            logger.info(f"   RR: 1:{signal.risk_reward:.1f}")
            logger.info(f"   Confidence: {signal.confidence}%")
            logger.info(f"   Reasons: {', '.join(signal.reasons)}")
            
            # Calculer la taille de position avec données dynamiques MT5
            account = self.mt5.get_account_info()
            if account:
                # Afficher les infos dynamiques du symbole
                symbol_info = self.mt5.get_symbol_info(symbol)
                if symbol_info:
                    logger.info(f"   Prix MT5: Bid={symbol_info['bid']:.5f}, Ask={symbol_info['ask']:.5f}")
                    logger.info(f"   Pip: {symbol_info['pip_size']}, Pip value/lot: ${symbol_info['pip_value_per_lot']:.2f}")
                
                # Utiliser les données dynamiques pour le calcul
                position = self.risk_manager.calculate_position_size_dynamic(
                    account['balance'],
                    signal.entry_price,
                    signal.stop_loss,
                    symbol,
                    self.mt5
                )
                
                # Appliquer le multiplicateur de lot pour signaux secondaires (iFVG)
                adjusted_lot_size = position.lot_size * signal.lot_multiplier
                adjusted_lot_size = max(0.01, round(adjusted_lot_size, 2))  # Min 0.01 lot
                
                # Identifier le type de signal pour le commentaire
                signal_label = "iFVG" if signal.is_secondary else "SMC"
                
                # Exécuter l'ordre (mode demo = log seulement)
                # Utiliser le mode résolu lors du démarrage
                mode = self.execution_mode
                
                if mode == "live":
                    # --- PRE-FLIGHT CHECK DE DERNIÈRE SECONDE ---
                    # Le prix a pu bouger entre l'analyse et l'exécution
                    
                    # 1. Obtenir les prix frais et point size
                    tick = self.mt5.get_current_price(symbol)
                    current_bid = tick['bid']
                    current_ask = tick['ask']
                    entry_exec = current_ask if signal.signal_type == SignalType.BUY else current_bid
                    point = tick.get('point', 0.00001)
                    
                    # 2. VÉRIFICATION DU SLIPPAGE DYNAMIQUE
                    # On compare le prix du signal (clôture bougie) au prix d'exécution actuel
                    symbol_upper = symbol.upper()
                    pip_unit = 0.01 if any(x in symbol_upper for x in ["JPY", "XAU", "BTC", "ETH"]) else 0.0001
                    slippage_price = abs(entry_exec - signal.entry_price)
                    slippage_pips = slippage_price / pip_unit
                    
                    # Seuil de tolérance (par défaut 5 pips pour FX, 10 pour Gold, 500 pour BTC)
                    max_slippage = 5.0
                    if "XAU" in symbol_upper: max_slippage = 10.0
                    if "BTC" in symbol_upper: max_slippage = 1000.0 # ~$10 sur BTC

                    symbol_cfg = next((s for s in self.config.get('symbols', []) if s.get('name') == symbol), None)
                    if symbol_cfg:
                        risk_settings = symbol_cfg.get('risk_settings', {})
                        cfg_slip = risk_settings.get('max_slippage_pips')
                        if cfg_slip is not None:
                            max_slippage = float(cfg_slip)
                    
                    if slippage_pips > max_slippage:
                        tick_retry = self.mt5.get_current_price(symbol)
                        if tick_retry:
                            current_bid = tick_retry['bid']
                            current_ask = tick_retry['ask']
                            entry_exec = current_ask if signal.signal_type == SignalType.BUY else current_bid
                            slippage_price = abs(entry_exec - signal.entry_price)
                            slippage_pips = slippage_price / pip_unit

                        if slippage_pips > max_slippage:
                            logger.warning(f"🚫 ORDRE ANNULÉ [{symbol}]: Slippage trop élevé ({slippage_pips:.1f} pips > {max_slippage:.1f})")
                            logger.warning(f"   Prix Strat: {signal.entry_price:.5f} | Prix Marché: {entry_exec:.5f}")
                            return
                    
                    # 3. Correction des stops de secours (protection technique anti-rejet MT5)
                    adjusted_sl = signal.stop_loss
                    adjusted_tp = signal.take_profit
                    safety_pad = 20 * point # 2 pips de sécurité
                    
                    if signal.signal_type == SignalType.BUY:
                        if adjusted_sl >= entry_exec:
                            adjusted_sl = entry_exec - safety_pad
                        if adjusted_tp <= entry_exec:
                            adjusted_tp = entry_exec + (safety_pad * 5) # TP plus loin
                    else: # SELL
                        if adjusted_sl <= entry_exec:
                            adjusted_sl = entry_exec + safety_pad
                        if adjusted_tp >= entry_exec:
                            adjusted_tp = entry_exec - (safety_pad * 5)

                    if self._check_duplicate_position(symbol, signal.signal_type.value.upper(), entry_exec, tolerance_pips=5.0):
                         logger.warning(f"🚫 ORDRE ANNULÉ: Une position similaire existe déjà sur {symbol}")
                         return

                    # 🛡️ VÉRIFICATION CORRELATION GUARD
                    can_trade_corr, corr_reasons = self.correlation_guard.can_open_trade(
                        symbol, signal.signal_type.value.upper(), adjusted_lot_size,
                        confidence=signal.confidence
                    )
                    if not can_trade_corr:
                        logger.warning(f"🛡️ ORDRE BLOQUÉ par Correlation Guard:")
                        for reason in corr_reasons:
                            logger.warning(f"   {reason}")
                        if self.dashboard:
                            self.dashboard.add_alert(f"🛡️ {symbol} bloqué: {corr_reasons[0]}")
                        return

                    result = self.mt5.order_manager.open_market_order(
                        symbol=symbol,
                        order_type=signal.signal_type.value.upper(),
                        volume=adjusted_lot_size,
                        sl=adjusted_sl,
                        tp=adjusted_tp,
                        comment=f"{signal_label} {signal.confidence}%"
                    )
                    
                    if result.success:
                        self.last_trade_times[symbol] = time.time()  # ✅ Activation du cooldown anti-doublon
                        self._save_last_trades()                     # ✅ Persistance immédiate sur disque
                        self.risk_manager.on_trade_opened(symbol)
                        
                        # 📢 NOTIFICATION DISCORD, TELEGRAM & JOURNAL
                        setup_info = ", ".join(signal.reasons)
                        self.discord.notify_trade_entry(
                            symbol, signal.signal_type.value.upper(), signal.entry_price,
                            signal.stop_loss, signal.take_profit, position.risk_amount,
                            adjusted_lot_size, setup_info
                        )
                        self.telegram.notify_trade_entry(
                            symbol, signal.signal_type.value.upper(), signal.entry_price,
                            signal.stop_loss, signal.take_profit, position.risk_amount,
                            adjusted_lot_size, setup_info
                        )
                        # 🆕 Journal amélioré avec analyse complète
                        self.journal.log_entry(
                            result.ticket, symbol, signal.signal_type.value.upper(),
                            signal.entry_price, signal.stop_loss, signal.take_profit,
                            adjusted_lot_size, position.risk_amount, setup_info, signal.confidence,
                            analysis=analysis  # Passer l'analyse complète pour journalisation détaillée
                        )
                        
                        logger.info(f"✅ TRADE EXECUTED: Ticket #{result.ticket}")

                        # 🎓 SMART COACH: Explication Pédagogique
                        try:
                            # Tenter d'extraire le biais macro pour l'explication
                            macro_bias_val = analysis.get('sentiment_score', 'NEUTRAL')
                            if isinstance(macro_bias_val, float):
                                macro_bias_val = 'BULLISH' if macro_bias_val > 10 else 'BEARISH' if macro_bias_val < -10 else 'NEUTRAL'

                            coach_msg = SmartCoach.explain_trade_decision(
                                symbol=symbol,
                                signal=signal.signal_type.value.upper(),
                                reason=f"EXECUTED #{result.ticket}",
                                analysis=analysis,
                                decision_data={
                                    'score': signal.confidence, 
                                    'htf_veto': False,
                                    'macro_bias': macro_bias_val
                                }
                            )
                            self.discord.notify_smart_coach(coach_msg)
                            self.telegram.notify_smart_coach(coach_msg)
                        except Exception as ec:
                            logger.warning(f"Coach error: {ec}")

                    else:
                        logger.error(f"❌ Trade failed: {result.message}")
                else:
                    # MODE SIGNAL (DEMO / PAPER TRADING)
                    # Le bot n'exécute pas l'ordre mais envoie un SIGNAL COMPLET pour exécution manuelle
                    if signal.signal_type != SignalType.NO_SIGNAL:
                        logger.info(f"📡 SIGNAL GÉNÉRÉ (MODE MANUEL): {signal.signal_type.value.upper()} {symbol}")
                        
                        # Préparer le message détaillé
                        sig_type = signal.signal_type.value.upper()
                        emoji = "🟢" if sig_type == "BUY" else "🔴"
                        
                        # Notification Discord Détaillée
                        self.discord.send_message(
                            f"{emoji} **SIGNAL {sig_type} {symbol}** (Mode Manuel)\n"
                            f"📍 Entry: **{signal.entry_price:.5f}**\n"
                            f"🛑 SL: **{signal.stop_loss:.5f}**\n"
                            f"🎯 TP: **{signal.take_profit:.5f}**\n"
                            f"⚖️ RR: 1:{signal.risk_reward:.1f}\n"
                            f"🧠 Confiance: {signal.confidence}%\n"
                            f"📝 Raison: {', '.join(signal.reasons[:3])}"
                        )
                        
                        # Notification Telegram Détaillée
                        if hasattr(self, 'telegram') and self.telegram:
                            self.telegram.send_message(
                                f"{emoji} *SIGNAL {sig_type} {symbol}*\n"
                                f"Entry: {signal.entry_price:.5f}\n"
                                f"SL: {signal.stop_loss:.5f}\n"
                                f"TP: {signal.take_profit:.5f}\n"
                                f"RR: 1:{signal.risk_reward:.1f}"
                            )
                            
                    logger.info(f"🧪 DEMO MODE: Analysis complete for {symbol} (No trade executed)")
        
        except Exception as e:
            # ✅ FIX: Capturer les erreurs dans le traitement d'un symbole pour éviter de crasher la boucle principale
            import traceback
            logger.error(f"Erreur traitement {symbol}: {e}")
            logger.debug(f"Full traceback:\n{traceback.format_exc()}")
    
    def _run_visualization(self):
        """Mode visualisation uniquement."""
        logger.info("Running visualization mode...")
        
        for symbol in self.symbols:
            df = self.mt5.get_ohlc(symbol, self.ltf, 500)
            if df is None:
                continue
            
            # Analyser
            analysis = self.strategy.analyze(df)
            
            # Afficher le résumé
            print(f"\n{'='*50}")
            print(f"📊 Analysis for {symbol}")
            print(f"{'='*50}")
            print(f"Trend: {analysis['trend']}")
            print(f"Bias: {analysis['bias']}")
            print(f"Bullish OBs: {len(analysis['bullish_obs'])}")
            print(f"Bearish OBs: {len(analysis['bearish_obs'])}")
            print(f"FVGs: {len(analysis['fvgs'])}")
            print(f"Sweeps: {len(analysis['sweeps'])}")
            
            if analysis['pd_zone']:
                print(f"P/D Zone: {analysis['pd_zone'].current_zone.value}")
                print(f"P/D %: {analysis['pd_zone'].current_percentage:.1f}%")
            
            print(f"Current Price: {analysis['current_price']:.5f}")


    def _run_backtest(self, symbol: str = None):
        """Mode Backtest."""
        logger.info("Starting Backtest mode...")
        # Lazy import pour éviter les dépendances circulaires
        from backtest.backtester import run_backtest
        
        # Paramètres par défaut
        years = 0.16
        capital = 10000.0
        
        # Si un symbole est spécifié via CLI, on ne teste que celui-là
        if symbol:
            symbols = [symbol]
        else:
            # Sinon on prend la liste par défaut ou configurable
            symbols = self.symbols if self.symbols else ['BTCUSDm', 'EURUSDm']
        
        logger.info(f"Running backtest on {len(symbols)} symbols: {symbols} for {years} years...")
        results = run_backtest(years, symbols, capital)
        
        # 📊 Remplir le Session Tracker avec les données historiques du Backtest
        if results and 'trades' in results:
            logger.info(f"💾 Importation de {len(results['trades'])} trades historiques dans le Session Tracker...")
            count = 0
            for trade in results['trades']:
                # BacktestTrade object
                try:
                    # Déterminer la stratégie (simplifié car pas toujours stocké dans BacktestTrade)
                    strategy = "backtest" 
                    
                    self.session_tracker.record_trade({
                        'ticket': count + 1,
                        'symbol': trade.symbol,
                        'direction': trade.direction,
                        'entry_time': trade.open_time,
                        'exit_time': trade.close_time,
                        'profit': trade.pnl,
                        'strategy': strategy
                    })
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to record backtest trade: {e}")
            
            logger.info(f"✅ {count} trades importés avec succès.")


def main():
    parser = argparse.ArgumentParser(description="Ultimate SMC Trading Bot")
    parser.add_argument(
        "--mode",
        choices=["live", "demo", "backtest", "visual"],
        default=None,
        help="Trading mode (falls back to config/settings.yaml if not set)"
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="Path to config file"
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="Specific symbol to backtest (e.g. BTCUSDm)"
    )
    
    args = parser.parse_args()
    
    # Créer et démarrer le bot
    bot = SMCTradingBot(config_path=args.config)
    
    if args.mode == "backtest":
        bot._run_backtest(symbol=args.symbol)
    else:
        bot.start(mode=args.mode)


if __name__ == "__main__":
    main()
