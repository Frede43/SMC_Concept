"""
Spread Guard - Protection contre spreads excessifs

Vérifie le spread AVANT d'exécuter un trade pour éviter
les frais excessifs qui peuvent manger 30-40% du profit.

Author: Expert SMC/ICT
Date: 19 Janvier 2026
"""

from loguru import logger
from typing import Optional, Dict


class SpreadGuard:
    """Protège contre les trades avec spreads excessifs."""
    
    def __init__(self, config: dict = None):
        """
        Initialize spread guard.
        
        Args:
            config: Configuration avec:
                - max_spread_pips: Spread max autorisé par défaut (2.0)
                - symbol_specific: Dict spreads spécifiques par symbole
                - strict_mode: Si True, rejette systématiquement (True)
        """
        config = config or {}
        self.max_spread_pips = config.get('max_spread_pips', 2.0)
        self.symbol_specific = config.get('symbol_specific', {
            'EURUSD': 1.5,
            'GBPUSD': 2.0,
            'USDJPY': 1.8,
            'XAUUSD': 5.0,
            'BTCUSD': 50.0,
            'US30': 3.0,
            'USTEC': 5.0
        })
        self.strict_mode = config.get('strict_mode', True)
        
        logger.info(f"🛡️ SpreadGuard initialized: max_spread={self.max_spread_pips} pips")
    
    def check_spread(self, symbol: str, current_spread: float, mt5_api=None) -> Dict:
        """
        Vérifie si le spread est acceptable.
        
        Args:
            symbol: Symbole (ex: 'EURUSDm')
            current_spread: Spread actuel en pips
            mt5_api: API MT5 (optionnel, pour récupérer spread dynamique)
            
        Returns:
            {
                'allowed': bool,
                'spread': float,
                'max_allowed': float,
                'reason': str,
                'excess_pct': float  # % au-dessus du max
            }
        """
        # Récupérer spread depuis MT5 si API disponible
        if mt5_api and hasattr(mt5_api, 'get_spread'):
            try:
                actual_spread = mt5_api.get_spread(symbol)
                if actual_spread is not None:
                    current_spread = actual_spread
            except Exception as e:
                logger.warning(f"Could not get spread from MT5: {e}")
        
        # Déterminer max allowed pour ce symbole
        symbol_clean = symbol.replace('m', '').replace('.', '')
        max_allowed = self.symbol_specific.get(symbol_clean, self.max_spread_pips)
        
        # Calculer excès
        excess_pct = ((current_spread - max_allowed) / max_allowed * 100) if max_allowed > 0 else 0
        
        # Décision
        allowed = current_spread <= max_allowed
        
        result = {
            'allowed': allowed,
            'spread': current_spread,
            'max_allowed': max_allowed,
            'excess_pct': excess_pct,
            'reason': ''
        }
        
        if allowed:
            result['reason'] = f"Spread acceptable: {current_spread:.1f} pips ≤ {max_allowed:.1f}"
            logger.debug(f"✅ {result['reason']}")
        else:
            result['reason'] = f"Spread excessif: {current_spread:.1f} pips > {max_allowed:.1f} (+{excess_pct:.0f}%)"
            logger.warning(f"❌ {result['reason']}")
        
        return result
    
    def calculate_spread_cost(self, symbol: str, spread: float, lot_size: float) -> Dict:
        """
        Calcule le coût du spread pour un trade.
        
        Args:
            symbol: Symbole
            spread: Spread en pips
            lot_size: Taille position (ex: 0.01)
            
        Returns:
            {
                'cost_usd': float,
                'pct_of_risk': float  # Si risk 0.60$, spread 0.15$ = 25%
            }
        """
        # Valeur du pip par lot (approximation)
        pip_values = {
            'EURUSD': 10.0,
            'GBPUSD': 10.0,
            'USDJPY': 10.0,  # Approximation (varie selon taux)
            'XAUUSD': 1.0,
            'BTCUSD': 1.0,
            'US30': 1.0,
            'USTEC': 1.0
        }
        
        symbol_clean = symbol.replace('m', '').replace('.', '')
        pip_value_per_lot = pip_values.get(symbol_clean, 10.0)
        
        # Coût = spread × pip_value × lot_size
        cost_usd = spread * pip_value_per_lot * lot_size
        
        return {
            'cost_usd': cost_usd,
            'spread_pips': spread,
            'lot_size': lot_size
        }
    
    def get_optimal_entry_time(self, symbol: str) -> str:
        """
        Recommande meilleur moment pour minimiser spread.
        
        Returns:
            Suggestion de timing
        """
        suggestions = {
            'EURUSD': "London session (8h-11h GMT) ou NY session (13h-16h GMT)",
            'GBPUSD': "London session (8h-11h GMT)",
            'XAUUSD': "NY session (13h-17h GMT) - éviter Asian",
            'BTCUSD': "Éviter week-ends et heures creuses",
            'US30': "NY session (13h30-16h GMT)"
        }
        
        symbol_clean = symbol.replace('m', '').replace('.', '')
        return suggestions.get(symbol_clean, "Sessions London/NY pour spreads minimaux")


# Test
if __name__ == "__main__":
    print("=" * 70)
    print("TEST SPREAD GUARD")
    print("=" * 70)
    
    guard = SpreadGuard()
    
    # Test 1: Spread acceptable EURUSD
    print("\n1. Test EURUSD - Spread 1.2 pips (OK):")
    result1 = guard.check_spread('EURUSDm', 1.2)
    print(f"   Allowed: {result1['allowed']}")
    print(f"   Reason: {result1['reason']}")
    
    # Test 2: Spread excessif EURUSD
    print("\n2. Test EURUSD - Spread 3.5 pips (TROP ÉLEVÉ):")
    result2 = guard.check_spread('EURUSDm', 3.5)
    print(f"   Allowed: {result2['allowed']}")
    print(f"   Reason: {result2['reason']}")
    print(f"   Excès: +{result2['excess_pct']:.0f}%")
    
    # Test 3: Calcul coût
    print("\n3. Calcul coût spread - EURUSD 1.5 pips, 0.01 lot:")
    cost = guard.calculate_spread_cost('EURUSDm', 1.5, 0.01)
    print(f"   Coût: ${cost['cost_usd']:.2f}")
    print(f"   (Sur risk 0.60$ = {cost['cost_usd']/0.60*100:.1f}% du risque)")
    
    # Test 4: Timing optimal
    print("\n4. Timing optimal EURUSD:")
    timing = guard.get_optimal_entry_time('EURUSDm')
    print(f"   {timing}")
    
    print("\n" + "=" * 70)
    print("✅ Tests terminés")
