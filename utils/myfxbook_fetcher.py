"""
MyFxBook News Fetcher - Source supplémentaire pour calendrier économique
Intégration avec le système News Filter existant

Author: Antigravity AI
Date: 2026-01-11
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from loguru import logger
import re


class MyFxBookFetcher:
    """
    Récupère les événements du calendrier économique MyFxBook.
    Source: https://www.myfxbook.com/forex-economic-calendar
    
    Note: MyFxBook n'a pas d'API publique, on parse le HTML.
    """
    
    BASE_URL = "https://www.myfxbook.com/forex-economic-calendar"
    
    def __init__(self, timezone_offset: int = 2):
        """
        Args:
            timezone_offset: Décalage horaire GMT (2 pour GMT+2)
        """
        self.timezone_offset = timezone_offset
        self._cache = []
        self._cache_timestamp = None
        self._cache_expiry = timedelta(hours=2)
        
        logger.info("MyFxBook Fetcher initialized")
    
    def fetch_events(self, days_ahead: int = 2) -> List[Dict]:
        """
        Récupère les événements économiques depuis MyFxBook.
        
        Args:
            days_ahead: Nombre de jours à récupérer (défaut: 2)
            
        Returns:
            Liste d'événements au format standardisé
        """
        # Vérifier cache
        if self._is_cache_valid():
            logger.debug(f"MyFxBook: Using cached events ({len(self._cache)} events)")
            return self._cache
        
        events = []
        
        try:
            # Headers pour éviter le blocage
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,fr;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            # Récupérer la page
            logger.debug(f"Fetching MyFxBook calendar: {self.BASE_URL}")
            response = requests.get(self.BASE_URL, headers=headers, timeout=15)
            response.raise_for_status()
            
            # Parser le HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # MyFxBook structure (peut varier - à adapter selon inspect)
            # Rechercher les événements dans les tables
            calendar_rows = soup.find_all('tr', class_=re.compile('calendar'))
            
            if not calendar_rows:
                # Fallback: chercher toutes les lignes avec données économiques
                calendar_rows = soup.find_all('tr', attrs={'data-event': True})
            
            logger.debug(f"MyFxBook: Found {len(calendar_rows)} potential event rows")
            
            for row in calendar_rows:
                try:
                    event = self._parse_event_row(row)
                    if event:
                        events.append(event)
                except Exception as e:
                    logger.debug(f"Error parsing MyFxBook row: {e}")
                    continue
            
            # Trier par date
            events.sort(key=lambda x: x['time'])
            
            # Filtrer uniquement les événements futurs et récents
            now = datetime.now()
            cutoff_past = now - timedelta(hours=1)
            cutoff_future = now + timedelta(days=days_ahead)
            
            events = [
                e for e in events 
                if cutoff_past <= e['time'] <= cutoff_future
            ]
            
            # Mettre en cache
            self._cache = events
            self._cache_timestamp = datetime.now()
            
            logger.info(f"📰 MyFxBook: {len(events)} events fetched successfully")
            
            # Log détaillé des événements HIGH impact
            high_events = [e for e in events if e['impact'] == 'HIGH']
            if high_events:
                logger.info(f"   → {len(high_events)} HIGH impact events detected")
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"MyFxBook request error: {e}")
        except Exception as e:
            logger.error(f"MyFxBook parsing error: {e}")
        
        return events
    
    def _parse_event_row(self, row) -> Optional[Dict]:
        """
        Parse une ligne d'événement MyFxBook.
        
        Structure typique MyFxBook:
        <tr data-event="XXX">
            <td class="calendar__time">14:30</td>
            <td class="calendar__currency">USD</td>
            <td class="calendar__impact">high/medium/low</td>
            <td class="calendar__event">Non-Farm Payrolls</td>
            <td class="calendar__actual">...</td>
            <td class="calendar__forecast">...</td>
            <td class="calendar__previous">...</td>
        </tr>
        """
        try:
            # Extraire les données (adapter selon structure réelle)
            time_elem = row.find('td', class_=re.compile('time|date'))
            currency_elem = row.find('td', class_=re.compile('currency|country'))
            impact_elem = row.find('td', class_=re.compile('impact|importance'))
            event_elem = row.find('td', class_=re.compile('event|title'))
            forecast_elem = row.find('td', class_=re.compile('forecast'))
            previous_elem = row.find('td', class_=re.compile('previous'))
            
            if not (time_elem and currency_elem and event_elem):
                return None
            
            # Parser le temps
            time_str = time_elem.get_text(strip=True)
            event_datetime = self._parse_time(time_str)
            
            if not event_datetime:
                return None
            
            # Extraire devise
            currency = currency_elem.get_text(strip=True).upper()
            if len(currency) > 3:
                currency = currency[:3]  # Garder les 3 premiers caractères
            
            # Extraire impact
            impact = self._parse_impact(impact_elem)
            
            # Extraire événement
            event_name = event_elem.get_text(strip=True)
            
            # Extraire forecast et previous
            forecast = forecast_elem.get_text(strip=True) if forecast_elem else ''
            previous = previous_elem.get_text(strip=True) if previous_elem else ''
            
            return {
                'time': event_datetime,
                'currency': currency,
                'impact': impact,
                'event': event_name,
                'forecast': forecast,
                'previous': previous,
                'source': 'MyFxBook'
            }
            
        except Exception as e:
            logger.debug(f"Error parsing event row: {e}")
            return None
    
    def _parse_time(self, time_str: str) -> Optional[datetime]:
        """
        Parse le temps depuis MyFxBook et converti en heure locale.
        
        Formats possibles:
        - "14:30" (aujourd'hui)
        - "Jan 11 14:30"
        - "2026-01-11 14:30"
        """
        try:
            now = datetime.now()
            
            # Format HH:MM (aujourd'hui)
            if ':' in time_str and len(time_str) <= 5:
                hour, minute = map(int, time_str.split(':'))
                event_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                # Si l'heure est passée aujourd'hui, c'est pour demain
                if event_time < now:
                    event_time += timedelta(days=1)
                
                return event_time
            
            # Format avec date (à implémenter selon format réel)
            # ...
            
            return None
            
        except Exception as e:
            logger.debug(f"Error parsing time '{time_str}': {e}")
            return None
    
    def _parse_impact(self, impact_elem) -> str:
        """
        Parse le niveau d'impact depuis MyFxBook.
        
        Returns:
            'high', 'medium', ou 'low'
        """
        if not impact_elem:
            return 'low'
        
        # Vérifier les classes CSS
        classes = impact_elem.get('class', [])
        classes_str = ' '.join(classes).lower()
        
        if 'high' in classes_str or 'red' in classes_str:
            return 'high'
        elif 'medium' in classes_str or 'orange' in classes_str or 'yellow' in classes_str:
            return 'medium'
        else:
            return 'low'
    
    def _is_cache_valid(self) -> bool:
        """Vérifie si le cache est encore valide."""
        if not self._cache or not self._cache_timestamp:
            return False
        
        age = datetime.now() - self._cache_timestamp
        return age < self._cache_expiry
    
    def get_high_impact_events(self, hours_ahead: int = 24) -> List[Dict]:
        """
        Retourne uniquement les événements HIGH impact à venir.
        
        Args:
            hours_ahead: Horizon temporel en heures
            
        Returns:
            Liste d'événements HIGH impact
        """
        events = self.fetch_events()
        
        now = datetime.now()
        cutoff = now + timedelta(hours=hours_ahead)
        
        return [
            e for e in events
            if e['impact'] == 'high' and now <= e['time'] <= cutoff
        ]


# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================

def test_myfxbook_fetcher():
    """Test rapide du fetcher MyFxBook."""
    fetcher = MyFxBookFetcher(timezone_offset=2)
    
    print("\n" + "="*70)
    print("TEST MYFXBOOK FETCHER")
    print("="*70)
    
    events = fetcher.fetch_events(days_ahead=2)
    
    print(f"\n📊 Total events: {len(events)}")
    
    if events:
        print("\n📅 UPCOMING EVENTS:")
        print("-"*70)
        
        for event in events[:10]:  # Afficher les 10 premiers
            impact_emoji = "🔴" if event['impact'] == 'high' else "🟡" if event['impact'] == 'medium' else "🟢"
            time_str = event['time'].strftime("%Y-%m-%d %H:%M")
            print(f"{impact_emoji} {time_str} | {event['currency']:3} | {event['event'][:45]}")
        
        if len(events) > 10:
            print(f"\n... et {len(events) - 10} autres événements")
    else:
        print("\n⚠️ Aucun événement récupéré (vérifier la connection ou la structure HTML)")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    # Test du module
    test_myfxbook_fetcher()
