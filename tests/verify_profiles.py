
import sys
import os
import yaml
from pathlib import Path

# Fix Windows Emoji output
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Ajouter le répertoire racine au path
sys.path.append(str(Path(os.getcwd())))

# Mock logger pour éviter les erreurs d'import
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="ERROR")

from strategy.smc_strategy import SMCStrategy

def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def test_profile_injection():
    print("🔍 DIAGNOSTIC PROFILS ACTIFS")
    print("============================")
    
    # 1. Charger la config
    try:
        config = load_config('config/settings.yaml')
        strategy = SMCStrategy(config)
    except Exception as e:
        print(f"Erreur init: {e}")
        return

    # 2. Test EURUSD (Forex)
    print("\n🧪 Test 1: EURUSDm (Forex Major)")
    sym_config = strategy.get_symbol_config('EURUSDm')
    smc_settings = sym_config.get('smc_settings', {})
    
    print(f"   Profil détecté: {sym_config.get('asset_class')}")
    print(f"   Paramètres injectés (SMC):")
    if 'liquidity' in smc_settings:
        print(f"   - Liquidity Lookback: {smc_settings['liquidity'].get('sweep_lookback')} (Standard: 20)")
    else:
        print("   - Pas de settings spécifiques (OK pour Forex si défaut)")
    
    # 3. Test BTCUSD (Crypto)
    print("\n🧪 Test 2: BTCUSDm (Crypto)")
    sym_config = strategy.get_symbol_config('BTCUSDm')
    smc_settings = sym_config.get('smc_settings', {})
    
    print(f"   Profil détecté: {sym_config.get('asset_class')}")
    print(f"   Paramètres injectés:")
    if 'liquidity' in smc_settings:
        print(f"   - Liquidity Lookback: {smc_settings['liquidity'].get('sweep_lookback')} (Crypto Target: 50)")
    if 'fvg' in smc_settings:
        print(f"   - FVG Min Pips: {smc_settings['fvg'].get('min_size_pips')} (Crypto Target: 50.0)")

    # 4. Test XAUUSD (Gold)
    print("\n🧪 Test 3: XAUUSDm (Commodity)")
    sym_config = strategy.get_symbol_config('XAUUSDm')
    smc_settings = sym_config.get('smc_settings', {})
    
    print(f"   Profil détecté: {sym_config.get('asset_class')}")
    print(f"   Paramètres injectés:")
    if 'liquidity' in smc_settings:
        print(f"   - Min Wick Ratio: {smc_settings['liquidity'].get('min_wick_ratio')} (Gold Target: 0.4)")

if __name__ == "__main__":
    try:
        test_profile_injection()
        print("\n✅ DIAGNOSTIC TERMINÉ")
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
