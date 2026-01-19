"""
RUN MINI TEST
Lance un backtest très court pour générer des données de test rapidement
et peupler le dashboard.
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

# Ajouter le répertoire racine au path
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from loguru import logger
from backtest.backtester import BacktestConfig, BacktestEngine
from utils.session_tracker import get_session_tracker
import yaml

def run_mini_test():
    logger.info("🚀 Démarrage du MINI TEST (5 jours)...")
    
    # Charger la config
    with open("config/settings.yaml", 'r') as f:
        config = yaml.safe_load(f)
    
    # Configurer le backtest pour 20 jours
    end_date = datetime.now()
    start_date = end_date - timedelta(days=20)
    
    # Utiliser un seul symbole pour aller vite
    symbols = ['GBPUSDm']
    
    backtest_config = BacktestConfig(
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        initial_capital=10000.0,
        data_dir=ROOT_DIR / "backtest" / "data"
    )
    
    # Exécuter
    engine = BacktestEngine(backtest_config, config.get('smc', {}))
    results = engine.run()
    
    # Sauvegarder dans le tracker
    tracker = get_session_tracker()
    
    if results and 'trades' in results: # Note: 'trades' ajouté par mon patch précédent dans backtester.py
        logger.info(f"💾 Sauvegarde de {len(results['trades'])} trades...")
        for trade in results['trades']: # Utiliser closed_trades directement si results['trades'] n'est pas dispo
             tracker.record_trade({
                'ticket': 12345, # Dummy ticket
                'symbol': trade.symbol,
                'direction': trade.direction,
                'entry_time': trade.open_time,
                'exit_time': trade.close_time,
                'profit': trade.pnl,
                'strategy': 'backtest_mini'
            })
    
    logger.info("✅ Mini test terminé. Vérifiez le dashboard !")

if __name__ == "__main__":
    run_mini_test()
