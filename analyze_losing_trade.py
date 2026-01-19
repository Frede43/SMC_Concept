"""
Script pour analyser LE trade qui a causé la perte de $33k
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
import json

ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

# Lire les résultats du backtest
results_file = ROOT_DIR / 'backtest' / 'results' / '2024' / 'fast_backtest_results.json'

with open(results_file, 'r') as f:
    results = json.load(f)

print("\n" + "="*70)
print("🔍 ANALYSE DU TRADE PERDANT")
print("="*70 + "\n")

print(f"📊 Résumé Global:")
print(f"  Total Trades: {results['summary']['total_trades']}")
print(f"  P&L Total: ${results['summary']['total_pnl']:,.2f}")
print(f"  Win Rate: {results['summary']['win_rate']:.2f}%")

if results['summary']['total_trades'] == 0:
    print("\n❌ Aucun trade n'a été exécuté!")
    print("   → Vérifier les conditions d'entrée (trop restrictives)")
else:
    print(f"\n⚠️ {results['summary']['total_trades']} trade(s) exécuté(s)")
    print(f"   → Perte de ${abs(results['summary']['total_pnl']):,.2f}")
    print(f"   → Sur capital initial de $10,000")
    print(f"   → Ratio: {abs(results['summary']['total_pnl'])/10000:.1f}x le capital")

print("\n" + "="*70)
print("\n💡 DIAGNOSTIC:")
print(f"   Le trade a perdu {abs(results['summary']['total_pnl'])/10000:.1f}x le capital initial.")
print(f"   Avec 1% de risque par trade, la perte DEVRAIT être ~$100.")
print(f"   Perte réelle: ${abs(results['summary']['total_pnl']):,.2f}")
print()
print("   → Le lot size était " + f"{abs(results['summary']['total_pnl'])/100:.0f}x trop élevé!")
print()
print("🔍 Prochaines étapes:")
print("   1. Activer logging WARNING temporairement")
print("   2. Re-run le backtest pour capturer le symbole du trade")
print("   3. Vérifier les valeurs de pip pour CE symbole spécifique")
print("   4. Ajuster RiskManager pour ce symbole")

print("\n" + "="*70 + "\n")
