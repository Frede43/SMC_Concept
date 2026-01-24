"""
SMT Divergence (Smart Money Tool)
Détecteur de divergence institutionnelle entre actifs corrélés.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple, List
from loguru import logger
from enum import Enum

class SMTType(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NONE = "none"

class SMTDetector:
    """
    Détecteur de SMT Divergence.
    Compare deux actifs pour détecter des divergences de haut/bas.
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.lookback = self.config.get('lookback_bars', 30)
        self.swing_strength = self.config.get('swing_strength', 3)

    def detect(self, df_main: pd.DataFrame, df_corr: pd.DataFrame, 
               correlation_type: str = "positive",
               main_sweeps: List = None,
               corr_sweeps: List = None) -> Tuple[SMTType, str]:
        """
        Détecte une divergence SMT entre deux flux de données.
        Supporte désormais la validation par balayage de liquidité (Sweep).
        """
        if df_main is None or df_corr is None:
            return SMTType.NONE, "Pas assez de données"
        
        # Validation basique
        if len(df_main) < self.lookback or len(df_corr) < self.lookback:
            return SMTType.NONE, "Historique insuffisant"

        # 1. LOGIQUE DE VALIDATION PAR SWEEP (Nouveau & Puissant)
        # Si on a des infos sur les sweeps récents, on vérifie la divergence de sweep
        if main_sweeps or df_corr is not None:
            is_sweep_smt, smt_type, reason = self._check_sweep_divergence(
                main_sweeps, corr_sweeps, correlation_type, df_corr=df_corr
            )
            if is_sweep_smt:
                return smt_type, reason

        # 2. LOGIQUE CLASSIQUE (Swing to Swing)
        # Synchroniser les queues
        df_m = df_main.tail(self.lookback)
        df_c = df_corr.tail(self.lookback)
        
        # BULLISH SMT
        bullish_smt, reason_bull = self._check_bullish_smt(df_m, df_c, correlation_type)
        if bullish_smt:
            return SMTType.BULLISH, reason_bull

        # BEARISH SMT
        bearish_smt, reason_bear = self._check_bearish_smt(df_m, df_c, correlation_type)
        if bearish_smt:
            return SMTType.BEARISH, reason_bear

        return SMTType.NONE, "Pas de divergence SMT"

    def _check_sweep_divergence(self, main_sweeps: List, corr_sweeps: List, 
                                correlation_type: str, df_corr: pd.DataFrame = None) -> Tuple[bool, SMTType, str]:
        """
        Détecte si un actif a balayé la liquidité alors que son corrélé a échoué.
        """
        main_sweeps = main_sweeps or []
        
        # Si on n'a pas les sweeps du corrélé, on tente de les détecter sur la queue du DF
        if not corr_sweeps and df_corr is not None:
             corr_sweeps = self._detect_basic_sweeps(df_corr)

        corr_sweeps = corr_sweeps or []
        
        # On ne garde que les sweeps très récents (dernières bougies)
        # pour éviter les faux signaux SMT décalés
        m_bull_sweep = any(s.type.value == "sell_side" for s in main_sweeps[-3:])
        c_bull_sweep = any(s.type.value == "sell_side" for s in corr_sweeps[-3:])
        
        m_bear_sweep = any(s.type.value == "buy_side" for s in main_sweeps[-3:])
        c_bear_sweep = any(s.type.value == "buy_side" for s in corr_sweeps[-3:])

        if correlation_type == "positive":
            if m_bull_sweep and not c_bull_sweep:
                return True, SMTType.BULLISH, " المؤسساتية SMT: Main swept Low but Corr failed (Positive)"
            if m_bear_sweep and not c_bear_sweep:
                return True, SMTType.BEARISH, " المؤسساتية SMT: Main swept High but Corr failed (Positive)"
        else: # negative
            if m_bull_sweep and not c_bear_sweep: # EU sweeps Low, DXY fails to sweep High
                return True, SMTType.BULLISH, " المؤسساتية SMT: Main swept Low but DXY failed High (Negative)"
            if m_bear_sweep and not c_bull_sweep: # EU sweeps High, DXY fails to sweep Low
                return True, SMTType.BEARISH, " المؤسساتية SMT: Main swept High but DXY failed Low (Negative)"

        return False, SMTType.NONE, ""

    def _detect_basic_sweeps(self, df: pd.DataFrame) -> List:
        """Détecte sommairement les sweeps sur un DF sans analyse complète."""
        from dataclasses import dataclass
        @dataclass
        class SimpleSweep:
            type: Any
            
        @dataclass
        class SweepType:
            value: str

        sweeps = []
        if len(df) < 5: return []
        
        # Simulation simplifiée: si le prix actuel est passé sous le bas des 20 dernières bougies puis a réintégré
        recent_low = df['low'].iloc[-20:-1].min()
        recent_high = df['high'].iloc[-20:-1].max()
        
        current_low = df['low'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_close = df['close'].iloc[-1]
        
        if current_low < recent_low and current_close > recent_low:
            sweeps.append(SimpleSweep(type=SweepType("sell_side")))
        if current_high > recent_high and current_close < recent_high:
            sweeps.append(SimpleSweep(type=SweepType("buy_side")))
            
        return sweeps

    def _check_bullish_smt(self, df_main: pd.DataFrame, df_corr: pd.DataFrame, 
                           correlation_type: str) -> Tuple[bool, str]:
        """Vérifie si une SMT Bullish existe."""
        # Trouver les deux derniers bas significatifs sur le Main
        lows_main = self._find_swings(df_main['low'], is_high=False)
        if len(lows_main) < 2: return False, ""
        
        m_idx1, m_p1 = lows_main[-2] # Avant-dernier bas
        m_idx2, m_p2 = lows_main[-1] # Dernier bas
        
        # On veut que le Main ait fait un plus bas (Lower Low)
        if m_p2 < m_p1:
            # Chercher les prix correspondants sur l'actif corrélé aux mêmes moments
            # (Ou les swings les plus proches dans le temps)
            try:
                # On utilise les index temporels pour être précis
                t1, t2 = df_main.index[m_idx1], df_main.index[m_idx2]
                
                if correlation_type == "positive":
                    # Sur GU, on cherche le bas au moment t1 et t2
                    # Si t2 n'est pas un LL alors que EU est un LL -> SMT
                    c_p1 = df_corr.loc[t1]['low'] if t1 in df_corr.index else df_corr.iloc[m_idx1]['low']
                    c_p2 = df_corr.loc[t2]['low'] if t2 in df_corr.index else df_corr.iloc[m_idx2]['low']
                    
                    if c_p2 > c_p1:
                        return True, f"Bullish SMT: Main LL vs Corr HL (Positive Corr)"
                
                else: # negative (ex: DXY)
                    # Sur DXY, on s'attend à un HH. Si DXY fait un LL -> SMT
                    c_p1 = df_corr.loc[t1]['high'] if t1 in df_corr.index else df_corr.iloc[m_idx1]['high']
                    c_p2 = df_corr.loc[t2]['high'] if t2 in df_corr.index else df_corr.iloc[m_idx2]['high']
                    
                    # SMT Négative Bullish: Main LL, DXY LL (au lieu de faire un HH)
                    # En réalité ICT dit: DXY fail to make HH
                    if c_p2 < c_p1:
                         return True, f"Bullish SMT: Main LL vs Corr LL (Negative Corr/DXY Fail)"
                         
            except Exception as e:
                logger.debug(f"SMT index error: {e}")
                
        return False, ""

    def _check_bearish_smt(self, df_main: pd.DataFrame, df_corr: pd.DataFrame, 
                           correlation_type: str) -> Tuple[bool, str]:
        """Vérifie si une SMT Bearish existe."""
        highs_main = self._find_swings(df_main['high'], is_high=True)
        if len(highs_main) < 2: return False, ""
        
        m_idx1, m_p1 = highs_main[-2]
        m_idx2, m_p2 = highs_main[-1]
        
        if m_p2 > m_p1: # Main Higher High
            try:
                t1, t2 = df_main.index[m_idx1], df_main.index[m_idx2]
                
                if correlation_type == "positive":
                    c_p1 = df_corr.loc[t1]['high'] if t1 in df_corr.index else df_corr.iloc[m_idx1]['high']
                    c_p2 = df_corr.loc[t2]['high'] if t2 in df_corr.index else df_corr.iloc[m_idx2]['high']
                    
                    if c_p2 < c_p1: # Corr Lower High
                        return True, f"Bearish SMT: Main HH vs Corr LH (Positive Corr)"
                
                else: # negative
                    c_p1 = df_corr.loc[t1]['low'] if t1 in df_corr.index else df_corr.iloc[m_idx1]['low']
                    c_p2 = df_corr.loc[t2]['low'] if t2 in df_corr.index else df_corr.iloc[m_idx2]['low']
                    
                    # SMT Négative Bearish: Main HH, DXY HH (au lieu de LL)
                    if c_p2 > c_p1:
                        return True, f"Bearish SMT: Main HH vs Corr HH (Negative Corr/DXY Fail)"
                        
            except Exception as e:
                logger.debug(f"SMT index error: {e}")
                
        return False, ""

    def _find_swings(self, series: pd.Series, is_high: bool = True) -> List[Tuple[int, float]]:
        """Trouve les points de swing dans une série."""
        swings = []
        n = self.swing_strength
        
        # Conversion en numpy pour la vitesse
        arr = series.values
        for i in range(n, len(arr) - n):
            val = arr[i]
            if is_high:
                if all(val > arr[i-j] for j in range(1, n+1)) and \
                   all(val >= arr[i+j] for j in range(1, n+1)):
                    swings.append((i, val))
            else:
                if all(val < arr[i-j] for j in range(1, n+1)) and \
                   all(val <= arr[i+j] for j in range(1, n+1)):
                    swings.append((i, val))
        return swings

    def check_risk_off(self, vix_df: pd.DataFrame) -> Tuple[bool, str]:
        """
        Analyse le VIX pour déterminer si le marché est en mode Risk-OFF (Peur).
        Une divergence SMT + Risk-OFF est un signal très puissant pour shorter les actifs à risque.
        """
        if vix_df is None or len(vix_df) < 20:
            return False, "No VIX data"
            
        current_vix = vix_df['close'].iloc[-1]
        ma_20_vix = vix_df['close'].rolling(window=20).mean().iloc[-1]
        
        # Risk-OFF condition: VIX > 20 et en hausse (au-dessus de sa MA20)
        if current_vix > 20 and current_vix > ma_20_vix:
            return True, f"Risk-OFF Detected (VIX={current_vix:.2f} > 20)"
            
        return False, "Risk-ON"
