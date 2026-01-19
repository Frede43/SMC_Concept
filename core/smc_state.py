from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, List, Any
import pandas as pd
from loguru import logger

class SMCStage(Enum):
    NEUTRAL = "NEUTRAL"
    LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"      # Step 1: Liquidity taken (HTF or LTF)
    STRUCTURE_SHIFT = "STRUCTURE_SHIFT"      # Step 2: CHoCH observed after sweep
    ENTRY_READY = "ENTRY_READY"              # Step 3: Retracement to entry zone (OB/FVG)

@dataclass
class MarketState:
    stage: SMCStage = SMCStage.NEUTRAL
    
    # Sweep Details
    sweep_type: Optional[str] = None         # 'PDH', 'PDL', 'ASIAN_HIGH', 'ASIAN_LOW', etc.
    sweep_direction: Optional[str] = None    # 'BUY' (after sell-side sweep) or 'SELL' (after buy-side sweep)
    sweep_price: float = 0.0
    sweep_time: Optional[pd.Timestamp] = None
    
    # Structure Details
    choch_detected: bool = False
    choch_price: float = 0.0
    choch_time: Optional[pd.Timestamp] = None
    
    # Entry Validation
    valid_entry_zone: bool = False
    entry_zone_type: Optional[str] = None    # 'OB', 'FVG', 'OTE'
    
    last_update: Optional[pd.Timestamp] = None

