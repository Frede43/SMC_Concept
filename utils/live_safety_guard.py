"""
🚨 LIVE SAFETY GUARD 🚨
Module de sécurité critique pour le trading en réel.
Ce module agit comme un pare-feu final avant toute exécution en mode LIVE.
"""

import os
import sys
from typing import Dict, Any
from loguru import logger
from dotenv import load_dotenv

import MetaTrader5 as mt5

class LiveSafetyGuard:
    """
    Garde-fou pour le trading LIVE.
    Vérifie les conditions de sécurité critiques avant d'autoriser le trading.
    """
    
    # 🔒 CONSTANTES DE SÉCURITÉ (HARDCODED - NE PAS MODIFIER)
    MAX_LIVE_RISK_PERCENT = 1.0     # Risque max absolu autorisé en code (même si config dit 20%)
    RECOMMENDED_RISK = 0.5          # Risque recommandé
    MIN_BALANCE_CHECK = 50.0        # Balance minimum pour trader
    
    def __init__(self, mt5_connector, config: Dict[str, Any]):
        self.mt5 = mt5_connector
        self.config = config
        load_dotenv() # Recharger les variables d'env
        
    def validate_environment(self, mode_override: str = None) -> bool:
        """
        Exécute toutes les vérifications de sécurité.
        Lève une exception critique si une règle de sécurité est violée.
        """
        # Priorité à l'argument CLI, sinon config YAML
        mode = mode_override.lower() if mode_override else self.config.get('general', {}).get('mode', 'demo').lower()
        
        # Si on n'est pas en LIVE, la sécurité est moins stricte (mais on vérifie quand même)
        if mode != "live":
            logger.info(f"🛡️ Mode {mode.upper()}: Vérifications de sécurité allégées passées.")
            return True
            
        logger.info("🛡️ INITIALISATION DU PROTOCOLE DE SÉCURITÉ LIVE...")
        
        # ✅ DÉTECTION COMPTE DEMO
        # Si c'est un compte démo, on autorise l'exécution sans les blocages stricts
        # Cela permet de tester le bot en conditions réelles (exécution) sans risque financier
        try:
            account_info = self.mt5.get_account_info()
            if account_info and 'trade_mode' in account_info:
                # ACCOUNT_TRADE_MODE_REAL = 2
                is_real_money = (account_info['trade_mode'] == mt5.ACCOUNT_TRADE_MODE_REAL)
                
                if not is_real_money:
                    logger.success("🛡️ COMPTE DEMO DÉTECTÉ: Protokole sécurité allégé autorisé.")
                    logger.info("   ✅ Mode LIVE actif sur compte DEMO -> Les ordres SERONT EXÉCUTÉS.")
                    return True
        except Exception as e:
            logger.warning(f"⚠️ Impossible de vérifier le type de compte: {e}")

        logger.warning("⚠️ ATTENTION: VOUS ÊTES SUR LE POINT DE TRADER DU CAPITAL RÉEL ⚠️")
        
        try:
            # 1. Vérifier Account ID Whitelist
            self._check_account_whitelist()
            
            # 2. Vérifier Risque Configuré
            self._check_risk_limits()
            
            # 3. Vérifier État du Compte
            self._check_account_health()
            
            # 4. Vérifier Variables d'Environnement Critiques
            self._check_env_vars()
            
            logger.success("✅ PROTOCOLE DE SÉCURITÉ LIVE: VALIDÉ (Toutes les vérifications sont OK)")
            return True
            
        except Exception as e:
            logger.critical("="*60)
            logger.critical("🛑 ÉCHEC DU PROTOCOLE DE SÉCURITÉ - ARRÊT IMMÉDIAT 🛑")
            logger.critical(f"Raison: {str(e)}")
            logger.critical("="*60)
            return False

    def _check_account_whitelist(self):
        """Vérifie que le compte connecté est bien celui autorisé."""
        # Récupérer l'ID du compte connecté
        account_info = self.mt5.get_account_info()
        if not account_info:
            raise SecurityViolation("Impossible de lire les infos du compte MT5.")
            
        connected_id = int(account_info.get('login', 0))
        
        # Récupérer l'ID autorisé depuis .env
        authorized_id_str = os.getenv('LIVE_ACCOUNT_ID')
        
        if not authorized_id_str:
            raise SecurityViolation("LIVE_ACCOUNT_ID manquant dans le fichier .env! Configuration requise pour le LIVE.")
            
        try:
            authorized_id = int(authorized_id_str)
        except ValueError:
            raise SecurityViolation(f"LIVE_ACCOUNT_ID invalide dans .env: {authorized_id_str}")
            
        if connected_id != authorized_id:
            logger.critical(f"Compte connecté: {connected_id}")
            logger.critical(f"Compte autorisé: {authorized_id}")
            raise SecurityViolation("⛔ Mismatch Compte: Le compte MT5 connecté ne correspond pas à la whitelist .env!")
            
        logger.info(f"✅ Compte {connected_id} vérifié et autorisé.")

    def _check_risk_limits(self):
        """Vérifie que le risque configuré ne dépasse pas les limites de sécurité."""
        # 1. Risque par trade
        risk_per_trade = self.config.get('risk', {}).get('risk_per_trade', 1.0)
        
        if risk_per_trade > self.MAX_LIVE_RISK_PERCENT:
            msg = (f"⛔ Risque configuré ({risk_per_trade}%) dépasse la limite de sécurité absolue ({self.MAX_LIVE_RISK_PERCENT}%). "
                   f"Changez 'risk_per_trade' dans settings.yaml.")
            raise SecurityViolation(msg)
            
        if risk_per_trade > self.RECOMMENDED_RISK:
            logger.warning(f"⚠️ Le risque ({risk_per_trade}%) est supérieur au recommandé ({self.RECOMMENDED_RISK}%). Soyez prudent.")
            
        # 2. Daily Loss Limit
        max_daily_loss = self.config.get('risk', {}).get('max_daily_loss', 100.0)
        if max_daily_loss > 5.0:
             logger.warning(f"⚠️ Max Daily Loss ({max_daily_loss}%) semble très élevé. Recommandé: < 3.0%")
             
        # 3. Mode Lot Fixe vs %
        use_fixed = self.config.get('risk', {}).get('use_fixed_lot', False)
        if not use_fixed:
            logger.warning("⚠️ Attention: Mode % du capital activé. En début de LIVE, le mode 'use_fixed_lot' est recommandé.")

    def _check_account_health(self):
        """Vérifie la santé du compte (Balance, Levier, Trading autorisé)."""
        account = self.mt5.get_account_info()
        
        # Balance minimum
        if account['balance'] < self.MIN_BALANCE_CHECK:
            raise SecurityViolation(f"Balance trop faible (${account['balance']}) pour le trading algo sécurisé.")
            
        # Trading algo autorisé
        if not account['trade_allowed']:
             raise SecurityViolation("Le trading est désactivé sur ce compte (Investisseur ou Désactivé par le broker).")
             
        if not account['trade_expert']:
             raise SecurityViolation("Le trading automatisé (AutoTrading) est désactivé dans MT5. Veuillez cliquer sur le bouton 'Algo Trading'.")

    def _check_env_vars(self):
        """Vérifie les flags explicites."""
        # On demande une confirmation explicite dans le .env pour éviter les lancements accidentels
        live_confirmed = os.getenv('CONFIRM_LIVE_MODE', 'false').lower() == 'true'
        
        if not live_confirmed:
            raise SecurityViolation("Confirmation manquante. Ajoutez CONFIRM_LIVE_MODE=true dans .env pour autoriser le LIVE.")

class SecurityViolation(Exception):
    """Exception levée en cas de violation de sécurité."""
    pass
