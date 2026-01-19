
import os
import requests
import json
from loguru import logger
from typing import Optional

class TelegramNotifier:
    """
    Gère l'envoi de notifications vers Telegram.
    Nécessite TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID.
    """
    
    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.enabled = bool(self.bot_token and self.chat_id)
        
        if self.enabled:
            logger.info("✅ Notifications Telegram activées")
        else:
            logger.warning("⚠️ Telegram non configuré (Token ou ChatID manquant).")

    def _send(self, method: str, data: dict):
        if not self.enabled:
            return
            
        url = f"{self.base_url}/{method}"
        try:
            response = requests.post(url, data=data, timeout=10)
            if response.status_code != 200:
                logger.error(f"Erreur Telegram {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Échec envoi Telegram: {e}")

    def send_message(self, message: str, parse_mode: str = "Markdown"):
        """Envoie un message texte simple."""
        if not self.enabled or not message:
            return
            
        # Telegram a une limite de 4096 caractères
        if len(message) > 4000:
            message = message[:4000] + "\n...(tronqué)"
            
        data = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode
        }
        self._send("sendMessage", data)

    def notify_trade_entry(self, symbol: str, direction: str, entry: float, sl: float, tp: float, risk: float, lots: float, setup: str):
        """Notifie une entrée en trade."""
        emoji = "🟢" if direction == "BUY" else "🔴"
        msg = (
            f"{emoji} **NOUVEAU TRADE: {symbol}**\n"
            f"--------------------------------\n"
            f"**Action:** {direction}\n"
            f"**Prix:** {entry:.5f}\n"
            f"**Lots:** {lots}\n"
            f"**Risque:** ${risk:.2f}\n"
            f"**SL:** {sl:.5f}\n"
            f"**TP:** {tp:.5f}\n"
            f"**Setup:** `{setup}`"
        )
        self.send_message(msg)

    def notify_trade_close(self, symbol: str, profit: float, pnl_percent: float, exit_price: float):
        """Notifie la fermeture."""
        emoji = "💰" if profit > 0 else "🛑"
        msg = (
            f"{emoji} **TRADE FERMÉ: {symbol}**\n"
            f"--------------------------------\n"
            f"**Résultat:** ${profit:+.2f} ({pnl_percent:+.2f}%)\n"
            f"**Prix Sortie:** {exit_price:.5f}"
        )
        self.send_message(msg)

    def notify_smart_coach(self, educational_msg: str):
        """Envoie le message pédagogique (en le nettoyant un peu pour Telegram)."""
        # Telegram Markdown est capricieux, utilisons tel quel ou nettoyons si besoin.
        # Le SmartCoach génère déjà du Markdown compatible Discord (**gras**, etc.), 
        # ça devrait passer sur Telegram.
        self.send_message(educational_msg)
        
    def notify_error(self, error_msg: str):
        """Alerte critique."""
        msg = f"🚨 **ERREUR CRITIQUE** 🚨\n\n{error_msg}"
        self.send_message(msg)