class SMCStateMachine:
    """
    Gère la machine d'état séquentielle pour les setups SMC institutionnels.
    Séquence: Sweep -> Reaction -> CHoCH -> Entry
    """
    
    def __init__(self, expiration_bars: int = 50):
        self.states: Dict[str, MarketState] = {}
        self.expiration_bars = expiration_bars # Max bars to hold a state without progression
        self.bar_counts: Dict[str, int] = {}   # Track bars since last state change

    def get_state(self, symbol: str) -> MarketState:
        if symbol not in self.states:
            self.states[symbol] = MarketState()
            self.bar_counts[symbol] = 0
        return self.states[symbol]

    def reset_state(self, symbol: str, reason: str = ""):
        if symbol in self.states and self.states[symbol].stage != SMCStage.NEUTRAL:
            logger.info(f"[{symbol}] 🔄 SMC State Machine RESET ({reason})")
        self.states[symbol] = MarketState()
        self.bar_counts[symbol] = 0

    def update(self, symbol: str, current_price: float, analysis: Dict[str, Any]):
        """
        Met à jour l'état SMC en fonction des nouvelles analyses (Sweep, Structure, Zones).
        """
        state = self.get_state(symbol)
        
        # Increment validity counter
        self.bar_counts[symbol] += 1
        
        # Check Expiration (Timeout)
        if state.stage != SMCStage.NEUTRAL and self.bar_counts[symbol] > self.expiration_bars:
            self.reset_state(symbol, f"Timeout ({self.expiration_bars} bars)")
            state = self.get_state(symbol)

        # =========================================================================
        # TRANSITION LOGIC
        # =========================================================================

        # 1. NEUTRAL -> LIQUIDITY_SWEEP
        # On cherche un sweep (PDH, PDL, Asian, ou Swing High/Low majeur)
        if state.stage == SMCStage.NEUTRAL:
            sweep_found = False
            sweep_dir = None
            sweep_name = None
            
            # Check PDL/PDH Sweep from analysis
            pdl_data = analysis.get('pdl', {})
            # Correction: Trigger state immediately on Sweep Detection (Hunting Mode)
            # Do not wait for 'confirmed' bias yet.
            detected_sweep = pdl_data.get('sweep')
            if detected_sweep:
                sweep_found = True
                # Determine direction based on sweep type
                # Assuming detected_sweep is SweepEvent object
                stype = str(detected_sweep.sweep_type)
                if "PDH" in stype:
                    sweep_dir = "SELL" # PDH Sweep -> Look for SELL
                    sweep_name = "PDH_SWEEP"
                elif "PDL" in stype:
                    sweep_dir = "BUY" # PDL Sweep -> Look for BUY
                    sweep_name = "PDL_SWEEP"
            
            # Fallback to bias if no sweep object but bias exists (legacy check)
            if not sweep_found and (pdl_data.get('confirmed') or pdl_data.get('sweep')):
                bias = pdl_data.get('bias')
                if bias and bias != "NEUTRAL":
                    sweep_found = True
                    sweep_dir = bias 
                    sweep_name = "PDL_PDH_SWEEP"
            
            # Check Asian Sweep
            if not sweep_found:
                asian_data = analysis.get('asian_range', {})
                if asian_data.get('signal') and asian_data.get('signal') != "NEUTRAL":
                    sweep_found = True
                    sweep_dir = asian_data.get('signal')
                    sweep_name = "ASIAN_SWEEP"

            # Check Silver Bullet (often implies a sweep)
            if not sweep_found:
                sb_data = analysis.get('silver_bullet', {})
                if sb_data.get('status') == "ENTRY_READY" or "sweep" in str(sb_data.get('status','')).lower():
                     pass 

            # NOUVEAU: Check Generic Liquidity Sweeps (EQH/EQL/Swing Points)
            # "Liquidity Engine" Integration
            if not sweep_found:
                sweeps = analysis.get('sweeps', [])
                # Get latest confirmed sweep
                latest_sweep = None
                for s in reversed(sweeps):
                    if s.is_confirmed:
                        latest_sweep = s
                        break
                
                if latest_sweep:
                    # Filter: Only accept sweeps inside KILLZONE or if it's a major Swing
                    # Reading Killzone status (added in strategy)
                    kz_data = analysis.get('killzone', {})
                    is_killzone = kz_data.get('is_killzone', True) 
                    
                    if is_killzone:
                        sweep_found = True
                        # If SELL_SIDE swept (Low taken) -> We look for BUY
                        # If BUY_SIDE swept (High taken) -> We look for SELL
                        sweep_dir = "BUY" if latest_sweep.type.value == "sell_side" else "SELL"
                        sweep_name = "LIQUIDITY_GRAB_KZ"
                    else:
                        # Log ignored sweep outside killzone
                        # logger.debug(f"[{symbol}] Sweep ignored outside Killzone")
                        pass

            # Check Momentum Reversal (RSI Extreme)
            if not sweep_found:
                momentum_data = analysis.get('momentum', {})
                if momentum_data.get('is_extreme'):
                    sweep_found = True
                    sweep_dir = momentum_data.get('reversal_bias') # "BUY" if RSI < 30, "SELL" if RSI > 70
                    sweep_name = "MOMENTUM_CLIMAX"

            if sweep_found:
                state.stage = SMCStage.LIQUIDITY_SWEEP
                state.sweep_type = sweep_name
                state.sweep_direction = sweep_dir
                state.sweep_price = current_price
                state.sweep_time = pd.Timestamp.now()
                self.bar_counts[symbol] = 0 # Reset counter
                logger.info(f"[{symbol}] 🎯 SMC State Triggered: {state.sweep_type} ({state.sweep_direction}) -> Waiting for CHoCH")
        
        # 2. LIQUIDITY_SWEEP -> STRUCTURE_SHIFT (CHoCH)
        elif state.stage == SMCStage.LIQUIDITY_SWEEP:
            # On attend un CHoCH dans la direction du sweep (sweep_dir)
            # sweep_dir = 'BUY' signifie qu'on veut acheter, donc on cherche un CHoCH Bullish
            
            structure = analysis.get('structure', {})
            current_trend = structure.get('current_trend')
            break_structure = structure.get('structure_breaks', [])
            
            # Vérifier si un CHoCH récent correspondant à notre direction est arrivé
            # L'analyse structurelle standard donne souvent le trend courant.
            # On veut détecter le CHANGEMENT.
            
            choch_valid = False
            
            # Méthode simple: Si le MarketStructure détecte un changement de trend favorable
            # OU si on a explicitement un 'break_type': 'choch' dans les données
            
            target_trend = "BULLISH" if state.sweep_direction == "BUY" else "BEARISH"
            
            # Vérification directe dans la liste des breaks récents (si disponible)
            # Ce bloc dépend de la structure de 'structure_breaks' dans smc_strategy/MarketStructure
            
            # Strict Institutional CHoCH Validation
            # Must detect a NEW CHoCH that happened AFTER the Sweep.
            
            latest_choch = None
            for b in reversed(break_structure):
                # FRESHness: Le CHoCH doit impérativement être arrivé APRÈS le sweep
                if b.type.name == "CHOCH" and b.timestamp > state.sweep_time:
                    # DIRECTION: Doit correspondre à l'inversion attendue après le sweep
                    is_bullish_reversal = (state.sweep_direction == "BUY" and b.direction.name == "BULLISH")
                    is_bearish_reversal = (state.sweep_direction == "SELL" and b.direction.name == "BEARISH")
                    
                    if is_bullish_reversal or is_bearish_reversal:
                        # ✅ NOUVEAU: Validation par l'impulsion (Displacement)
                        # On s'assure que le mouvement qui a causé le CHoCH n'est pas "mou"
                        # On peut utiliser le break_price vs swing_price pour estimer la force
                        break_distance = abs(b.break_price - b.swing_price)
                        
                        # Seuil minimal de cassure (ex: 5 pips sur forex)
                        min_break = 0.5 if "PDL" in state.sweep_type or "PDH" in state.sweep_type else 0.2
                        # Ajuster pour Gold
                        if current_price > 1000: min_break *= 10 
                        
                        if break_distance > min_break:
                            choch_valid = True
                            latest_choch = b
                            break

            if choch_valid:
                state.stage = SMCStage.STRUCTURE_SHIFT
                state.choch_detected = True
                state.choch_price = latest_choch.break_price if latest_choch else current_price
                state.choch_time = latest_choch.timestamp if latest_choch else pd.Timestamp.now()
                self.bar_counts[symbol] = 0
                logger.info(f"[{symbol}] ⚡ CHoCH Institutionnel Validé! Direction: {state.sweep_direction} | Prix: {state.choch_price:.5f}")
            
            # ❌ INVALIDATION DU SWEEP:
            # Si le prix continue de s'enfoncer au-delà du sweep sans faire de CHoCH
            # On considère que ce n'était pas un sweep mais une continuation de tendance.
            invalidation_buffer = 15.0 # pips
            if "XAU" in symbol: invalidation_buffer = 5.0 # $5 sur l'or
            
            pips_multiplier = 0.0001 if current_price < 1000 else 1.0 # Simple approx
            
            if state.sweep_direction == "BUY" and current_price < (state.sweep_price - invalidation_buffer * pips_multiplier):
                self.reset_state(symbol, "Continuation baissière détectée (Sweep invalidé)")
            elif state.sweep_direction == "SELL" and current_price > (state.sweep_price + invalidation_buffer * pips_multiplier):
                self.reset_state(symbol, "Continuation haussière détectée (Sweep invalidé)")

        # 3. STRUCTURE_SHIFT -> ENTRY_READY
        elif state.stage == SMCStage.STRUCTURE_SHIFT:
            # On a le sweep, on a le CHoCH. Maintenant on veut un retracement vers OB ou FVG ou OTE.
            
            # Vérifier zones
            # On réutilise les détecteurs de l'analyse courante
            
            entry_signal = False
            entry_reason = ""
            
            dir_str = state.sweep_direction
            
            # Check iFVG / FVG
            ifvgs = analysis.get('ifvgs', [])
            fvgs = analysis.get('fvgs', [])
            
            # Check Order Blocks
            # (Requires implementation in Strategy to pass check result or doing it here)
            # Simplification: Si l'analyse dit qu'on est dans une zone...
            
            # Pour l'instant on va laisser la stratégie 'generate_signal' valider la zone précise (OB/FVG).
            # La machine d'état dit juste: "C'est bon, tu as le droit de chercher une entrée".
            # Mais on peut être plus strict:
            
            pd_zone = analysis.get('pd_zone')
            if pd_zone:
                current_zone = pd_zone.current_zone.value
                # If BUY, we want Discount. If SELL, we want Premium.
                allowed_zone = (dir_str == "BUY" and current_zone in ['DISCOUNT', 'EQUILIBRIUM']) or \
                               (dir_str == "SELL" and current_zone in ['PREMIUM', 'EQUILIBRIUM'])
                
                if allowed_zone:
                    state.stage = SMCStage.ENTRY_READY
                    state.valid_entry_zone = True
                    state.last_update = pd.Timestamp.now()
                    self.bar_counts[symbol] = 0
                    logger.info(f"[{symbol}] ✅ Entry Zone Validated ({current_zone}). READY TO TRADE.")

        # 4. ENTRY_READY Monitor
        elif state.stage == SMCStage.ENTRY_READY:
             # On reste dans cet état tant que le setup est valide
             # Invalidation si on casse le Low du Sweep (pour un Buy)
             if state.sweep_direction == "BUY":
                 if current_price < state.sweep_price:
                     self.reset_state(symbol, "Price broke Sweep Low (Invalidation)")
             elif state.sweep_direction == "SELL":
                 if current_price > state.sweep_price:
                     self.reset_state(symbol, "Price broke Sweep High (Invalidation)")

        state.last_update = pd.Timestamp.now()
