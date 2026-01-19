"""
Proactive News Alerts - Notification 4h avant événements critiques
Envoie des alertes Discord/Telegram pour préparer le trader

Author: Antigravity AI
Date: 2026-01-11
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
from loguru import logger
import asyncio
import threading
import time


class ProactiveNewsAlerts:
    """
    Système d'alertes proactives pour les news économiques.
    
    Envoie des notifications 4h avant les événements HIGH impact
    pour permettre au trader de se préparer.
    
    Usage:
        >>> alerts = ProactiveNewsAlerts(news_filter, discord, telegram)
        >>> alerts.start()  # Démarre le monitoring en arrière-plan
    """
    
    def __init__(self, news_filter, discord_notifier=None, telegram_notifier=None, config: Dict = None):
        """
        Args:
            news_filter: Instance du NewsFilter
            discord_notifier: Notifieur Discord
            telegram_notifier: Notifieur Telegram
            config: Configuration du bot
        """
        self.news_filter = news_filter
        self.discord = discord_notifier
        self.telegram = telegram_notifier
        
        # Configuration
        proactive_config = config.get('filters', {}).get('news', {}).get('proactive_alerts', {})
        self.enabled = proactive_config.get('enabled', True)
        self.alert_hours_before = proactive_config.get('alert_hours_before', 4)
        self.alert_high_only = proactive_config.get('alert_high_only', True)
        
        # État interne
        self._notified_events = set()  # Events déjà notifiés (éviter spam)
        self._running = False
        self._thread = None
        
        if self.enabled:
            logger.info(f"🔔 Proactive News Alerts: ACTIVÉ (alert {self.alert_hours_before}h avant)")
        else:
            logger.info("🔔 Proactive News Alerts: DÉSACTIVÉ")
    
    def start(self):
        """Démarre le monitoring en arrière-plan."""
        if not self.enabled:
            return
        
        if self._running:
            logger.warning("Proactive alerts already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self._thread.start()
        
        logger.info("🔔 Proactive alerts monitoring started")
    
    def stop(self):
        """Arrête le monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("🔔 Proactive alerts monitoring stopped")
    
    def _monitoring_loop(self):
        """Boucle de monitoring principal (thread background)."""
        while self._running:
            try:
                self._check_upcoming_events()
                # Vérifier toutes les 15 minutes
                time.sleep(900)
            except Exception as e:
                logger.error(f"Error in proactive alerts loop: {e}")
                time.sleep(60)  # Attendre 1min en cas d'erreur
    
    def _check_upcoming_events(self):
        """Vérifie s'il y a des événements critiques à venir."""
        try:
            # Rafraîchir le cache des news
            self.news_filter._update_cache()
            
            now = datetime.now()
            alert_window_start = now + timedelta(hours=self.alert_hours_before - 0.5)  # 3.5h à 4.5h
            alert_window_end = now + timedelta(hours=self.alert_hours_before + 0.5)
            
            # Parcourir les événements
            for event in self.news_filter.events_cache:
                # Filtrer par impact
                if self.alert_high_only and event.impact != 'high':
                    continue
                
                # Vérifier si l'événement est dans la fenêtre d'alerte
                if alert_window_start <= event.time <= alert_window_end:
                    # Créer clé unique pour éviter de notifier 2 fois
                    event_key = f"{event.time.isoformat()}_{event.currency}_{event.event}"
                    
                    if event_key not in self._notified_events:
                        self._send_proactive_alert(event)
                        self._notified_events.add(event_key)
            
            # Nettoyer les vieux événements notifiés (> 24h)
            cutoff = now - timedelta(hours=24)
            self._notified_events = {
                k for k in self._notified_events
                if datetime.fromisoformat(k.split('_')[0]) > cutoff
            }
            
        except Exception as e:
            logger.error(f"Error checking upcoming events: {e}")
    
    def _send_proactive_alert(self, event):
        """Envoie une alerte proactive pour un événement."""
        now = datetime.now()
        hours_to_event = (event.time - now).total_seconds() / 3600
        
        # Emoji selon impact
        impact_emoji = "🔴" if event.impact == 'high' else "🟡" if event.impact == 'medium' else "🟢"
        
        # Message formaté
        message = (
            f"⚠️ **ALERTE NEWS CRITIQUE** ⚠️\n\n"
            f"{impact_emoji} **{event.event}**\n"
            f"🌍 Devise: **{event.currency}**\n"
            f"⏰ Heure: **{event.time.strftime('%Y-%m-%d %H:%M')}** "
            f"(dans {hours_to_event:.1f}h)\n"
            f"📊 Impact: **{event.impact.upper()}**\n\n"
        )
        
        if event.forecast:
            message += f"📈 Forecast: {event.forecast}\n"
        if event.previous:
            message += f"📉 Previous: {event.previous}\n"
        
        message += (
            f"\n💡 **Conseil:**\n"
            f"• Éviter nouveaux trades {self.news_filter.pause_before}min avant\n"
            f"• Positions ouvertes: Réduire exposition ou fermer\n"
            f"• Surveiller la volatilité après publication\n"
        )
        
        # Log
        logger.warning(f"🔔 PROACTIVE ALERT: {event.event} ({event.currency}) dans {hours_to_event:.1f}h")
        
        # Envoyer via Discord
        if self.discord:
            try:
                self.discord.send_message(
                    title="⚠️ ALERTE NEWS CRITIQUE",
                    description=message,
                    color="orange"
                )
            except Exception as e:
                logger.error(f"Error sending Discord alert: {e}")
        
        # Envoyer via Telegram
        if self.telegram:
            try:
                self.telegram.send_message(message)
            except Exception as e:
                logger.error(f"Error sending Telegram alert: {e}")
    
    def check_next_24h(self) -> List[Dict]:
        """
        Retourne les événements HIGH impact des prochaines 24h.
        Utile pour affichage dashboard.
        
        Returns:
            Liste d'événements avec temps restant
        """
        if not self.enabled:
            return []
        
        try:
            self.news_filter._update_cache()
            
            now = datetime.now()
            cutoff = now + timedelta(hours=24)
            
            upcoming = []
            
            for event in self.news_filter.events_cache:
                if event.time > cutoff:
                    continue
                
                if self.alert_high_only and event.impact != 'high':
                    continue
                
                hours_to = (event.time - now).total_seconds() / 3600
                
                if hours_to > 0:  # Seulement futurs
                    upcoming.append({
                        'event': event.event,
                        'currency': event.currency,
                        'time': event.time,
                        'hours_to': hours_to,
                        'impact': event.impact,
                        'forecast': event.forecast,
                        'previous': event.previous
                    })
            
            # Trier par proximité
            upcoming.sort(key=lambda x: x['hours_to'])
            
            return upcoming
            
        except Exception as e:
            logger.error(f"Error getting next 24h events: {e}")
            return []
    
    def display_upcoming_critical(self):
        """Affiche les événements critiques à venir (console)."""
        events = self.check_next_24h()
        
        if not events:
            print("\n✅ Aucun événement HIGH impact dans les 24 prochaines heures")
            return
        
        print("\n" + "="*70)
        print("⚠️ ÉVÉNEMENTS CRITIQUES - PROCHAINES 24 HEURES")
        print("="*70)
        
        for event in events:
            impact_emoji = "🔴" if event['impact'] == 'high' else "🟡"
            time_str = event['time'].strftime("%Y-%m-%d %H:%M")
            hours = event['hours_to']
            
            print(f"\n{impact_emoji} {event['event']}")
            print(f"   Devise: {event['currency']}")
            print(f"   Heure: {time_str} (dans {hours:.1f}h)")
            if event['forecast']:
                print(f"   Forecast: {event['forecast']}")
            if event['previous']:
                print(f"   Previous: {event['previous']}")
        
        print("\n" + "="*70)


