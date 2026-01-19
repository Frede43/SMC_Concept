"""
Helper Functions
Fonctions utilitaires diverses
"""

import yaml
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
import pytz


def load_config(config_path: str = "config/settings.yaml") -> Dict[str, Any]:
    """Charge la configuration depuis un fichier YAML."""
    path = Path(config_path)
    
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    return config


def pips_to_price(pips: float, symbol: str = "EURUSD") -> float:
    """Convertit des pips en différence de prix."""
    if "JPY" in symbol:
        return pips * 0.01
    elif "XAU" in symbol:
        return pips * 0.01
    return pips * 0.0001


def price_to_pips(price_diff: float, symbol: str = "EURUSD") -> float:
    """Convertit une différence de prix en pips."""
    if "JPY" in symbol:
        return price_diff / 0.01
    elif "XAU" in symbol:
        return price_diff / 0.01
    return price_diff / 0.0001


def format_price(price: float, symbol: str = "EURUSD") -> str:
    """Formate un prix selon le symbole."""
    if "JPY" in symbol:
        return f"{price:.3f}"
    elif "XAU" in symbol:
        return f"{price:.2f}"
    return f"{price:.5f}"


def get_server_time() -> datetime:
    """Retourne l'heure du serveur (UTC)."""
    return datetime.now(pytz.UTC)


def get_london_time() -> datetime:
    """Retourne l'heure de Londres."""
    return datetime.now(pytz.timezone('Europe/London'))


def get_new_york_time() -> datetime:
    """Retourne l'heure de New York."""
    return datetime.now(pytz.timezone('America/New_York'))


def is_weekend() -> bool:
    """Vérifie si c'est le weekend."""
    now = get_server_time()
    return now.weekday() >= 5


def calculate_lot_size(risk_amount: float, sl_pips: float, pip_value: float = 10.0) -> float:
    """
    Calcule la taille de lot.
    
    Args:
        risk_amount: Montant à risquer en $
        sl_pips: Distance du stop loss en pips
        pip_value: Valeur d'un pip pour 1 lot standard ($10 par défaut)
    """
    if sl_pips <= 0:
        return 0.01
    
    lot_size = risk_amount / (sl_pips * pip_value)
    return max(0.01, round(lot_size, 2))


def print_banner():
    """Affiche le banner ASCII du bot."""
    import sys
    import io
    
    # Forcer UTF-8 pour éviter les erreurs Unicode sur Windows
    try:
        if sys.stdout.encoding.lower() != 'utf-8':
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    except:
        pass

    banner = """
    =================================================================
          _   _ _ _   _                 _         ____  __  __  ____ 
         | | | | | | (_)_ __ ___   __ _| |_ ___  / ___||  \/  |/ ___|
         | | | | | | | | '_ ` _ \ / _` | __/ _ \ \___ \| |\/| | |    
         | |_| | | | | | | | | | | (_| | ||  __/  ___) | |  | | |___ 
          \___/|_|_| |_|_| |_| |_|\__,_|\__\___| |____/|_|  |_|\____|
                                                                     
                   SMC Trading Bot - Python Edition                  
    =================================================================
    """
    print(banner)
