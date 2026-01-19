
import sys
import os

# Ajouter la racine au path pour les imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass
from loguru import logger

# --- MOCKING (SIMULATION) ---
@dataclass
class MockContext:
    composite_score: float
    macro_bias: str
    has_critical_news: bool = False
    block_threshold: float = -30.0 # Nouveau seuil strict

def simulate_new_logic(direction: str, context: MockContext):
    """
    Simule exactement la nouvelle logique insérée dans smc_strategy.py
    """
    print(f"\n🧪 TEST SCENARIO: Tentative de {direction} avec Macro {context.macro_bias} (Score: {context.composite_score})")
    print("-" * 60)
    
    # 1. Logique originale (FundamentalFilter.should_block_trade)
    # Simulation simplifiée de la règle de seuil
    should_block = False
    block_reason = ""
    
    # Règle seuil standard (settings.yaml)
    if abs(context.composite_score) > abs(context.block_threshold):
        # Vérifier si divergence
        is_buy = direction == "BUY"
        is_macro_bullish = context.macro_bias == "BULLISH"
        if is_buy != is_macro_bullish and context.macro_bias != "NEUTRAL":
            should_block = True
            block_reason = f"❌ Divergence standard > {context.block_threshold}"

    print(f"1. Filtre Standard (Ancien): {'🚫 BLOQUÉ' if should_block else '✅ PASSE'} | {block_reason}")

    # 2. 🛑 NOUVELLE LOGIQUE (HARD VETO)
    # Celle que nous venons d'ajouter
    if not should_block:
        is_buy = direction == "BUY"
        macro_bearish = context.macro_bias == "BEARISH"
        macro_bullish = context.macro_bias == "BULLISH"
        
        if (is_buy and macro_bearish) or (not is_buy and macro_bullish):
                should_block = True
                block_reason = f"❌ HARD VETO: Trade {direction} vs Macro {context.macro_bias} (Score: {context.composite_score:.1f})"
                print(f"2. 🛡️ PROTECTION MACRO (Nouveau): ACTIVÉE -> {block_reason}")
    else:
        print("2. 🛡️ PROTECTION MACRO: Pas nécessaire (déjà bloqué)")

    return should_block, block_reason

def main():
    # CAS RÉEL DU TRADE PERDANT GBPUSD
    # Ticket #2168264777
    # Signal: BUY
    # Conflit Intermarket: -35.3%
    # Biais déduit: BEARISH (car score negatif et DXY Bullish)
    
    print("🔍 AUTOPSIE DU TRADE GBPUSD #2168264777")
    print("========================================")
    
    gbp_context = MockContext(
        composite_score = -35.3, 
        macro_bias = "BEARISH",
        block_threshold = -30.0 # Seuil durci dans settings
    )
    
    blocked, reason = simulate_new_logic("BUY", gbp_context)
    
    print("\n📝 RÉSULTAT FINAL:")
    if blocked:
        print(f"✅ SUCCÈS: Le trade aurait été SAUVÉ (BLOQUÉ).")
        print(f"   Raison: {reason}")
    else:
        print(f"❌ ÉCHEC: Le trade serait passé.")

    # CAS TEST 2: Trade EURUSD "Borderline"
    # Signal: BUY
    # Score: -15% (Neutre-Bearish mais pas extrême)
    # Biais: NEUTRAL
    print("\n\n🔍 CAS TEST: EURUSD BORDERLINE")
    print("========================================")
    eur_context = MockContext(
        composite_score = -15.0, 
        macro_bias = "NEUTRAL",  # Pas assez fort pour être Bearish
        block_threshold = -30.0
    )
    blocked, reason = simulate_new_logic("BUY", eur_context)
    
    if not blocked:
        print("✅ Comportement correct: Trade autorisé (Score faible, Biais Neutre)")
    else:
        print("❌ Comportement trop strict: Trade bloqué pour rien")

if __name__ == "__main__":
    main()