# ============================================================================
# INTÉGRATION DANS LE BOT PRINCIPAL
# ============================================================================

def init_proactive_alerts(bot):
    """
    Initialise les alertes proactives dans le bot principal.
    À appeler depuis main.py après init du bot.
    
    Args:
        bot: Instance du SMCTradingBot
        
    Returns:
        Instance ProactiveNewsAlerts
    """
    if not hasattr(bot, 'news_filter'):
        logger.warning("News filter not found - Proactive alerts disabled")
        return None
    
    alerts = ProactiveNewsAlerts(
        news_filter=bot.news_filter,
        discord_notifier=bot.discord if hasattr(bot, 'discord') else None,
        telegram_notifier=bot.telegram if hasattr(bot, 'telegram') else None,
        config=bot.config
    )
    
    alerts.start()
    
    return alerts


if __name__ == "__main__":
    # Test standalone
    print("Testing Proactive News Alerts...")
    
    # Mock objects pour test
    class MockNewsFilter:
        def __init__(self):
            self.events_cache = []
            self.pause_before = 30
        
        def _update_cache(self):
            # Simuler un événement dans 4h
            from strategy.news_filter import EconomicEvent
            self.events_cache = [
                EconomicEvent(
                    time=datetime.now() + timedelta(hours=4),
                    currency='USD',
                    impact='high',
                    event='Test NFP',
                    forecast='200K',
                    previous='180K'
                )
            ]
    
    mock_nf = MockNewsFilter()
    
    alerts = ProactiveNewsAlerts(
        news_filter=mock_nf,
        config={'filters': {'news': {'proactive_alerts': {'enabled': True}}}}
    )
    
    print("\n✅ Checking upcoming events...")
    alerts._check_upcoming_events()
    
    print("\n✅ Displaying upcoming critical events...")
    alerts.display_upcoming_critical()
    
    print("\n✅ Test completed!")
