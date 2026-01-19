"""
SCRIPT DE VALIDATION - Corrections Critiques Bot 300$

Ce script teste les corrections du bug money management
pour s'assurer qu'aucun lot_size dangereux ne peut être calcule.

Auteur: Expert SMC/ICT
Date: 19 Janvier 2026
"""

# -*- coding: utf-8 -*-
import sys
import os

# Fix encoding pour Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.risk_management import RiskManager
from loguru import logger

def test_position_sizing():
    """Teste le calcul de position size pour tous les scénarios critiques."""
    
    print("=" * 70)
    print("🛡️ TEST DE VALIDATION - CORRECTIONS MONEY MANAGEMENT")
    print("=" * 70)
    print()
    
    # Configuration minimale
    config = {
        'risk': {
            'risk_per_trade': 0.20,
            'max_lots_forex': 10.0,
            'max_lots_xauusd': 50.0,
            'use_fixed_lot': False,
            'max_daily_loss': 0.60
        }
    }
    
    rm = RiskManager(config)
    
    # Scénarios de test
    test_cases = [
        # Format: (account_balance, entry_price, stop_loss, symbol, expected_max_lot, description)
        (300, 1.2500, 1.2450, "EURUSDm", 0.10, "EUR/USD - Compte 300$ (protection petit compte)"),
        (300, 1.2500, 1.2450, "GBPUSDm", 0.10, "GBP/USD - Compte 300$ (protection petit compte)"),
        (300, 30000, 29500, "BTCUSDm", 0.05, "BTC/USD - Compte 300$ (protection crypto)"),
        (300, 2000, 1990, "XAUUSDm", 0.10, "XAU/USD - Compte 300$ (protection petit compte)"),
        (300, 35000, 34500, "US30m", 0.10, "US30 - Compte 300$ (protection indices)"),
        (300, 15000, 14800, "USTECm", 0.10, "USTEC - Compte 300$ (protection indices)"),
        
        (500, 1.2500, 1.2450, "EURUSDm", 0.10, "EUR/USD - Compte 500$ (toujours protection)"),
        (1000, 1.2500, 1.2450, "EURUSDm", 10.0, "EUR/USD - Compte 1000$ (normal)"),
        (1500, 30000, 29500, "BTCUSDm", 0.05, "BTC/USD - Compte 1500$ (toujours cap crypto)"),
    ]
    
    all_passed = True
    failures = []
    
    for i, (balance, entry, sl, symbol, max_lot, desc) in enumerate(test_cases, 1):
        print(f"\n{'─' * 70}")
        print(f"TEST {i}/{len(test_cases)}: {desc}")
        print(f"{'─' * 70}")
        print(f"  Capital: ${balance:.2f}")
        print(f"  Symbole: {symbol}")
        print(f"  Entry: {entry}, SL: {sl} (Distance: {abs(entry-sl):.1f})")
        
        try:
            pos = rm.calculate_position_size(
                account_balance=balance,
                entry_price=entry,
                stop_loss=sl,
                symbol=symbol
            )
            
            print(f"  📊 Résultat:")
            print(f"     Lot Size: {pos.lot_size:.4f}")
            print(f"     Risk Amount: ${pos.risk_amount:.2f}")
            print(f"     SL Pips: {pos.stop_loss_pips:.2f}")
            print(f"     Pip Value: {pos.pip_value}")
            
            # Validation
            if pos.lot_size > max_lot:
                print(f"  ❌ ÉCHEC: Lot size {pos.lot_size} > maximum {max_lot}")
                all_passed = False
                failures.append((desc, pos.lot_size, max_lot))
            elif pos.lot_size > 1.0:
                print(f"  🚨 CRITIQUE: Lot size {pos.lot_size} > ABSOLUTE MAX 1.0!")
                all_passed = False
                failures.append((desc, pos.lot_size, 1.0))
            elif pos.lot_size <= 0 or pos.lot_size != pos.lot_size:  # NaN check
                print(f"  ❌ ÉCHEC: Lot size invalide (0 ou NaN)")
                all_passed = False
                failures.append((desc, pos.lot_size, "Valid number"))
            else:
                print(f"  ✅ SUCCÈS: Lot size dans limites sécuritaires")
                
        except Exception as e:
            print(f"  🚨 ERREUR EXCEPTION: {e}")
            all_passed = False
            failures.append((desc, "EXCEPTION", str(e)))
    
    # Résumé final
    print("\n" + "=" * 70)
    print("📊 RÉSUMÉ DES TESTS")
    print("=" * 70)
    print(f"Total tests: {len(test_cases)}")
    print(f"Réussis: {len(test_cases) - len(failures)}")
    print(f"Échecs: {len(failures)}")
    
    if all_passed:
        print("\n✅ ✅ ✅ TOUS LES TESTS RÉUSSIS ✅ ✅ ✅")
        print("\n🎉 CORRECTIONS VALIDÉES!")
        print("🛡️ Protection bug liquidation: ACTIVE")
        print("🛡️ Hard caps en place:")
        print("   - Petit compte (<1000$): 0.10 lot max")
        print("   - Crypto (BTC/ETH): 0.05 lot max")
        print("   - Indices (US30/USTEC): 0.10 lot max")
        print("   - Absolu global: 1.0 lot max")
        print("\n✅ Bot prêt pour paper trading (mode DEMO)")
        print("⚠️ NE PAS utiliser en mode LIVE avant validation paper trading")
        return True
    else:
        print("\n❌ ❌ ❌ DES TESTS ONT ÉCHOUÉ ❌ ❌ ❌")
        print("\n🚨 ÉCHECS DÉTAILLÉS:")
        for desc, actual, expected in failures:
            print(f"   - {desc}")
            print(f"     Obtenu: {actual}, Attendu: ≤ {expected}")
        print("\n⚠️ CORRECTIONS NÉCESSAIRES AVANT UTILISATION")
        return False

