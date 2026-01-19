"""
MetaTrader 5 Connector
Connexion et interaction avec MetaTrader 5
"""

import MetaTrader5 as mt5
import pandas as pd
import os
from typing import Optional, Dict, List, Any
from datetime import datetime
from loguru import logger
from .order_manager import OrderManager

# ✅ FIX: Charger les variables d'environnement depuis .env avec chemin explicite
try:
    from dotenv import load_dotenv
    from pathlib import Path
    
    # Chercher .env dans le dossier parent de ce fichier (broker/) -> dossier racine
    env_path = Path(__file__).resolve().parent.parent / '.env'
    load_dotenv(dotenv_path=env_path)
    
    logger.debug(f"Tentative chargement .env depuis: {env_path}")
    logger.debug(f"MT5_LOGIN trouvé: {'OUI' if os.getenv('MT5_LOGIN') else 'NON'}")
    
except ImportError:
    logger.debug("python-dotenv non installé, utilisation des variables d'environnement système uniquement")


class MT5Connector:
    """
    Connecteur MetaTrader 5.
    
    Gère:
    - Connexion/Déconnexion
    - Récupération des données OHLC
    - Informations du compte
    - Informations des symboles
    
    Les credentials peuvent être définis via:
    1. Variables d'environnement (.env) - RECOMMANDÉ pour la sécurité
    2. Fichier config YAML (fallback)
    """
    
    TIMEFRAME_MAP = {
        'M1': mt5.TIMEFRAME_M1,
        'M5': mt5.TIMEFRAME_M5,
        'M15': mt5.TIMEFRAME_M15,
        'M30': mt5.TIMEFRAME_M30,
        'H1': mt5.TIMEFRAME_H1,
        'H4': mt5.TIMEFRAME_H4,
        'D1': mt5.TIMEFRAME_D1,
        'W1': mt5.TIMEFRAME_W1,
        'MN1': mt5.TIMEFRAME_MN1
    }
    
    def __init__(self, config: Dict[str, Any]):
        self.full_config = config
        self.config = config.get('mt5', {})
        self.connected = False
        self.account_info = None
        self.current_broker = None  # 'weekday' ou 'weekend'
        
        # ✅ FIX: Lire credentials depuis .env avec fallback sur config YAML
        self.env_login = os.getenv('MT5_LOGIN')
        self.env_password = os.getenv('MT5_PASSWORD')
        self.env_server = os.getenv('MT5_SERVER')
        self.env_path = os.getenv('MT5_PATH')
        
        if self.env_login:
            logger.info("🔒 Credentials MT5 chargés depuis variables d'environnement (.env)")
        else:
            logger.warning("⚠️ Credentials MT5 depuis config YAML - Considérez utiliser .env pour plus de sécurité")
        
        # Mode multi-broker
        self.multi_broker_mode = self.config.get('multi_broker_mode', 'auto')
        self.weekday_config = self.config.get('weekday', {})
        self.weekend_config = self.config.get('weekend', {})

        # Initialiser le gestionnaire d'ordres
        magic = self.config.get('magic_number', 123456)
        self.order_manager = OrderManager(magic_number=magic)
        
    # Liste des serveurs Exness à essayer
    EXNESS_SERVERS = [
        "Exness-MT5Trial9",
        "Exness-MT5Real9", 
        "Exness-MT5Trial",
        "Exness-MT5Real",
        "Exness-MT5Trial8",
        "Exness-MT5Real8",
        "Exness-MT5Trial7",
        "Exness-MT5Real7",
        "Exness-MT5",
    ]
    
    def _is_weekend(self) -> bool:
        """Vérifie si c'est le week-end."""
        from datetime import datetime, timedelta
        # UTC+2 pour le timezone de l'utilisateur
        tz_offset = self.config.get('timezone_offset', 2)
        utc_now = datetime.utcnow()
        local_time = utc_now + timedelta(hours=tz_offset)
        return local_time.weekday() in [5, 6]  # Samedi, Dimanche
    
    def _get_active_broker_config(self) -> dict:
        """Retourne la config du broker à utiliser selon le jour."""
        if self.multi_broker_mode == 'weekday':
            return self.weekday_config
        elif self.multi_broker_mode == 'weekend':
            return self.weekend_config
        else:  # auto
            if self._is_weekend():
                return self.weekend_config
            else:
                return self.weekday_config
    
    def get_active_symbols(self) -> list:
        """Retourne les symboles à trader selon le broker actif."""
        broker_config = self._get_active_broker_config()
        return broker_config.get('symbols', [])
    
    def connect(self, force_broker: str = None) -> bool:
        """
        Établit la connexion à MetaTrader 5.
        Support multi-broker: connecte au bon broker selon le jour.
        
        Args:
            force_broker: 'weekday' ou 'weekend' pour forcer un broker spécifique
        """
        # Déterminer quel broker utiliser
        if force_broker:
            broker_config = self.weekday_config if force_broker == 'weekday' else self.weekend_config
            self.current_broker = force_broker
        else:
            broker_config = self._get_active_broker_config()
            self.current_broker = 'weekend' if self._is_weekend() else 'weekday'
        
        broker_name = broker_config.get('name', 'Unknown')
        logger.info(f"Connecting to MetaTrader 5... ({broker_name})")
        logger.info(f"🔄 Mode: {self.multi_broker_mode.upper()} | Broker actif: {self.current_broker.upper()}")
        
        # Fermer toute connexion existante
        mt5.shutdown()
        
        # Initialiser MT5 avec le path du broker actif
        path = broker_config.get('path', self.config.get('path'))
        max_attempts = 3
        
        for attempt in range(max_attempts):
            if path:
                success = mt5.initialize(path=path)
            else:
                success = mt5.initialize()
            
            if success:
                break
            else:
                error = mt5.last_error()
                logger.warning(f"Tentative {attempt + 1}/{max_attempts}: {error}")
                if attempt < max_attempts - 1:
                    import time
                    time.sleep(2)
        
        if not success:
            logger.error(f"MT5 initialize failed après {max_attempts} tentatives")
            logger.error(f"⚠️  Assurez-vous que {broker_name} est OUVERT!")
            return False
        
        # Vérifier si déjà connecté au bon compte
        account = mt5.account_info()
        expected_login = broker_config.get('login')
        
        if account and account.login == expected_login:
            logger.info(f"Utilisation de la connexion MT5 existante")
            logger.info(f"Compte: {account.login} | Serveur: {account.server}")
            self.connected = True
            self.account_info = account
            logger.info(f"Balance: ${account.balance:.2f}")
            return True
        
        # ✅ FIX: Priorité aux credentials .env puis fallback sur config YAML
        login = self.env_login or broker_config.get('login', self.config.get('login'))
        password = self.env_password or broker_config.get('password', self.config.get('password'))
        server = self.env_server or broker_config.get('server', self.config.get('server'))
        
        # 🔧 Résoudre les variables non remplacées (format ${VAR})
        def resolve_env_var(value, name="valeur"):
            if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
                var_name = value[2:-1]
                env_val = os.getenv(var_name)
                if env_val:
                    return env_val
                logger.error(f"❌ Variable d'environnement manquante: {var_name}")
                logger.error(f"   Veuillez définir {var_name} dans votre fichier .env")
                return None # Retourne None pour forcer l'erreur explicite plus bas
            return value

        login = resolve_env_var(login, "Login")
        password = resolve_env_var(password, "Password")
        server = resolve_env_var(server, "Server")
        
        if not login or not password:
            logger.error(f"❌ Credentials MT5 invalides ou incomplets.")
            logger.error(f"   Login reçu: {login}")
            mt5.shutdown()
            return False
        
        # Essayer le serveur configuré d'abord
        servers_to_try = []
        if server:
            servers_to_try.append(server)
        servers_to_try.extend([s for s in self.EXNESS_SERVERS if s != server])
        
        for srv in servers_to_try:
            logger.info(f"Tentative de connexion au serveur: {srv}")
            authorized = mt5.login(
                login=int(login),
                password=password,
                server=srv
            )
            
            if authorized:
                logger.info(f"✅ Connecté au serveur {srv}")
                self.connected = True
                self.account_info = mt5.account_info()
                logger.info(f"Balance: ${self.account_info.balance:.2f}" if self.account_info else "")
                return True
            else:
                logger.debug(f"Échec sur {srv}: {mt5.last_error()}")
        
        logger.error("Impossible de se connecter à MT5")
        logger.error("Solutions:")
        logger.error("1. Ouvrez MT5 et connectez-vous manuellement")
        logger.error("2. Vérifiez vos credentials")
        mt5.shutdown()
        return False
    
    def disconnect(self) -> None:
        """Ferme la connexion MT5."""
        if self.connected:
            mt5.shutdown()
            self.connected = False
            logger.info("Disconnected from MT5")
    
    def get_ohlc(self, symbol: str, timeframe: str, count: int = 500, max_retries: int = 3) -> Optional[pd.DataFrame]:
        """
        Récupère les données OHLC avec retry automatique.
        
        Args:
            symbol: Symbole (ex: "EURUSD")
            timeframe: Timeframe (ex: "H1", "M15")
            count: Nombre de bougies
            max_retries: Nombre de tentatives maximum
            
        Returns:
            DataFrame avec colonnes: open, high, low, close, volume
        """
        import time
        
        for attempt in range(max_retries):
            # ✅ FIX: Vérifier et tenter reconnexion si nécessaire
            if not self.connected:
                logger.warning(f"MT5 déconnecté, tentative de reconnexion... ({attempt + 1}/{max_retries})")
                if not self.connect():
                    time.sleep(2 ** attempt)  # Backoff exponentiel
                    continue
            
            tf = self.TIMEFRAME_MAP.get(timeframe.upper())
            if tf is None:
                logger.error(f"Invalid timeframe: {timeframe}")
                return None
            
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
            
            if rates is not None and len(rates) > 0:
                # Succès!
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s')
                df.set_index('time', inplace=True)
                df = df.rename(columns={
                    'tick_volume': 'volume'
                })
                return df[['open', 'high', 'low', 'close', 'volume']]
            
            # Échec - analyser l'erreur
            error = mt5.last_error()
            error_code = error[0] if error else 0
            
            # Codes d'erreur réseau qui justifient une reconnexion
            network_errors = [10006, 10014, 10015, 10018, 10019]  # ERR_xxx network related
            
            if error_code in network_errors or "network" in str(error).lower():
                logger.warning(f"Erreur réseau MT5 détectée, reconnexion... ({attempt + 1}/{max_retries})")
                self.connected = False
                time.sleep(2 ** attempt)
            else:
                logger.error(f"Failed to get rates for {symbol}: {error}")
                if attempt < max_retries - 1:
                    time.sleep(1)
        
        logger.error(f"Impossible de récupérer les données pour {symbol} après {max_retries} tentatives")
        return None
    
    def get_current_price(self, symbol: str) -> Optional[Dict[str, float]]:
        """Récupère le prix actuel (bid/ask)."""
        if not self.connected:
            return None
        
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        
        return {
            'bid': tick.bid,
            'ask': tick.ask,
            'spread': (tick.ask - tick.bid) / self._get_pip_value(symbol)
        }
    
    def _get_pip_value(self, symbol: str) -> float:
        """Retourne la valeur d'un pip basée sur les données MT5 réelles."""
        info = mt5.symbol_info(symbol)
        if info:
            # Un pip est généralement 10 * point pour forex, ou point pour autres
            if info.digits == 5 or info.digits == 3:
                return info.point * 10  # Forex standard (5 décimales = pip à 4ème)
            else:
                return info.point  # Autres (gold, indices, etc.)
        
        # Fallback si pas d'info
        if "JPY" in symbol:
            return 0.01
        elif "XAU" in symbol:
            return 0.01  # XAUUSD typiquement coté à 2 décimales
        return 0.0001
    
    def get_account_info(self) -> Optional[Dict]:
        """Récupère les informations du compte."""
        if not self.connected:
            return None
        
        info = mt5.account_info()
        if info is None:
            return None
        
        return {
            'login': info.login,
            'balance': info.balance,
            'equity': info.equity,
            'margin': info.margin,
            'free_margin': info.margin_free,
            'margin_level': info.margin_level,
            'profit': info.profit,
            'leverage': info.leverage,
            'currency': info.currency,
            'trade_allowed': info.trade_allowed,
            'trade_expert': info.trade_expert,
            'trade_mode': info.trade_mode
        }
    
    def ensure_symbol_visible(self, symbol: str) -> bool:
        """
        S'assure que le symbole est visible dans le Market Watch.
        Essentiel pour récupérer les ticks en temps réel.
        """
        if not self.connected:
            return False
            
        selected = mt5.symbol_select(symbol, True)
        if not selected:
            logger.error(f"❌ Impossible d'ajouter {symbol} au Market Watch")
            return False
            
        return True

    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """
        Récupère les informations COMPLÈTES d'un symbole depuis MT5.
        Données 100% dynamiques et réelles.
        """
        if not self.connected:
            return None
        
        info = mt5.symbol_info(symbol)
        if info is None:
            logger.warning(f"Impossible de récupérer les infos pour {symbol}")
            return None
        
        # Calculer pip value dynamiquement
        if info.digits == 5 or info.digits == 3:
            pip_size = info.point * 10  # Forex: pip = 10 points
            pips_in_price = 4 if info.digits == 5 else 2
        else:
            pip_size = info.point
            pips_in_price = info.digits
        
        # Valeur d'un pip pour 1 lot standard
        # tick_value = valeur de 1 tick (point) pour 1 lot
        if info.digits == 5 or info.digits == 3:
            pip_value_per_lot = info.trade_tick_value * 10  # 10 points = 1 pip
        else:
            pip_value_per_lot = info.trade_tick_value
        
        symbol_data = {
            'name': info.name,
            'description': info.description,
            # Pricing
            'bid': info.bid,
            'ask': info.ask,
            'spread': info.spread,
            'spread_float': info.spread_float,
            # Précision
            'digits': info.digits,
            'point': info.point,
            'pip_size': pip_size,
            # Volumes
            'volume_min': info.volume_min,
            'volume_max': info.volume_max,
            'volume_step': info.volume_step,
            # Contract
            'contract_size': info.trade_contract_size,
            'tick_size': info.trade_tick_size,
            'tick_value': info.trade_tick_value,
            'pip_value_per_lot': pip_value_per_lot,
            # Trading
            'trade_mode': info.trade_mode,
            'trade_allowed': info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL,
            # Stops
            'stops_level': info.trade_stops_level,  # Distance min pour SL/TP en points
            'freeze_level': info.trade_freeze_level,  # Distance freeze
            # Margin
            'margin_initial': info.margin_initial,
            'margin_maintenance': info.margin_maintenance,
        }
        
        logger.debug(f"📊 {symbol}: pip_size={pip_size}, pip_value/lot=${pip_value_per_lot:.4f}, "
                    f"digits={info.digits}, contract={info.trade_contract_size}")
        
        return symbol_data
    
    def get_dynamic_pip_info(self, symbol: str) -> Dict:
        """
        Récupère les informations de pip dynamiques pour le calcul de position.
        
        Returns:
            Dict avec pip_size, pip_value_per_lot, min_sl_pips
        """
        info = self.get_symbol_info(symbol)
        if info is None:
            # Fallback values
            logger.warning(f"Utilisation des valeurs fallback pour {symbol}")
            if "XAU" in symbol:
                return {'pip_size': 0.01, 'pip_value_per_lot': 1.0, 'min_sl_pips': 50, 'max_lots': 0.5}
            elif "JPY" in symbol:
                return {'pip_size': 0.01, 'pip_value_per_lot': 10.0, 'min_sl_pips': 20, 'max_lots': 1.0}
            else:
                return {'pip_size': 0.0001, 'pip_value_per_lot': 10.0, 'min_sl_pips': 15, 'max_lots': 1.0}
        
        # Calculer min SL en pips basé sur stops_level de MT5
        stops_level_pips = info['stops_level'] / 10 if info['digits'] in [5, 3] else info['stops_level']
        min_sl_pips = max(10, stops_level_pips + 5)  # Au moins stops_level + 5 pips
        
        # Max lots basé sur le symbole
        if "XAU" in symbol:
            max_lots = min(0.5, info['volume_max'])
        else:
            max_lots = min(1.0, info['volume_max'])
        
        return {
            'pip_size': info['pip_size'],
            'pip_value_per_lot': info['pip_value_per_lot'],
            'min_sl_pips': min_sl_pips,
            'max_lots': max_lots,
            'volume_min': info['volume_min'],
            'volume_step': info['volume_step'],
            'contract_size': info['contract_size'],
            'stops_level': info['stops_level'],
            'digits': info['digits']
        }
    
    def get_positions(self, symbol: str = None) -> List[Dict]:
        """Récupère les positions ouvertes."""
        if not self.connected:
            return []
        
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()
        
        if positions is None:
            return []
        
        return [
            {
                'ticket': p.ticket,
                'symbol': p.symbol,
                'type': 'BUY' if p.type == mt5.ORDER_TYPE_BUY else 'SELL',
                'volume': p.volume,
                'price_open': p.price_open,
                'sl': p.sl,
                'tp': p.tp,
                'profit': p.profit,
                'time': datetime.fromtimestamp(p.time)
            }
            for p in positions
        ]
    
    def get_pending_orders(self, symbol: str = None) -> List[Dict]:
        """Récupère les ordres en attente."""
        if not self.connected:
            return []
        
        if symbol:
            orders = mt5.orders_get(symbol=symbol)
        else:
            orders = mt5.orders_get()
        
        if orders is None:
            return []
        
        return [
            {
                'ticket': o.ticket,
                'symbol': o.symbol,
                'type': o.type,
                'volume': o.volume_initial,
                'price': o.price_open,
                'sl': o.sl,
                'tp': o.tp,
                'time': datetime.fromtimestamp(o.time_setup)
            }
            for o in orders
        ]
    
    def is_market_open(self, symbol: str) -> bool:
        """Vérifie si le marché est ouvert."""
        if not self.connected:
            return False
        
        info = mt5.symbol_info(symbol)
        if info is None:
            return False
        
        return info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL

    def get_trade_history(self, ticket: int) -> pd.DataFrame:
        """Récupère l'historique des deals pour un ticket spécifique."""
        if not self.connected:
            return pd.DataFrame()
            
        # Chercher les deals associés à ce ticket de position
        from_date = datetime.now() - pd.Timedelta(days=2) # Look back 2 days
        to_date = datetime.now() + pd.Timedelta(days=1)
        
        deals = mt5.history_deals_get(from_date, to_date, position=ticket)
        if deals is None or len(deals) == 0:
            return pd.DataFrame()
            
        df = pd.DataFrame(list(deals), columns=deals[0]._asdict().keys())
        return df

