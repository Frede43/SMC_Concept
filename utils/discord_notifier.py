"""
📢 MODULE DE NOTIFICATION DISCORD
Envoie des alertes de trading enrichies via Webhook.
"""

import os
import json
import requests
from datetime import datetime
from loguru import logger
from typing import Dict, Any, Optional

class DiscordNotifier:
    """Gère l'envoi de notifications vers Discord."""
    
    def __init__(self, webhook_url: str = None):
        # Charger l'URL depuis l'argument ou les variables d'environnement
        self.webhook_url = webhook_url or os.getenv('DISCORD_WEBHOOK_URL')
        self.enabled = bool(self.webhook_url)
        
        if self.enabled:
            logger.info("✅ Notifications Discord activées")
        else:
            logger.warning("⚠️ Webhook Discord non configuré. Notifications désactivées.")

    def send_message(self, content: str = None, embed: Dict = None):
        """Envoie un message simple ou un embed."""
        if not self.enabled:
            return

        payload = {}
        if content:
            payload['content'] = content
        if embed:
            payload['embeds'] = [embed]

        try:
            response = requests.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            if response.status_code not in [200, 204]:
                logger.error(f"Erreur Discord {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Échec envoi Discord: {e}")

    def notify_startup(self, mode: str, account_id: str, balance: float):
        """Notifie le démarrage du bot."""
        embed = {
            "title": "🚀 SMC Bot Démarré",
            "color": 3447003,  # Bleu
            "fields": [
                {"name": "Mode", "value": mode.upper(), "inline": True},
                {"name": "Compte", "value": str(account_id), "inline": True},
                {"name": "Capital Initial", "value": f"${balance:,.2f}", "inline": True},
                {"name": "Heure", "value": datetime.now().strftime("%H:%M:%S"), "inline": False}
            ],
            "footer": {"text": "Ultimate SMC Trading Bot"}
        }
        self.send_message(embed=embed)

    def notify_trade_entry(self, symbol: str, direction: str, entry: float, sl: float, tp: float, risk: float, lots: float, setup: str):
        """Notifie l'ouverture d'un trade."""
        color = 65280 if direction == "BUY" else 16711680 # Vert ou Rouge
        
        embed = {
            "title": f"⚡ Nouveau Trade: {symbol} {direction}",
            "color": color,
            "fields": [
                {"name": "Entrée", "value": f"{entry:.5f}", "inline": True},
                {"name": "Lots", "value": f"{lots}", "inline": True},
                {"name": "Risque", "value": f"${risk:.2f}", "inline": True},
                {"name": "Stop Loss", "value": f"{sl:.5f}", "inline": True},
                {"name": "Take Profit", "value": f"{tp:.5f}", "inline": True},
                {"name": "Setup", "value": setup, "inline": True}
            ],
            "timestamp": datetime.utcnow().isoformat()
        }
        self.send_message(embed=embed)

    def notify_trade_close(self, symbol: str, direction: str, pnl: float, pnl_percent: float, exit_price: float, duration: str):
        """Notifie la fermeture d'un trade."""
        is_win = pnl > 0
        emoji = "💰" if is_win else "🛑"
        color = 65280 if is_win else 16711680
        
        embed = {
            "title": f"{emoji} Trade Fermé: {symbol} {direction}",
            "description": f"Résultat: **${pnl:+.2f} ({pnl_percent:+.2f}%)**",
            "color": color,
            "fields": [
                {"name": "Prix Sortie", "value": f"{exit_price:.5f}", "inline": True},
                {"name": "Durée", "value": duration, "inline": True}
            ],
            "timestamp": datetime.utcnow().isoformat()
        }
        self.send_message(embed=embed)

    def notify_macro_bias_change(self, symbol: str, old_bias: str, new_bias: str, score: float, reasons: list):
        """Notifie un changement de biais macro-économique."""
        emoji = "📈" if new_bias == "BULLISH" else "📉" if new_bias == "BEARISH" else "⚖️"
        color = 65280 if new_bias == "BULLISH" else 16711680 if new_bias == "BEARISH" else 8421504
        
        # Nettoyer les raisons pour l'affichage (max 3)
        reasons_str = "\n".join([f"• {r}" for r in reasons[:3]]) if reasons else "Analyse technique & fondamentale"
        
        embed = {
            "title": f"{emoji} Changement de Biais Macro: {symbol}",
            "description": f"Le sentiment institutionnel est passé de **{old_bias}** à **{new_bias}**",
            "color": color,
            "fields": [
                {"name": "Nouveau Biais", "value": f"**{new_bias}**", "inline": True},
                {"name": "Score Composite", "value": f"{score:+.1f}", "inline": True},
                {"name": "Principaux Facteurs", "value": reasons_str, "inline": False}
            ],
            "footer": {"text": "🌍 Analyse Fondamentale SMC"},
            "timestamp": datetime.utcnow().isoformat()
        }
        self.send_message(embed=embed)

    def notify_error(self, error_msg: str):
        """Notifie une erreur critique."""
        embed = {
            "title": "🚨 Erreur Critique / Kill Switch",
            "description": error_msg,
            "color": 16711680,  # Rouge foncé
            "timestamp": datetime.utcnow().isoformat()
        }
        self.send_message(content="@everyone", embed=embed)

    def notify_smart_coach(self, educational_msg: str):
        """Envoie un message éducatif du Smart Coach."""
        if not educational_msg:
            return
            
        # On découpe si trop long (limite Discord 2000 chars)
        if len(educational_msg) > 1900:
            educational_msg = educational_msg[:1900] + "\n...(suite tronquée)"
            
        self.send_message(content=educational_msg)
