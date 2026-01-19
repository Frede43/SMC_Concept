import os
import sys
import csv
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import MetaTrader5 as mt5
from loguru import logger
from dotenv import load_dotenv

# Load .env variables immediately
load_dotenv()

# Add project root to path to import utils
sys.path.insert(0, str(Path(__file__).parent))
from utils.helpers import load_config

# Configuration
DATA_DIR = Path("data")
CONFIG_PATH = "config/settings.yaml" # Helper expects string path
TIMEFRAMES = {
    'M15': mt5.TIMEFRAME_M15,
    'H1': mt5.TIMEFRAME_H1,
    'H4': mt5.TIMEFRAME_H4,
    'D1': mt5.TIMEFRAME_D1
}

# load_config is now imported from utils.helpers


def resolve_env_var(value):
    if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
        var_name = value[2:-1]
        return os.getenv(var_name, value)
    return value

def init_mt5(config):
    login_raw = config['mt5']['login']
    password_raw = config['mt5']['password']
    
    # Resolve env vars
    login = int(resolve_env_var(login_raw))
    password = resolve_env_var(password_raw)
    server = config['mt5']['server']
    path = config['mt5']['path']

    logger.info(f"Connecting to MT5 {server} as {login}...")
    if not mt5.initialize(path=path, login=login, password=password, server=server):
        logger.error(f"MT5 Init failed, error code = {mt5.last_error()}")
        return False
    return True

def download_symbol_data(symbol, timeframe_name, timeframe_val, days=365):
    """Télécharger les données et sauvegarder en CSV"""
    utc_to = datetime.now()
    utc_from = utc_to - timedelta(days=days)

    logger.info(f"Downloading {symbol} ({timeframe_name}) from {utc_from.date()} to {utc_to.date()}...")
    
    # S'assurer que le symbole est dispo ds MarketWatch
    if not mt5.symbol_select(symbol, True):
        logger.error(f"Symbol {symbol} not found or invalid.")
        return

    rates = mt5.copy_rates_range(symbol, timeframe_val, utc_from, utc_to)
    
    if rates is None or len(rates) == 0:
        logger.warning(f"No data for {symbol} {timeframe_name}")
        return

    # Convertir en DataFrame
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    # Ordonner et nettoyer
    df = df[['time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume']]
    df.rename(columns={'tick_volume': 'volume'}, inplace=True)

    # Sauvegarder CSV
    filename = DATA_DIR / f"{symbol}_{timeframe_name}.csv"
    df.to_csv(filename, index=False)
    logger.success(f"Saved {len(df)} rows to {filename}")

def main():
    logger.add("logs/data_download.log", rotation="10 MB")
    print("=== Exness-MT5 Data Downloader ===")
    
    DATA_DIR.mkdir(exist_ok=True)
    
    config = load_config(CONFIG_PATH)
    if not init_mt5(config):
        return

    # Récupérer les symboles activés dans la config
    symbols = [s['name'] for s in config['symbols'] if s.get('enabled', True)]
    
    # Télécharger (Par défaut 1 an de données)
    for symbol in symbols:
        print(f"\nProcessing {symbol}...")
        # On télécharge M15 (LTF) et D1 (HTF) principalement
        download_symbol_data(symbol, 'M15', TIMEFRAME_M15, days=365)
        download_symbol_data(symbol, 'H4', TIMEFRAME_H4, days=365)
        download_symbol_data(symbol, 'D1', TIMEFRAME_D1, days=365 * 2)

    mt5.shutdown()
    print("\n=== Download Complete ===")
    print(f"Files saved in: {DATA_DIR.absolute()}")

if __name__ == "__main__":
    from MetaTrader5 import *
    main()
