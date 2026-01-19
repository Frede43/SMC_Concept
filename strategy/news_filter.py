"""
News Filter - Filtre les trades pendant les événements économiques importants
Utilise l'API de calendrier économique réelle (ForexFactory) pour éviter le trading pendant les news
"""

import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from loguru import logger
import json
from pathlib import Path
import re


@dataclass
class EconomicEvent:
    time: datetime
    currency: str
    impact: str  # 'high', 'medium', 'low'
    event: str
    forecast: str
    previous: str


class NewsFilter:
    """
    Filtre les trades pendant les événements économiques à fort impact.
    
    Utilise ForexFactory et TradingView comme sources de données réelles.
    
    Intègre un calendrier économique pour:
    - Identifier les événements high/medium impact
    - Pause trading X minutes avant/après ces événements
    - Filtrage par devise (USD, EUR, GBP, etc.)
    """
    
    # Mapping symbole -> devises concernées
    SYMBOL_CURRENCIES = {
        "EURUSD": ["EUR", "USD"],
        "GBPUSD": ["GBP", "USD"],
        "USDJPY": ["USD", "JPY"],
        "XAUUSD": ["XAU", "USD"],
        "USDCHF": ["USD", "CHF"],
        "AUDUSD": ["AUD", "USD"],
        "USDCAD": ["USD", "CAD"],
        "NZDUSD": ["NZD", "USD"],
    }
    
    def __init__(self, config: Dict):
        # Chercher dans 'filters.news' (nouveau) ou 'filters.news_filter' (ancien)
        filters = config.get('filters', {})
        news_config = filters.get('news', filters.get('news_filter', config.get('news_filter', {})))
        
        self.enabled = news_config.get('enabled', True)
        self.pause_before = news_config.get('minutes_before', news_config.get('pause_minutes_before', 30))
        self.pause_after = news_config.get('minutes_after', news_config.get('pause_minutes_after', 15))
        self.filter_high = news_config.get('filter_high_impact', news_config.get('avoid_high_impact', True))
        self.filter_medium = news_config.get('filter_medium_impact', False)
        self.timezone_offset = news_config.get('timezone_offset', 2)  # GMT+2 par défaut
        
        # Cache des événements
        self.events_cache: List[EconomicEvent] = []
        self.cache_date: Optional[datetime] = None
        self.api_source: str = "none"
        
        # Fichier de cache local
        self.cache_file = Path("data/news_cache.json")
        
        logger.info(f"NewsFilter initialized - Enabled: {self.enabled}, "
                   f"Pause: {self.pause_before}min before, {self.pause_after}min after")
    
    def is_trading_allowed(self, symbol: str) -> Tuple[bool, Optional[str]]:
        """
        Vérifie si le trading est autorisé pour le symbole donné.
        
        Returns:
            Tuple[bool, Optional[str]]: (allowed, reason)
        """
        if not self.enabled:
            return True, None
        
        # Récupérer les devises concernées par le symbole
        currencies = self.SYMBOL_CURRENCIES.get(symbol, [])
        if not currencies:
            # Essayer d'extraire les devises du symbole
            if len(symbol) >= 6:
                currencies = [symbol[:3], symbol[3:6]]
        
        # Vérifier les événements proches
        now = datetime.now()
        
        # Mettre à jour le cache si nécessaire
        self._update_cache()
        
        for event in self.events_cache:
            # Vérifier si l'événement concerne le symbole
            if event.currency not in currencies and event.currency != "*":
                continue
            
            # Vérifier le niveau d'impact
            if event.impact == "high" and not self.filter_high:
                continue
            if event.impact == "medium" and not self.filter_medium:
                continue
            if event.impact == "low":
                continue
            
            # Ajustement dynamique de la pause selon le type d'événement
            # Expérience Trading: Les discours (Speeches) ont un impact immédiat mais moins durable que les Data (NFP/CPI)
            current_pause_after = self.pause_after
            
            is_speech = any(k in event.event.lower() for k in ['speak', 'speech', 'testif', 'conference', 'minutes'])
            if is_speech:
                # Plafonner la pause après un discours à 20 minutes max (suffisant pour l'absorption par les algos)
                current_pause_after = min(current_pause_after, 20)
                
            pause_start = event.time - timedelta(minutes=self.pause_before)
            pause_end = event.time + timedelta(minutes=current_pause_after)
            
            if pause_start <= now <= pause_end:
                minutes_to_event = (event.time - now).total_seconds() / 60
                source_tag = f"[{self.api_source}]" if self.api_source != "simulated" else "[SIM]"
                
                if minutes_to_event > 0:
                    reason = f"📰 {source_tag} {event.event} ({event.currency}) dans {minutes_to_event:.0f} min"
                else:
                    reason = f"📰 {source_tag} {event.event} ({event.currency}) il y a {-minutes_to_event:.0f} min"
                
                logger.warning(reason)
                return False, reason
        
        return True, None
    
    def check_emergency_exit(self, symbol: str, horizon_minutes: int = 5) -> Tuple[bool, Optional[str]]:
        """
        Vérifie si une news majeure arrive dans un horizon très court (Stratégie 2).
        Utilisé pour fermer les positions ouvertes.
        """
        if not self.enabled:
            return False, None
            
        currencies = self.SYMBOL_CURRENCIES.get(symbol, [])
        if not currencies and len(symbol) >= 6:
            currencies = [symbol[:3], symbol[3:6]]
            
        now = datetime.now()
        self._update_cache()
        
        for event in self.events_cache:
            if event.currency not in currencies and event.currency != "*":
                continue
            if event.impact != "high":
                continue
                
            # Delta temps
            time_to_event = (event.time - now).total_seconds() / 60
            
            # Si la news est entre 0 et horizon_minutes dans le futur
            if 0 <= time_to_event <= horizon_minutes:
                reason = f"🚨 EMERGENCY EXIT: {event.event} ({event.currency}) dans {time_to_event:.1f} min"
                return True, reason
                
        return False, None
    
    def _update_cache(self):
        """Met à jour le cache des événements économiques."""
        now = datetime.now()
        
        # Recharger le cache toutes les 2 heures (ou 5 min si simulé)
        mem_duration = 300 if self.api_source == 'simulated' else 7200
        if self.cache_date and (now - self.cache_date).total_seconds() < mem_duration:
            return
        
        # Essayer de charger depuis le fichier de cache
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    cache_time = datetime.fromisoformat(cached_data.get('timestamp', '2000-01-01'))
                    
                    duration = 300 if cached_data.get('source') == 'simulated' else 14400
                    if (now - cache_time).total_seconds() < duration:
                        self.events_cache = [
                            EconomicEvent(
                                time=datetime.fromisoformat(e['time']),
                                currency=e['currency'],
                                impact=e['impact'],
                                event=e['event'],
                                forecast=e.get('forecast', ''),
                                previous=e.get('previous', '')
                            )
                            for e in cached_data.get('events', [])
                        ]
                        self.api_source = cached_data.get('source', 'cache')
                        self.cache_date = now
                        logger.debug(f"📰 Loaded {len(self.events_cache)} events from cache ({self.api_source})")
                        return
        except Exception as e:
            logger.debug(f"Could not load news cache: {e}")
        
        # Essayer de récupérer les événements depuis l'API
        events, source = self._fetch_events_from_api()
        
        if events:
            self.events_cache = events
            self.api_source = source
            logger.info(f"📰 Loaded {len(events)} REAL economic events from {source}")
        else:
            # Fallback sur les événements simulés
            self.events_cache = self._get_simulated_events()
            self.api_source = "simulated"
            logger.warning("📰 Using simulated events (API unavailable)")
        
        self.cache_date = now
        
        # Sauvegarder le cache
        self._save_cache()
    
    def _fetch_events_from_api(self) -> Tuple[List[EconomicEvent], str]:
        """
        Récupère les événements économiques depuis une API réelle.
        Essaie plusieurs sources dans l'ordre avec validation croisée.
        
        🆕 AMÉLIORATION: Utilise maintenant 3 sources (ForexFactory, TradingView, MyFxBook)
        avec validation croisée pour augmenter la fiabilité.
        """
        
        all_sources = []
        
        # 1. Essayer ForexFactory d'abord (Source primaire)
        try:
            events_ff = self._fetch_from_forex_factory()
            if events_ff and len(events_ff) > 3:
                all_sources.append(('ForexFactory', events_ff))
                logger.debug(f"✅ ForexFactory: {len(events_ff)} events")
        except Exception as e:
            logger.debug(f"ForexFactory fetch failed: {e}")
        
        # 2. Essayer TradingView Calendar
        try:
            events_tv = self._fetch_from_tradingview()
            if events_tv and len(events_tv) > 3:
                all_sources.append(('TradingView', events_tv))
                logger.debug(f"✅ TradingView: {len(events_tv)} events")
        except Exception as e:
            logger.debug(f"TradingView fetch failed: {e}")
        
        # 3. 🆕 NOUVEAU: Essayer MyFxBook comme 3ème source
        try:
            from utils.myfxbook_fetcher import MyFxBookFetcher
            myfxbook = MyFxBookFetcher(timezone_offset=self.timezone_offset)
            events_mfxb_raw = myfxbook.fetch_events(days_ahead=2)
            
            # Convertir au format EconomicEvent
            events_mfxb = []
            for e in events_mfxb_raw:
                events_mfxb.append(EconomicEvent(
                    time=e['time'],
                    currency=e['currency'],
                    impact=e['impact'],
                    event=e['event'],
                    forecast=e.get('forecast', ''),
                    previous=e.get('previous', '')
                ))
            
            if events_mfxb and len(events_mfxb) > 3:
                all_sources.append(('MyFxBook', events_mfxb))
                logger.debug(f"✅ MyFxBook: {len(events_mfxb)} events")
        except ImportError:
            logger.debug("MyFxBook fetcher not available (module not found)")
        except Exception as e:
            logger.debug(f"MyFxBook fetch failed: {e}")
        
        # 4. 🆕 VALIDATION CROISÉE: Si plusieurs sources disponibles, fusionner
        if len(all_sources) >= 2:
            merged = self._merge_and_validate_sources(all_sources)
            source_names = " + ".join([s[0] for s in all_sources])
            logger.info(f"📰 Multi-source validation: {source_names} → {len(merged)} events")
            return merged, source_names
        
        # 5. Si une seule source, l'utiliser
        elif len(all_sources) == 1:
            source_name, events = all_sources[0]
            return events, source_name
        
        # 6. Aucune source disponible
        return [], "none"
    
    def _fetch_from_forex_factory(self) -> List[EconomicEvent]:
        """
        Récupère les événements depuis ForexFactory via leur feed JSON.
        Source: https://nfs.faireconomy.media
        """
        events = []
        now = datetime.now()
        
        try:
            # ForexFactory week calendar (JSON public feed)
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9'
            }
            
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            logger.debug(f"ForexFactory returned {len(data)} raw events")
            
            for item in data:
                try:
                    # Date et heure - ForexFactory utilise format ISO
                    date_str = item.get('date', '')
                    
                    if not date_str:
                        continue
                    
                    try:
                        # Format ISO: "2024-12-11T14:30:00-05:00"
                        if 'T' in date_str:
                            # Parser ISO datetime avec timezone
                            # Supprimer le timezone pour parser
                            if '-05:00' in date_str:
                                date_clean = date_str.replace('-05:00', '')
                                event_datetime = datetime.fromisoformat(date_clean)
                                # Ajouter 7 heures (EST -> GMT+2)
                                event_datetime = event_datetime + timedelta(hours=self.timezone_offset + 5)
                            elif '+' in date_str or date_str.endswith('Z'):
                                # UTC ou autre timezone
                                date_clean = date_str.replace('Z', '').split('+')[0].split('-05')[0]
                                event_datetime = datetime.fromisoformat(date_clean)
                                event_datetime = event_datetime + timedelta(hours=self.timezone_offset)
                            else:
                                event_datetime = datetime.fromisoformat(date_str)
                        else:
                            # Format simple: "2024-12-11"
                            event_datetime = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=12)
                    except Exception as parse_err:
                        logger.debug(f"Date parse error: {date_str} - {parse_err}")
                        continue
                    
                    # Ne garder que les événements des prochaines 48h et dernière heure
                    time_diff = (event_datetime - now).total_seconds()
                    if time_diff < -3600 or time_diff > 172800:  # -1h à +48h
                        continue
                    
                    # Mapper l'impact
                    impact_raw = item.get('impact', '').lower()
                    if impact_raw in ['high', 'red']:
                        impact = 'high'
                    elif impact_raw in ['medium', 'orange', 'yellow']:
                        impact = 'medium'
                    else:
                        impact = 'low'
                    
                    # Créer l'événement
                    event = EconomicEvent(
                        time=event_datetime,
                        currency=item.get('country', 'USD').upper(),
                        impact=impact,
                        event=item.get('title', 'Unknown Event'),
                        forecast=str(item.get('forecast', '')),
                        previous=str(item.get('previous', ''))
                    )
                    
                    events.append(event)
                    
                except Exception as e:
                    logger.debug(f"Error parsing FF event: {e}")
                    continue
            
            # Trier par date
            events.sort(key=lambda x: x.time)
            
            high_impact = len([e for e in events if e.impact == 'high'])
            logger.info(f"📰 ForexFactory: {len(events)} events ({high_impact} high impact)")
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"ForexFactory request error: {e}")
        except json.JSONDecodeError as e:
            logger.warning(f"ForexFactory JSON error: {e}")
        except Exception as e:
            logger.warning(f"ForexFactory error: {e}")
        
        return events
    
    def _fetch_from_tradingview(self) -> List[EconomicEvent]:
        """
        Récupère les événements depuis TradingView Economic Calendar.
        """
        events = []
        now = datetime.utcnow()
        
        try:
            url = "https://economic-calendar.tradingview.com/events"
            
            from_date = now.strftime("%Y-%m-%dT00:00:00.000Z")
            to_date = (now + timedelta(days=3)).strftime("%Y-%m-%dT23:59:59.999Z")
            
            params = {
                'from': from_date,
                'to': to_date,
                'countries': 'US,EU,GB,JP,AU,CA,CH,NZ',
                'minImportance': 0
            }
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Origin': 'https://www.tradingview.com'
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                # Mapper les codes pays
                country_to_currency = {
                    'US': 'USD', 'EU': 'EUR', 'GB': 'GBP',
                    'JP': 'JPY', 'AU': 'AUD', 'CA': 'CAD',
                    'CH': 'CHF', 'NZ': 'NZD', 'DE': 'EUR',
                    'FR': 'EUR', 'IT': 'EUR'
                }
                
                for item in data.get('result', []):
                    try:
                        # Parser la date
                        date_str = item.get('date', '')
                        if not date_str:
                            continue
                        
                        event_time = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        event_time = event_time.replace(tzinfo=None)
                        
                        # Convertir en heure locale (UTC + timezone_offset)
                        event_time = event_time + timedelta(hours=self.timezone_offset)
                        
                        # Mapper l'importance
                        importance = item.get('importance', 0)
                        if importance >= 2:
                            impact = 'high'
                        elif importance >= 1:
                            impact = 'medium'
                        else:
                            impact = 'low'
                        
                        # Mapper le pays
                        country = item.get('country', 'US')
                        currency = country_to_currency.get(country, 'USD')
                        
                        event = EconomicEvent(
                            time=event_time,
                            currency=currency,
                            impact=impact,
                            event=item.get('title', 'Unknown Event'),
                            forecast=str(item.get('forecast', '')),
                            previous=str(item.get('previous', ''))
                        )
                        
                        events.append(event)
                        
                    except Exception as e:
                        continue
                
                events.sort(key=lambda x: x.time)
                logger.info(f"📰 TradingView: {len(events)} events")
                
        except Exception as e:
            logger.debug(f"TradingView Calendar error: {e}")
        
        return events
    
    def _get_simulated_events(self) -> List[EconomicEvent]:
        """
        Génère des événements simulés comme fallback.
        Basé sur les heures typiques des publications économiques.
        """
        events = []
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Événements typiques par jour de la semaine
        weekday = now.weekday()  # 0=Lundi, 6=Dimanche
        
        daily_events = [
            # (heure locale, minute, currency, impact, event)
            (10, 30, "GBP", "high", "UK Economic Data"),
            (14, 30, "USD", "high", "US Economic Data"),
            (16, 0, "USD", "medium", "US Treasury Data"),
            (20, 0, "USD", "high", "FOMC/Fed Speech"),
        ]
        
        # Événements spécifiques selon le jour
        if weekday == 2:  # Mercredi
            daily_events.append((20, 0, "USD", "high", "FOMC Meeting Minutes"))
        if weekday == 4:  # Vendredi
            daily_events.insert(0, (14, 30, "USD", "high", "NFP/Employment Data"))
        
        for hour, minute, currency, impact, event_name in daily_events:
            event_time = today.replace(hour=hour, minute=minute)
            
            # Ajouter aussi pour demain
            for day_offset in [0, 1]:
                event_dt = event_time + timedelta(days=day_offset)
                
                # Ne garder que les événements futurs ou récents
                if (event_dt - now).total_seconds() > -3600:
                    events.append(EconomicEvent(
                        time=event_dt,
                        currency=currency,
                        impact=impact,
                        event=f"[SIM] {event_name}",
                        forecast="",
                        previous=""
                    ))
        
        events.sort(key=lambda x: x.time)
        return events
    
    def _merge_and_validate_sources(self, sources: List[Tuple[str, List[EconomicEvent]]]) -> List[EconomicEvent]:
        """
        🆕 NOUVEAU: Fusionne et valide les événements de multiples sources.
        
        Logique:
        1. Déduplique les événements similaires (même heure, devise, événement)
        2. Prend l'impact le plus élevé si divergence
        3. Garde les événements confirmés par au moins 2 sources (si disponible)
        
        Args:
            sources: Liste de tuples (nom_source, liste_événements)
            
        Returns:
            Liste fusionnée et validée d'événements
        """
        from collections import defaultdict
        
        # Dictionnaire pour regrouper les événements similaires
        event_groups = defaultdict(list)
        
        # Regrouper les événements par clé (date + heure + devise)
        for source_name, events in sources:
            for event in events:
                # Clé unique: arrondir au quart d'heure + devise
                time_rounded = event.time.replace(minute=(event.time.minute // 15) * 15, second=0, microsecond=0)
                key = (time_rounded, event.currency)
                
                event_groups[key].append((source_name, event))
        
        # Fusionner les événements similaires
        merged_events = []
        
        for key, event_list in event_groups.items():
            if len(event_list) == 1:
                # Un seul événement pour cette clé
                source, event = event_list[0]
                merged_events.append(event)
            else:
                # Plusieurs sources pour le même événement → validation croisée
                # Prendre l'impact le plus élevé
                impact_priority = {'high': 3, 'medium': 2, 'low': 1}
                
                best_event = max(
                    event_list,
                    key=lambda x: impact_priority.get(x[1].impact, 0)
                )[1]
                
                # Combiner les noms d'événements si différents
                event_names = set(e.event for s, e in event_list)
                if len(event_names) > 1:
                    best_event.event = " / ".join(sorted(event_names)[:2])  # Max 2 noms
                
                merged_events.append(best_event)
                
                # Log la validation croisée pour événements HIGH
                if best_event.impact == 'high':
                    sources_str = ", ".join([s for s, e in event_list])
                    logger.debug(f"📊 Cross-validated HIGH event: {best_event.event} "
                               f"(confirmed by: {sources_str})")
        
        # Trier par date
        merged_events.sort(key=lambda x: x.time)
        
        return merged_events
    
    def _save_cache(self):
        """Sauvegarde le cache des événements."""
        try:
            Path("data").mkdir(exist_ok=True)
            
            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'source': self.api_source,
                'events': [
                    {
                        'time': e.time.isoformat(),
                        'currency': e.currency,
                        'impact': e.impact,
                        'event': e.event,
                        'forecast': e.forecast,
                        'previous': e.previous
                    }
                    for e in self.events_cache
                ]
            }
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"📰 Saved {len(self.events_cache)} events to cache")
                
        except Exception as e:
            logger.debug(f"Could not save news cache: {e}")
    
    def get_upcoming_events(self, hours_ahead: int = 24) -> List[EconomicEvent]:
        """Retourne les événements à venir."""
        self._update_cache()
        
        now = datetime.now()
        cutoff = now + timedelta(hours=hours_ahead)
        
        return [e for e in self.events_cache if now <= e.time <= cutoff]
    
    def display_calendar(self):
        """Affiche le calendrier des événements."""
        self._update_cache()
        events = self.get_upcoming_events(48)
        
        print(f"\n📅 CALENDRIER ÉCONOMIQUE - Source: {self.api_source}")
        print("="*70)
        
        if not events:
            print("   Aucun événement majeur prévu dans les 48h")
            return
        
        current_date = None
        for event in sorted(events, key=lambda e: e.time):
            event_date = event.time.date()
            
            if event_date != current_date:
                current_date = event_date
                day_name = event.time.strftime("%A %d %B")
                print(f"\n   📆 {day_name}")
                print("   " + "-"*50)
            
            impact_emoji = "🔴" if event.impact == "high" else "🟡" if event.impact == "medium" else "🟢"
            time_str = event.time.strftime("%H:%M")
            print(f"   {impact_emoji} {time_str} | {event.currency:3} | {event.event[:45]}")
        
        print("\n" + "="*70)
        
    def force_refresh(self):
        """Force le rafraîchissement du cache."""
        self.cache_date = None
        if self.cache_file.exists():
            self.cache_file.unlink()
        self._update_cache()
        logger.info(f"📰 Force refreshed: {len(self.events_cache)} events from {self.api_source}")
