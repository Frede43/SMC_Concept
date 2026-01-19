"""
COT Analyzer - Commitments of Traders Analysis
Analyse le positionnement des institutionnels (CFTC Reports)

Author: SMC Bot Team
Date: 2026-01-07

Note: Ce module nécessite l'implémentation d'une source de données COT.
      Options: CFTC.gov (scraping), Quandl API (payant), ou Barchart scraping.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from loguru import logger
import pandas as pd


@dataclass
class COTData:
    """Données COT pour une devise/commodity."""
    symbol: str
    date: datetime
    
    # Positionnement (en contrats)
    large_specs_long: int = 0
    large_specs_short: int = 0
    commercials_long: int = 0
    commercials_short: int = 0
    small_traders_long: int = 0
    small_traders_short: int = 0
    
    # Calculés
    large_specs_net: int = 0
    commercials_net: int = 0
    small_traders_net: int = 0
    
    # Statistiques (position dans l'historique)
    large_specs_net_percentile: float = 50.0  # 0-100
    commercials_net_percentile: float = 50.0
    
    # Classification
    extreme_level: str = "NORMAL"  # EXTREME_LONG, EXTREME_SHORT, NORMAL
    
    def __post_init__(self):
        """Calcule les nets si non fournis."""
        if self.large_specs_net == 0:
            self.large_specs_net = self.large_specs_long - self.large_specs_short
        if self.commercials_net == 0:
            self.commercials_net = self.commercials_long - self.commercials_short
        if self.small_traders_net == 0:
            self.small_traders_net = self.small_traders_long - self.small_traders_short


class COTAnalyzer:
    """
    Analyse le positionnement COT pour détecter les extrêmes.
    
    Théorie:
    - Large Speculators (Hedge Funds, CTAs): Souvent "wrong" aux extrêmes
    - Commercials (Hedgers, Smart Money): Souvent "right" car hedgent production
    - Small Traders (Retail): Toujours "wrong" (crowd psychology)
    
    Source: CFTC (Commodity Futures Trading Commission)
    Publication: Chaque vendredi 15:30 ET (données du mardi)
    
    Usage:
        >>> analyzer = COTAnalyzer(config)
        >>> score = analyzer.get_score("EURUSD")  # -100 à +100
        >>> # Score positif = Institutionnels bullish
        >>> # Score négatif = Institutionnels bearish
    
    Attributes:
        config (Dict): Configuration du bot
        enabled (bool): Si l'analyseur est activé
        extreme_threshold (float): Seuil en écarts-types pour extrême
        historical_data (Dict): Cache des données historiques
    """
    
    # Mapping symbole → CFTC Market Name (exact match required)
    SYMBOL_TO_CFTC = {
        "EURUSD": "EURO FX",
        "EURUSDm": "EURO FX",
        "GBPUSD": "BRITISH POUND",
        "GBPUSDm": "BRITISH POUND",
        "USDJPY": "JAPANESE YEN",
        "USDJPYm": "JAPANESE YEN",
        "AUDUSD": "AUSTRALIAN DOLLAR",
        "AUDUSDm": "AUSTRALIAN DOLLAR",
        "CADUSD": "CANADIAN DOLLAR",
        "CADUSDm": "CANADIAN DOLLAR",
        "CHFUSD": "SWISS FRANC",
        "CHFUSDm": "SWISS FRANC",
        "XAUUSD": "GOLD",
        "XAUUSDm": "GOLD",
        "XAGUSD": "SILVER",
        "XAGUSDm": "SILVER",
        "WTIUSD": "CRUDE OIL, LIGHT SWEET",
        "WTIUSDm": "CRUDE OIL, LIGHT SWEET",
        "BTCUSD": "BITCOIN",
        "BTCUSDm": "BITCOIN",
    }
    
    def __init__(self, config: Dict):
        """
        Initialise le COT Analyzer.
        
        Args:
            config: Configuration complète du bot
        """
        self.config = config
        cot_config = config.get('fundamental', {}).get('cot_analysis', {})
        
        self.enabled = cot_config.get('enabled', False)
        self.extreme_threshold = cot_config.get('extreme_threshold', 2.0)  # σ
        self.update_frequency = cot_config.get('update_frequency', 'weekly')
        
        # Cache des données COT
        self.historical_data = {}  # {symbol: List[COTData]}
        self.last_update = {}
        self._df_cache = None
        self._df_cache_time = None
        
        if not self.enabled:
            logger.info("📊 COT Analyzer: DÉSACTIVÉ (config)")
            return
        
        logger.info(f"📊 COT Analyzer: ACTIVÉ")
        logger.info(f"   📈 Seuil extrême: ±{self.extreme_threshold}σ")
    
    def get_score(self, symbol: str) -> float:
        """
        Retourne un score COT (-100 à +100).
        """
        if not self.enabled:
            return 0.0
            
        # Nettoyer le symbole pour trouver le mapping
        clean_symbol = symbol
        if symbol not in self.SYMBOL_TO_CFTC:
            # Tenter de retirer les suffixes communs
            for suffix in ['m', 'pro', 'c']:
                if symbol.endswith(suffix):
                    clean_symbol = symbol[:-len(suffix)]
                    if clean_symbol in self.SYMBOL_TO_CFTC:
                        break
        
        if clean_symbol not in self.SYMBOL_TO_CFTC:
            logger.debug(f"📊 {symbol} non supporté par COT analyzer")
            return 0.0
            
        try:
            # Récupérer les données COT récentes
            cot_data = self._fetch_latest_cot(clean_symbol)
            
            if not cot_data:
                logger.debug(f"📊 Pas de données COT pour {symbol}")
                return 0.0
            
            # Score basé sur Large Specs (retail proxy)
            # Théorie: Quand retail est massivement long → Reversal short attendu
            specs_percentile = cot_data.large_specs_net_percentile
            
            # Logique contrarian
            if specs_percentile > 80:
                # Large specs très long → Overbought → Score négatif
                score = -(specs_percentile - 50) * 2  # -60 à -100
            elif specs_percentile < 20:
                # Large specs très short → Oversold → Score positif
                score = (50 - specs_percentile) * 2   # +60 à +100
            else:
                # Zone normale
                score = (50 - specs_percentile)       # -30 à +30
            
            # Ajustement par Commercials (smart money)
            # Si commercials sont net long → Bullish (ils hedgent production)
            comm_net = cot_data.commercials_net
            if comm_net > 0:  # Commercials long
                score += 20
            elif comm_net < 0:  # Commercials short
                score -= 20
            
            # Limiter à [-100, 100]
            score = max(min(score, 100), -100)
            
            return score
            
        except Exception as e:
            logger.error(f"📊 Erreur COT analysis {symbol}: {e}")
            return 0.0
    
    def _fetch_from_cftc(self) -> Optional[pd.DataFrame]:
        """Télécharge et cache le rapport CFTC global."""
        import requests
        import io
        
        # Si cache valide (< 24h), l'utiliser
        if self._df_cache is not None and self._df_cache_time:
            if datetime.now() - self._df_cache_time < timedelta(hours=24):
                return self._df_cache

        try:
            logger.info("📊 Téléchargement données CFTC (Legacy Futures)...")
            # URL officielle CFTC "Legacy Futures Only" 
            url = "https://www.cftc.gov/dea/newcot/deafut.txt"
            
            # Utiliser requests avec verify=False pour éviter les erreurs SSL sur Windows
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except:
                pass
                
            response = requests.get(url, verify=False, timeout=10)
            response.raise_for_status()
            
            # On ne fournit pas de noms de colonnes ici pour laisser pandas gérer le nombre de colonnes
            # On utilisera les indices numériques
            df = pd.read_csv(io.BytesIO(response.content), header=None, low_memory=False)
            
            # Nettoyer les noms de marché (Col 0)
            df[0] = df[0].astype(str).str.strip()
            
            self._df_cache = df
            self._df_cache_time = datetime.now()
            logger.info(f"📊 Données CFTC téléchargées: {len(df)} entrées")
            
            return df
            
        except Exception as e:
            logger.error(f"📊 Erreur téléchargement CFTC: {e}")
            return None

    def _fetch_latest_cot(self, symbol: str) -> Optional[COTData]:
        """
        Récupère les dernières données COT pour un symbole.
        Indices basés sur le format 'Legacy Futures Only' :
        0: Market Name
        2: Date (YYYY-MM-DD)
        7: Open Interest
        8: Non-Commercial Long (Large Specs)
        9: Non-Commercial Short
        11: Commercial Long
        12: Commercial Short
        """
        cftc_name = self.SYMBOL_TO_CFTC.get(symbol)
        if not cftc_name:
            return None
            
        df = self._fetch_from_cftc()
        if df is None:
            return None
            
        try:
            # Filtrer pour le marché spécifique
            # On cherche cftc_name (ex: "EURO FX") dans la colonne 0
            row = df[df[0].str.contains(cftc_name, case=False, na=False)]
            
            if row.empty:
                logger.warning(f"📊 Pas de données CFTC pour {cftc_name}")
                return None
                
            # Prendre la ligne la plus récente
            latest = row.iloc[0]
            
            # Extraire les valeurs par indices
            non_comm_long = int(latest[8])
            non_comm_short = int(latest[9])
            comm_long = int(latest[11])
            comm_short = int(latest[12])
            
            date_val = latest[2]
            try:
                report_date = datetime.strptime(str(date_val).strip(), "%Y-%m-%d")
            except:
                report_date = datetime.now()
            
            # Calcul des nets
            specs_net = non_comm_long - non_comm_short
            comm_net = comm_long - comm_short
            
            # Pour le percentile, on simule une valeur si pas d'historique
            # TODO: Implémenter le chargement de l'historique annuel (annual.txt)
            
            return COTData(
                symbol=symbol,
                date=report_date,
                large_specs_long=non_comm_long,
                large_specs_short=non_comm_short,
                commercials_long=comm_long,
                commercials_short=comm_short,
                large_specs_net=specs_net,
                commercials_net=comm_net,
                large_specs_net_percentile=50.0, # Neutre par défaut
                extreme_level="NORMAL"
            )

        except Exception as e:
            logger.error(f"📊 Erreur parsing COT pour {symbol}: {e}")
            return None
    
    def _calculate_percentile(self, current_net: int, 
                             historical_nets: List[int]) -> float:
        """
        Calcule le percentile du positionnement actuel vs historique.
        
        Args:
            current_net: Position nette actuelle
            historical_nets: Liste des positions historiques
        
        Returns:
            Percentile 0-100
        """
        if not historical_nets:
            return 50.0  # Neutre par défaut
        
        # Nombre de valeurs historiques inférieures
        count_below = sum(1 for val in historical_nets if val < current_net)
        percentile = (count_below / len(historical_nets)) * 100
        
        return percentile
    
    def _classify_extreme(self, percentile: float) -> str:
        """
        Classifie le niveau d'extrême selon le percentile.
        
        Args:
            percentile: Percentile 0-100
        
        Returns:
            "EXTREME_LONG", "EXTREME_SHORT", ou "NORMAL"
        """
        # Utiliser le seuil configuré (ex: 2σ ≈ 97.5%ile et 2.5%ile)
        extreme_high = 100 - (100 * (1 - 0.9773))  # ~97.7%
        extreme_low = 100 * (1 - 0.9773)            # ~2.3%
        
        if percentile > extreme_high:
            return "EXTREME_LONG"
        elif percentile < extreme_low:
            return "EXTREME_SHORT"
        else:
            return "NORMAL"
    
    def get_bias(self, symbol: str) -> str:
        """
        Retourne le biais COT simplifié.
        
        Args:
            symbol: Symbole
        
        Returns:
            "BULLISH", "BEARISH", ou "NEUTRAL"
        """
        score = self.get_score(symbol)
        
        if score > 30:
            return "BULLISH"
        elif score < -30:
            return "BEARISH"
        else:
            return "NEUTRAL"
    
    def get_analysis_summary(self, symbol: str) -> Dict:
        """
        Retourne un résumé de l'analyse COT.
        
        Args:
            symbol: Symbole
        
        Returns:
            Dict avec score, bias, extreme_level, last_update
        """
        if not self.enabled:
            return {
                'score': 0.0,
                'bias': 'NEUTRAL',
                'extreme_level': 'NORMAL',
                'last_update': None,
                'available': False
            }
        
        cot_data = self._fetch_latest_cot(symbol)
        score = self.get_score(symbol)
        bias = self.get_bias(symbol)
        
        if cot_data:
            return {
                'score': score,
                'bias': bias,
                'extreme_level': cot_data.extreme_level,
                'last_update': cot_data.date,
                'specs_percentile': cot_data.large_specs_net_percentile,
                'available': True
            }
        else:
            return {
                'score': 0.0,
                'bias': 'NEUTRAL',
                'extreme_level': 'NORMAL',
                'last_update': None,
                'available': False
            }
    
    def is_at_extreme(self, symbol: str) -> bool:
        """
        Vérifie si le positionnement est à un extrême.
        
        Args:
            symbol: Symbole
        
        Returns:
            True si extrême détecté
        """
        cot_data = self._fetch_latest_cot(symbol)
        
        if not cot_data:
            return False
        
        return cot_data.extreme_level in ["EXTREME_LONG", "EXTREME_SHORT"]


# TODO: Fonction helper pour implémenter un fetcher CFTC simple
def fetch_cftc_report_example():
    """
    Exemple de fonction pour fetcher les reports CFTC.
    
    Étapes:
    1. Télécharger le fichier annual.txt depuis CFTC
       URL: https://www.cftc.gov/files/dea/history/deacot2021.zip
    
    2. Parser le fichier (format: comma-separated)
       Colonnes importantes:
       - Market_and_Exchange_Names
       - As_of_Date_In_Form_YYMMDD
       - NonComm_Positions_Long_All
       - NonComm_Positions_Short_All
       - Comm_Positions_Long_All
       - Comm_Positions_Short_All
    
    3. Filtrer par contract code (ex: "EURO FX - CHICAGO MERCANTILE EXCHANGE")
    
    4. Calculer nets et percentiles
    
    5. Retourner COTData
    """
    pass