def test_edge_cases():
    """Teste les cas limites et situations extrêmes."""
    
    print("\n" + "=" * 70)
    print("🔬 TESTS CAS LIMITES")
    print("=" * 70)
    
    config = {'risk': {'risk_per_trade': 0.20, 'max_lots_forex': 10.0}}
    rm = RiskManager(config)
    
    edge_cases = [
        (0, 1.2500, 1.2450, "EURUSDm", "Balance zéro"),
        (-100, 1.2500, 1.2450, "EURUSDm", "Balance négative"),
        (300, 1.2500, 1.2500, "EURUSDm", "SL = Entry (SL zero)"),
        (300, 0, 0, "EURUSDm", "Prix invalides"),
    ]
    
    print("\nTesting edge cases pour robustesse...")
    for balance, entry, sl, symbol, desc in edge_cases:
        print(f"\n  Test: {desc}")
        try:
            pos = rm.calculate_position_size(balance, entry, sl, symbol)
            if pos.lot_size >= 0.01 and pos.lot_size <= 0.10:
                print(f"    ✅ Géré correctement: lot_size = {pos.lot_size:.4f}")
            else:
                print(f"    ⚠️ Lot size inhabituel: {pos.lot_size}")
        except Exception as e:
            print(f"    ⚠️ Exception (attendu dans certains cas): {e}")
    
    print("\n✅ Tests edge cases complétés")

if __name__ == "__main__":
    print("\n🚀 DÉMARRAGE VALIDATION CORRECTIONS CRITIQUES\n")
    
    # Test 1: Position sizing normal
    success = test_position_sizing()
    
    # Test 2: Edge cases
    test_edge_cases()
    
    print("\n" + "=" * 70)
    if success:
        print("✅ VALIDATION COMPLÈTE: SUCCÈS")
        print("=" * 70)
        print("\n📋 PROCHAINES ÉTAPES:")
        print("  1. ✅ Corrections appliquées et validées")
        print("  2. ⏭️ Lancer paper trading: python main.py --mode demo")
        print("  3. 📊 Tracker résultats pendant 4 semaines")
        print("  4. ✅ Si Win Rate > 50% → Déploiement progressif")
        print("\n⚠️ NE PAS connecter compte RÉEL avant fin paper trading")
        exit(0)
    else:
        print("❌ VALIDATION COMPLÈTE: ÉCHEC")
        print("=" * 70)
        print("\n⚠️ ACTIONS REQUISES:")
        print("  1. Vérifier corrections dans strategy/risk_management.py")
        print("  2. Relancer ce script de validation")
        print("  3. Contacter support si problème persiste")
        exit(1)
