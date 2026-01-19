
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from loguru import logger

try:
    import investpy
    INVESTPY_AVAILABLE = True
except ImportError:
    INVESTPY_AVAILABLE = False

class NewsFetcher:
    """
    Récupère les événements du calendrier économique.
    """
    
    def __init__(self, config: Dict):
        self.config = config
        news_config = config.get('fundamental', {}).get('news_filter', {})
        self.enabled = news_config.get('enabled', True)
        self.high_impact_only = news_config.get('high_impact_only', True)
        
        # Cache pour éviter de spammer les serveurs
        self._cache = {}  # {symbol: (timestamp, data)}
        self._cache_expiry = timedelta(hours=1)
        
        if not INVESTPY_AVAILABLE:
            logger.warning("NewsFetcher: investpy not installed. Calendar disabled.")
            self.enabled = False
        elif self.enabled:
            logger.info("NewsFetcher: Initialized (investpy)")

    def get_upcoming_news(self, symbol: str, hours: int = 24) -> List[Dict]:
        """
        Récupère les news à venir pour les devises liées au symbole.
        """
        if not self.enabled:
            return []
            
        cur1, cur2 = self._extract_currencies(symbol)
        relevant_currencies = [cur1, cur2]
        
        # Vérifier cache
        cache_key = tuple(sorted(relevant_currencies))
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if datetime.now() - ts < self._cache_expiry:
                return data
        
        try:
            # investpy requires from_date and to_date where to_date > from_date
            now = datetime.now()
            from_date = now.strftime('%d/%m/%Y')
            # Add at least 1 day to to_date even if hours < 24 to avoid "to_date should be greater than from_date"
            end_dt = now + timedelta(hours=max(hours, 24))
            to_date = end_dt.strftime('%d/%m/%Y')
            
            # If still same date (unlikely with +24h but safe check), add one more day
            if from_date == to_date:
                end_dt = now + timedelta(days=1)
                to_date = end_dt.strftime('%d/%m/%Y')
            
            # Récupérer le calendrier (investpy)
            # On récupère pour tous les pays et on filtrera après
            # Note: investpy peut être instable parfois (erreurs Cloudflare)
            df = investpy.economic_calendar(
                from_date=from_date,
                to_date=to_date
            )
            
            if df is None or df.empty:
                return []
                
            # Filtrer par devise et impact
            results = []
            for _, row in df.iterrows():
                currency = str(row['currency']).upper()
                impact = str(row['importance']).upper()  # 'high', 'medium', 'low'
                
                if currency in relevant_currencies:
                    if not self.high_impact_only or impact == 'HIGH':
                        results.append({
                            'time': datetime.strptime(f"{row['date']} {row['time']}", "%d/%m/%Y %H:%M"),
                            'currency': currency,
                            'event': row['event'],
                            'impact': impact,
                            'actual': row['actual'],
                            'forecast': row['forecast'],
                            'previous': row['previous']
                        })
            
            # Trier par temps
            results.sort(key=lambda x: x['time'])
            
            # Mettre en cache
            self._cache[cache_key] = (datetime.now(), results)
            
            return results
            
        except Exception as e:
            logger.error(f"📰 Erreur NewsFetcher pour {symbol}: {e}")
            # Fallback vers un service de news simulé ou vide
            return []

    def _extract_currencies(self, symbol: str) -> List[str]:
        """Extrait les devises (ex: EURUSD -> [EUR, USD])"""
        # Supprimer les suffixes
        clean_sym = symbol.upper().replace('M', '').replace('PRO', '')
        
        if len(clean_sym) == 6:
            return [clean_sym[:3], clean_sym[3:]]
        elif 'XAU' in clean_sym:
            return ['XAU', 'USD']
        elif 'BTC' in clean_sym:
            return ['BTC', 'USD']
        else:
            return [clean_sym, 'USD']
