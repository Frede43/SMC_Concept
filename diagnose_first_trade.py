"""
Script de diagnostic - Capture le PREMIER trade uniquement
Pour comprendre pourquoi le lot size est aberrant
"""

import sys
import os

# Fix encodage
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from pathlib import Path
from datetime import datetime
import yaml

ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from backtest.backtester import BacktestConfig, BacktestEngine

def diagnose_first_trade():
    """Lance le backtest et s'arrête au premier trade"""
    
    print("\n" + "="*70)
    print("🔍 DIAGNOSTIC - PREMIER TRADE UNIQUEMENT")
    print("="*70 + "\n")
    
    # Config
    config_path = ROOT_DIR / 'config' / 'settings.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # Backtest sur Décembre 2024
    data_dir = ROOT_DIR / 'backtest' / 'data'
    
    backtest_config = BacktestConfig(
        symbols=['GBPUSDm', 'EURUSDm', 'XAUUSDm', 'US30m'],
        start_date=datetime(2024, 12, 1),
        end_date=datetime(2024, 12, 31),
        initial_capital=10000.0,
        data_dir=data_dir
    )
    
    print("🔄 Lancement backtest...\n")
    
    engine = BacktestEngine(backtest_config, config.get('smc', {}))
    engine.data_manager.use_mt5 = False
    
    # Modifier le backtester pour s'arrêter après le premier trade
    original_open_trade = engine._open_trade
    
    first_trade_params = {}
    
    def capture_first_trade(symbol, entry_price, stop_loss, take_profit, lot_size, direction):
        """Capture les paramètres du premier trade et arrête"""
        first_trade_params['symbol'] = symbol
        first_trade_params['entry_price'] = entry_price
        first_trade_params['stop_loss'] = stop_loss
        first_trade_params['take_profit'] = take_profit
        first_trade_params['lot_size'] = lot_size
        first_trade_params['direction'] = direction
        
        # Appeler la fonction originale
        result = original_open_trade(symbol, entry_price, stop_loss, take_profit, lot_size, direction)
        
        if result:
            # Arrêter le backtest en levant une exception
            raise StopIteration("Premier trade capturé!")
        
        return result
    
    engine._open_trade = capture_first_trade
    
    try:
        results = engine.run()
    except StopIteration:
        print("\n" + "="*70)
        print("✅ PREMIER TRADE CAPTURÉ!")
        print("="*70 + "\n")
        
        if first_trade_params:
            print("📋 PARAMÈTRES DU TRADE:")
            for key, value in first_trade_params.items():
                if isinstance(value, float):
                    print(f"  {key:15s} = {value:,.5f}")
                else:
                    print(f"  {key:15s} = {value}")
            
            # Calculer ce que ÇA DEVRAIT être
            symbol = first_trade_params['symbol']
            entry = first_trade_params['entry_price']
            sl = first_trade_params['stop_loss']
            lot = first_trade_params['lot_size']
            
            print("\n🔍 ANALYSE:")
            
            # Recalculer avec les bonnes valeurs
            from strategy.risk_management import RiskManager
            rm = RiskManager(config)
            
            pos_size = rm.calculate_position_size(
                account_balance=10000.0,
                entry_price=entry,
                stop_loss=sl,
                symbol=symbol
            )
            
            print(f"\n  ✅ Lot calculé par RiskManager: {pos_size.lot_size:.4f}")
            print(f"  ❌ Lot reçu par Backtester:     {lot:.4f}")
            print(f"  📊 Pip Value (RM):              {pos_size.pip_value:.5f}")
            print(f"  📊 SL Pips:                     {pos_size.stop_loss_pips:.1f}")
            print(f"  💰 Risk Amount:                 ${pos_size.risk_amount:,.2f}")
            
            if abs(lot - pos_size.lot_size) > 0.01:
                print(f"\n  🚨 PROBLÈME DÉTECTÉ: Incohérence de {abs(lot - pos_size.lot_size):.4f} lots!")
        else:
            print("❌ Aucun trade n'a été ouvert pendant la période")
    
    print("\n" + "="*70 + "\n")

if __name__ == "__main__":
    diagnose_first_trade()
