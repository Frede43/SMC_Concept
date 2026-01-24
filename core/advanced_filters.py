"""
Advanced Filters Module for SMC Trading
Filtres avancés pour améliorer la qualité des signaux

Ces filtres sont basés sur l'analyse du backtest qui a montré:
- PDH/PDL Sweep sur XAUUSD: 64-72% WR
- Asian Sweep sur Forex: 70-72% WR
- FVG seul: <30% WR (à utiliser en confluence)

Améliorations implémentées:
1. ATR Dynamic SL/TP - Stop loss et take profit adaptatifs
2. Multi-Candle Confirmation - Éviter les faux breakouts
3. Structure Validation - Vérifier l'alignement avec la structure
4. Time-Based Filters - Trader aux heures optimales
5. Momentum Filter - Confirmer la force du mouvement
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional, List, Dict, Tuple
from enum import Enum
from loguru import logger


class SignalQuality(Enum):
    """Qualité du signal de trading"""
    A_PLUS = "A+"      # Setup parfait - Full position
    A = "A"            # Excellent setup - 80% position
    B = "B"            # Bon setup - 50% position
    C = "C"            # Setup moyen - 30% position
    REJECT = "REJECT"  # Ne pas trader


@dataclass
class VolumeAnalysis:
    """Analyse du volume et de la pression"""
    is_safe: bool
    cmf_value: float
    pressure_direction: str  # "BUY", "SELL", "NEUTRAL"
    volume_trend: str        # "increasing", "decreasing"
    reason: str


@dataclass
class ATRInfo:
    """Information sur l'ATR (Average True Range)"""
    current_atr: float
    atr_14: float
    atr_50: float
    volatility_ratio: float  # current / average
    is_high_volatility: bool
    is_low_volatility: bool
    suggested_sl_pips: float
    suggested_tp_pips: float


@dataclass 
class ConfirmationResult:
    """Résultat de la confirmation multi-bougies"""
    is_confirmed: bool
    candles_confirmed: int
    required_candles: int
    direction: str
    strength: float  # 0-100
    rejection_reason: str = ""


@dataclass
class StructureAlignment:
    """Alignement avec la structure de marché"""
    htf_trend: str           # "bullish", "bearish", "ranging"
    ltf_trend: str
    is_aligned: bool
    alignment_score: float   # 0-100
    notes: List[str]


@dataclass
class TimeFilter:
    """Filtre basé sur le temps"""
    is_optimal_time: bool
    current_session: str
    session_quality: str     # "prime", "good", "avoid"
    hours_until_close: float
    avoid_reason: str = ""


@dataclass
class EnhancedSignal:
    """Signal amélioré avec tous les filtres et Scoring Matriciel"""
    original_direction: str
    final_direction: str
    quality: SignalQuality
    confidence: float
    
    # Composants de Scoring (Détail pour le dashboard)
    score_details: Dict[str, float]
    
    # Informations techniques
    atr_info: Optional[ATRInfo]
    confirmation: Optional[ConfirmationResult]
    structure: Optional[StructureAlignment]
    time_filter: Optional[TimeFilter]
    volume_analysis: Optional[VolumeAnalysis]
    spread_info: Optional[Dict]  # Nouveau: Infos spread & slippage
    
    # Niveaux ajustés
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size_multiplier: float
    
    # Raisons et Alertes
    reasons: List[str]
    warnings: List[str]
    
    # Pro Confluences
    adr_exhaustion: float = 0.0  # 0-100%
    is_near_round_number: bool = False


class AdvancedFilters:
    """
    Filtres avancés pour améliorer la qualité des signaux SMC.
    
    Usage:
        filters = AdvancedFilters(config)
        enhanced = filters.enhance_signal(df, signal_direction, entry_price, symbol)
    """
    
    def __init__(self, config: Dict = None):
        """
        Args:
            config: Configuration optionnelle
        """
        self.config = config or {}
        
        # ATR settings - Ajustés pour des SL/TP plus réalistes
        self.atr_period = self.config.get('atr_period', 14)
        self.atr_multiplier_sl = self.config.get('atr_multiplier_sl', 1.0)  # Réduit de 1.5 à 1.0
        self.atr_multiplier_tp = self.config.get('atr_multiplier_tp', 2.0)  # Réduit de 3.0 à 2.0
        
        # Confirmation settings - Plus permissif
        self.min_confirmation_candles = self.config.get('min_confirmation_candles', 1)  # Réduit de 2 à 1
        self.max_confirmation_candles = self.config.get('max_confirmation_candles', 5)
        
        # Time settings
        self.timezone_offset = self.config.get('timezone_offset', 2)
        
        # Structure settings
        self.allow_counter_trend = self.config.get('allow_counter_trend', False)
        
        # 🆕 TREND ALIGNMENT WEIGHTS (Adaptatif par mode)
        # Recommandation Expert: Réduire le poids du HTF pour permettre contra-trend
        self.htf_alignment_weight = self.config.get('htf_alignment_weight', 0.25)  # 🚀 Réduit de 0.40
        self.ltf_alignment_weight = self.config.get('ltf_alignment_weight', 0.25)  # 🚀 Réduit de 0.40
        self.confluence_weight = 1.0 - (self.htf_alignment_weight + self.ltf_alignment_weight)  # Reste
        
        # Quality thresholds - Ajustés pour plus de trades
        self.quality_thresholds = {
            'A+': 85,  # Réduit de 90
            'A': 70,   # Réduit de 80
            'B': 55,   # Réduit de 65
            'C': 40    # Réduit de 50
        }
        
        logger.info(f"🎯 Advanced Filters initialized | HTF weight: {self.htf_alignment_weight*100:.0f}%, "
                   f"LTF weight: {self.ltf_alignment_weight*100:.0f}%, "
                   f"Confluence: {self.confluence_weight*100:.0f}%")
    
    # =========================================================================
    # 1. ATR DYNAMIC SL/TP
    # =========================================================================
    
    def calculate_atr(self, df: pd.DataFrame, symbol: str = "UNKNOWN") -> ATRInfo:
        """
        Calcule l'ATR et suggère des niveaux SL/TP dynamiques.
        
        L'ATR (Average True Range) mesure la volatilité et permet d'ajuster
        les stops en fonction des conditions de marché actuelles.
        """
        try:
            # Calculer le True Range
            high = df['high']
            low = df['low']
            close = df['close'].shift(1)
            
            tr1 = high - low
            tr2 = abs(high - close)
            tr3 = abs(low - close)
            
            true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            
            # ATR périodes
            atr_14 = true_range.rolling(window=14).mean().iloc[-1]
            atr_50 = true_range.rolling(window=50).mean().iloc[-1]
            current_atr = true_range.iloc[-1]
            
            # Ratio de volatilité
            volatility_ratio = atr_14 / atr_50 if atr_50 > 0 else 1.0
            
            # Déterminer si haute/basse volatilité
            is_high = volatility_ratio > 1.3
            is_low = volatility_ratio < 0.7
            
            # Pip value selon le symbole
            pip_value = self._get_pip_value(symbol)
            
            # Récupérer la configuration dynamique
            dyn_config = self.config.get('risk', {}).get('dynamic_sl_tp', {})
            
            # Multiplicateurs ATR (défaut: 1.5x SL, 3.0x TP)
            mult_sl = dyn_config.get('sl_atr_multiplier', self.atr_multiplier_sl)
            mult_tp = dyn_config.get('tp_atr_multiplier', self.atr_multiplier_tp)
            
            # Limites globales (fallback si non définies en config)
            global_min_sl = dyn_config.get('min_sl_pips', 10)
            global_max_sl = dyn_config.get('max_sl_pips', 50)
            global_min_tp = dyn_config.get('min_tp_pips', 20)
            global_max_tp = dyn_config.get('max_tp_pips', 100)
            
            # Suggérer SL/TP en pips basés sur l'ATR
            suggested_sl = (atr_14 * mult_sl) / pip_value
            suggested_tp = (atr_14 * mult_tp) / pip_value
            
            # Limites spécifiques par type d'actif (Override les limites globales si nécessaire)
            if "XAU" in symbol:
                min_sl, max_sl = 300, 1000
                min_tp, max_tp = 500, 2000
            elif "JPY" in symbol:
                min_sl, max_sl = 10, 40
                min_tp, max_tp = 20, 80
            elif "BTC" in symbol or "ETH" in symbol:
                min_sl, max_sl = 1000, 200000 
                min_tp, max_tp = 2000, 500000
            else:
                # Forex Standard: Utiliser la config globale ou les défauts ajustés
                min_sl = global_min_sl
                max_sl = global_max_sl
                min_tp = global_min_tp
                max_tp = global_max_tp
            
            # Appliquer les limites
            suggested_sl = max(min_sl, min(suggested_sl, max_sl))
            suggested_tp = max(min_tp, min(suggested_tp, max_tp))
            
            atr_info = ATRInfo(
                current_atr=current_atr,
                atr_14=atr_14,
                atr_50=atr_50,
                volatility_ratio=volatility_ratio,
                is_high_volatility=is_high,
                is_low_volatility=is_low,
                suggested_sl_pips=suggested_sl,
                suggested_tp_pips=suggested_tp
            )
            
            logger.debug(f"ATR Info: ATR14={atr_14:.5f}, Ratio={volatility_ratio:.2f}, "
                        f"SL={suggested_sl:.1f} pips (cap: {max_sl}), TP={suggested_tp:.1f} pips (cap: {max_tp})")
            
            return atr_info
            
        except Exception as e:
            logger.error(f"Erreur calcul ATR: {e}")
            # Retourner des valeurs par défaut
            return ATRInfo(
                current_atr=0.0,
                atr_14=0.0,
                atr_50=0.0,
                volatility_ratio=1.0,
                is_high_volatility=False,
                is_low_volatility=False,
                suggested_sl_pips=20,
                suggested_tp_pips=40
            )
            
    # =========================================================================
    # 1.5 VOLUME PRESSURE (CMF & RVOL)
    # =========================================================================
    
    def _get_session_relative_volume(self, df: pd.DataFrame) -> float:
        """
        Calcule le volume relatif par rapport à la même heure les jours précédents.
        (RVOL par Session)
        """
        try:
            if 'tick_volume' not in df.columns and 'volume' not in df.columns:
                return 1.0
            
            vol_col = 'tick_volume' if 'tick_volume' in df.columns else 'volume'
            current_time = df.index[-1]
            current_vol = df[vol_col].iloc[-1]
            
            # Extraire les volumes à la même heure (HH:MM) sur les jours précédents
            same_time_mask = (df.index.hour == current_time.hour) & (df.index.minute == current_time.minute)
            # Exclure le jour actuel pour la moyenne
            past_volumes = df[same_time_mask][vol_col].iloc[:-1]
            
            if len(past_volumes) < 3: # Pas assez de jours
                return 1.0
                
            avg_session_vol = past_volumes.tail(10).mean() # Moyenne sur les 10 derniers jours max
            
            return current_vol / avg_session_vol if avg_session_vol > 0 else 1.0
        except:
            return 1.0

    def check_volume_pressure(self, df: pd.DataFrame, signal_direction: str) -> VolumeAnalysis:
        """
        Vérifie la pression volumétrique via Chaikin Money Flow (CMF) et RVOL.
        """
        # ✅ FIX: Initialiser les variables par défaut AVANT le try pour éviter UnboundLocalError
        reason = "Volume analysis"
        is_safe = True
        pressure_dir = "NEUTRAL"
        vol_trend = "unknown"
        current_cmf = 0.0
        
        try:
            # 1. Calcul RVOL (Relative Volume par Session)
            rvol = self._get_session_relative_volume(df)
            
            # Vérifier si on a du volume
            if 'volume' not in df.columns and 'tick_volume' not in df.columns:
                return VolumeAnalysis(True, 0.0, "NEUTRAL", "unknown", "Pas de données volume")
            
            vol_col = 'volume' if 'volume' in df.columns else 'tick_volume'
            
            # Calcul CMF (20 périodes)
            period = 20
            adl = ((2 * df['close'] - df['high'] - df['low']) / (df['high'] - df['low'])).fillna(0)
            mf_volume = adl * df[vol_col]
            cmf = mf_volume.rolling(window=period).sum() / df[vol_col].rolling(window=period).sum()
            current_cmf = cmf.iloc[-1]
            
            # Analyse de la tendance du volume
            vol_sma20 = df[vol_col].rolling(window=20).mean().iloc[-1]
            vol_trend = "increasing" if df[vol_col].rolling(window=5).mean().iloc[-1] > vol_sma20 else "decreasing"
            
            # --- VSA (Volume Spread Analysis) avec RVOL ---
            vsa_signal = "NORMAL"
            is_safe = True
            reason = f"RVOL: {rvol:.2f}x"
            
            current_range = df['high'].iloc[-1] - df['low'].iloc[-1]
            avg_range = (df['high'] - df['low']).rolling(window=20).mean().iloc[-1]

            # 1. Faible volume session
            if rvol < 0.5:
                is_safe = False
                reason += " (Absence Institutionnelle 💤)"
            
            # 2. Churning / Absorption (Gros volume relatif, petit range) -> Manipulation probable
            elif rvol > 1.5 and current_range < (avg_range * 0.8):
                vsa_signal = "CHURNING_ABSORPTION"
                reason += " | VSA Churning (Manipulation Probable 🛑)"
                is_safe = False
            
            # 3. Ignition / Breakout (Gros volume, gros range) -> Force réelle
            elif rvol > 1.2 and current_range > (avg_range * 1.1):
                vsa_signal = "IGNITION"
                reason += " | VSA Ignition 🔥"
            
            # Déterminer la direction de la pression
            pressure_dir = "NEUTRAL"
            if current_cmf > 0.05: pressure_dir = "BUY"
            elif current_cmf < -0.05: pressure_dir = "SELL"
            
            # Divergence Volume/Prix
            if signal_direction == "BUY" and current_cmf < -0.15:
                is_safe = False
                reason += f" | Divergence Bearish (CMF={current_cmf:.2f})"
            elif signal_direction == "SELL" and current_cmf > 0.15:
                is_safe = False
                reason += f" | Divergence Bullish (CMF={current_cmf:.2f})"

            return VolumeAnalysis(
                is_safe=is_safe,
                cmf_value=current_cmf,
                pressure_direction=pressure_dir,
                volume_trend=vol_trend,
                reason=reason
            )
            
        except Exception as e:
            logger.error(f"Erreur analyse volume: {e}")
            return VolumeAnalysis(True, 0.0, "NEUTRAL", "error", str(e))

    # =========================================================================
    # 1.1 ADR (AVERAGE DAILY RANGE) EXHAUSTION
    # =========================================================================
    
    def check_adr_exhaustion(self, df: pd.DataFrame, htf_df: pd.DataFrame = None) -> float:
        """
        Calcule si le mouvement du jour a déjà épuisé l'ADR.
        Retourne le % d'utilisation de l'ADR (0-100+).
        """
        try:
            if htf_df is None or len(htf_df) < 14:
                return 0.0
                
            # ADR 14 jours (HTF est D1)
            htf_ranges = htf_df['high'] - htf_df['low']
            adr = htf_ranges.tail(14).mean()
            
            # Mouvement du jour actuel
            # On cherche le début de la journée dans le dataframe LTF (df)
            today = df.index[-1].date()
            today_df = df[df.index.date == today]
            
            if len(today_df) == 0:
                return 0.0
                
            today_range = today_df['high'].max() - today_df['low'].min()
            exhaustion_pct = (today_range / adr) * 100 if adr > 0 else 0
            
            return exhaustion_pct
        except Exception as e:
            logger.error(f"Erreur ADR: {e}")
            return 0.0

    # =========================================================================
    # 1.2 INSTITUTIONAL ROUND NUMBERS
    # =========================================================================
    
    def check_round_numbers(self, price: float, symbol: str) -> bool:
        """
        Vérifie si le prix est proche d'un 'Big Figure' (000) ou d'un niveau institutionnel (500).
        """
        if "JPY" in symbol or "XAU" in symbol or "BTC" in symbol:
            # Pour JPY/XAU/BTC, on regarde les multiples de 100, 50, 10
            # Exemple Gold: 2000, 2010, 2050
            levels = [100.0, 50.0, 10.0]
            for lvl in levels:
                if abs(price % lvl) < (lvl * 0.02) or abs(price % lvl) > (lvl * 0.98):
                    return True
        else:
            # Forex Standard: 1.1000, 1.1050, 1.1100
            # On multiplie par 10000 pour travailler en points/pips
            price_pips = price * 10000
            # Niveaux 00 et 50 pips
            if (price_pips % 100 < 5) or (price_pips % 100 > 95): # .XX00
                return True
            if abs(price_pips % 100 - 50) < 5: # .XX50
                return True
                
        return False

    
    def check_confirmation(self, df: pd.DataFrame, direction: str, 
                          lookback: int = 5) -> ConfirmationResult:
        """
        Vérifie la confirmation multi-bougies pour éviter les faux signaux.
        
        Critères de confirmation:
        - BUY: X bougies consécutives avec close > open
        - SELL: X bougies consécutives avec close < open
        - Force basée sur la taille des corps
        """
        try:
            recent = df.tail(lookback)
            candles_confirmed = 0
            total_body_size = 0
            
            for i in range(len(recent)):
                candle = recent.iloc[i]
                body = candle['close'] - candle['open']
                
                if direction == "BUY" and body > 0:
                    candles_confirmed += 1
                    total_body_size += body
                elif direction == "SELL" and body < 0:
                    candles_confirmed += 1
                    total_body_size += abs(body)
                else:
                    # Reset si bougie contraire
                    if i > 0:  # Tolérer 1 bougie contraire
                        pass
            
            # Calculer la force (basée sur taille des corps vs range)
            avg_range = (recent['high'] - recent['low']).mean()
            strength = min(100, (abs(total_body_size) / (avg_range * lookback)) * 100) if avg_range > 0 else 50
            
            is_confirmed = candles_confirmed >= self.min_confirmation_candles
            
            rejection_reason = ""
            if not is_confirmed:
                rejection_reason = f"Seulement {candles_confirmed}/{self.min_confirmation_candles} bougies confirmées"
            
            result = ConfirmationResult(
                is_confirmed=is_confirmed,
                candles_confirmed=candles_confirmed,
                required_candles=self.min_confirmation_candles,
                direction=direction,
                strength=strength,
                rejection_reason=rejection_reason
            )
            
            logger.debug(f"Confirmation: {candles_confirmed} bougies {direction}, "
                        f"strength={strength:.1f}%, confirmed={is_confirmed}")
            
            return result
            
        except Exception as e:
            logger.error(f"Erreur confirmation: {e}")
            return ConfirmationResult(
                is_confirmed=False,
                candles_confirmed=0,
                required_candles=self.min_confirmation_candles,
                direction=direction,
                strength=0,
                rejection_reason=str(e)
            )
    
    # =========================================================================
    # 3. STRUCTURE VALIDATION
    # =========================================================================
    
    def validate_structure(self, df: pd.DataFrame, htf_df: pd.DataFrame = None,
                          signal_direction: str = "BUY", 
                          allow_counter_trend: bool = None) -> StructureAlignment:
        """
        Valide l'alignement du signal avec la structure de marché.
        
        Règles:
        - BUY seulement si tendance bullish ou ranging en zone discount
        - SELL seulement si tendance bearish ou ranging en zone premium
        """
        notes = []
        
        try:
            # Analyser la tendance LTF (20 dernières bougies)
            ltf_trend = self._detect_trend(df.tail(50))
            notes.append(f"LTF Trend: {ltf_trend}")
            
            # Analyser la tendance HTF si disponible
            htf_trend = "unknown"
            if htf_df is not None and len(htf_df) > 20:
                htf_trend = self._detect_trend(htf_df.tail(30))
                notes.append(f"HTF Trend: {htf_trend}")
            
            # Vérifier l'alignement
            alignment_score = 0
            is_aligned = False
            
            # Conversion des poids en points (ex: 0.25 -> 25 points)
            ltf_max_score = self.ltf_alignment_weight * 100
            htf_max_score = self.htf_alignment_weight * 100
            
            if signal_direction == "BUY":
                # LTF Scoring
                if ltf_trend == "bullish":
                    alignment_score += ltf_max_score
                    notes.append("✓ LTF bullish")
                elif ltf_trend == "ranging":
                    alignment_score += ltf_max_score * 0.75  # 75% du max score
                    notes.append("~ LTF ranging")
                else:
                    notes.append("✗ LTF bearish - contre-tendance")
                
                # HTF Scoring
                if htf_trend == "bullish":
                    alignment_score += htf_max_score
                    notes.append("✓ HTF bullish")
                elif htf_trend == "ranging":
                    alignment_score += htf_max_score * 0.75
                    notes.append("~ HTF ranging")
                elif htf_trend == "unknown":
                    alignment_score += htf_max_score * 0.5   # Neutre
                else:
                    notes.append("✗ HTF bearish")
            
            elif signal_direction == "SELL":
                # LTF Scoring
                if ltf_trend == "bearish":
                    alignment_score += ltf_max_score
                    notes.append("✓ LTF bearish")
                elif ltf_trend == "ranging":
                    alignment_score += ltf_max_score * 0.75
                    notes.append("~ LTF ranging")
                else:
                    notes.append("✗ LTF bullish - contre-tendance")
                
                # HTF Scoring
                if htf_trend == "bearish":
                    alignment_score += htf_max_score
                    notes.append("✓ HTF bearish")
                elif htf_trend == "ranging":
                    alignment_score += htf_max_score * 0.75
                    notes.append("~ HTF ranging")
                elif htf_trend == "unknown":
                    alignment_score += htf_max_score * 0.5
                else:
                    notes.append("✗ HTF bullish")
            
            # Bonus pour PRO momentum et Confluences (Le reste du poids)
            momentum = self._check_momentum(df, signal_direction)
            if momentum > 0:
                # Le momentum peut ajouter jusqu'à 30% du poids restant
                bonus_points = min(self.confluence_weight * 100 * 0.5, momentum)
                alignment_score += bonus_points
                notes.append(f"✓ Momentum: +{bonus_points:.1f}")
                
                # NOUVEAU: Si momentum extrême (RSI surachat/vente ou Divergence MACD), valider le Reversal
                if momentum >= 20: 
                    is_aligned = True
                    # Force le passage avec un score minimum de 65 pour le mode Balanced+
                    alignment_score = max(alignment_score, 65) 
                    notes.append("✓ Extreme Momentum/Divergence - Reversal Validated")
            
            # LOGIC IMPROVEMENT: Respecter allow_counter_trend MAIS avec validation Momentum
            # Si contre-tendance autorisée (ex: Sweep), on force l'alignement SEULEMENT si le momentum le supporte
            if allow_counter_trend and not is_aligned:
                # Vérifier condition supplémentaire: MOMENTUM EXHAUSTION
                # On ne veut pas shorter un Bull Run violent juste parce qu'il y a un sweep.
                # On exige que le RSI soit en zone extrême (Reversal probable)
                
                momentum_score = self._check_momentum(df, signal_direction)
                momentum_ok = momentum_score >= 10 # Au moins "bon" momentum (ex: RSI > 50 pour SELL non, RSI > 70 pour SELL oui)
                
                # Check Momentum retourne:
                # 20: Extreme (RSI > 70 SELL, RSI < 30 BUY)
                # 10: Good context (RSI > 50 SELL?? Non check implementation)
                
                # Correction lecture _check_momentum:
                # SELL: RSI > 70 -> 20pts, RSI > 50 -> 10pts
                # BUY: RSI < 30 -> 20pts, RSI < 50 -> 10pts
                
                # Pour un contre-tendance, on veut de l'EXTREME (20) ou presque
                if momentum_score >= 15: # Exige RSI Extreme
                    if alignment_score < 60:
                        alignment_score = max(alignment_score + 30, 65) # Boost pour passer le seuil
                        notes.append("✓ Contre-tendance validée (Momentum Extrême/Reversal)")
                        is_aligned = True
                else:
                    notes.append("❌ Contre-tendance rejetée: Momentum trop fort (Pas d'épuisement)")
                    # Le trade restera "not aligned" et sera probablement rejeté ou aura un score très faible
            
            # Vérification standard
            # Vérification standard - RELAXED threshold
            if alignment_score >= 50: # Was 60
                is_aligned = True
            
            return StructureAlignment(
                htf_trend=htf_trend,
                ltf_trend=ltf_trend,
                is_aligned=is_aligned,
                alignment_score=alignment_score,
                notes=notes
            )
            
        except Exception as e:
            logger.error(f"Erreur validation structure: {e}")
            return StructureAlignment(
                htf_trend="unknown",
                ltf_trend="unknown",
                is_aligned=False,
                alignment_score=0,
                notes=[f"Erreur: {e}"]
            )
    
    def _detect_trend(self, df: pd.DataFrame) -> str:
        """
        Détecte la tendance avec des indicateurs Institutionnels (Pro).
        
        Indicateurs utilisés:
        1. EMA 200: Le juge de paix institutionnel (Au-dessus = Bullish, Dessous = Bearish)
        2. EMA 50: Tendance moyen terme
        3. RSI 14: Momentum context ( > 50 Bullish, < 50 Bearish)
        4. Structure: Dow Theory (Higher Highs/Lows)
        """
        try:
            close = df['close']
            current_price = close.iloc[-1]
            
            # --- Indicateurs PRO ---
            # 1. EMAs Institutionnelles
            ema_50 = close.ewm(span=50).mean().iloc[-1]
            ema_200 = close.ewm(span=200).mean().iloc[-1]
            
            # 2. RSI (Momentum)
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1]
            
            # 3. Structure (Price Action)
            highs = df['high']
            lows = df['low']
            recent_high = highs.tail(10).max()
            older_high = highs.tail(20).head(10).max()
            recent_low = lows.tail(10).min()
            older_low = lows.tail(20).head(10).min()
            
            # --- Scoring Avancé ---
            bullish_score = 0
            bearish_score = 0
            
            # Critère 1: Position par rapport à EMA 200 (Fondamental)
            if current_price > ema_200:
                bullish_score += 2  # Poids fort pour EMA 200
            else:
                bearish_score += 2
                
            # Critère 2: Alignement EMA 50 vs EMA 200
            if ema_50 > ema_200:
                bullish_score += 1
            else:
                bearish_score += 1
                
            # Critère 3: RSI Momentum
            if current_rsi > 50:
                bullish_score += 1
            else:
                bearish_score += 1
                
            # Critère 4: Structure (Dow Theory)
            if recent_high > older_high: bullish_score += 1
            if recent_low > older_low: bullish_score += 1
            
            if recent_low < older_low: bearish_score += 1
            if recent_high < older_high: bearish_score += 1
            
            # Debug
            logger.debug(f"PRO Trend Analysis: Price={current_price:.2f}, EMA200={ema_200:.2f}, RSI={current_rsi:.1f}")
            logger.debug(f"Scores: Bull={bullish_score}, Bear={bearish_score}")
            
            # Décision (Seuil ajusté pour robustesse)
            # Max score possible = 2 (EMA200) + 1 (Cross) + 1 (RSI) + 2 (Structure) = 6
            if bullish_score >= 4:
                return "bullish"
            elif bearish_score >= 4:
                return "bearish"
            elif bullish_score > bearish_score: # Biais léger
                return "ranging" # Ou "weak bullish"
            else:
                return "ranging"
                
        except Exception as e:
            logger.error(f"Error in Pro Trend detection: {e}")
            return "unknown"
    
    
    def _calculate_macd(self, df: pd.DataFrame) -> Tuple[float, float, float]:
        """
        Calcule les valeurs MACD (MACD line, Signal line, Histogram).
        Paramètres standard: 12, 26, 9
        """
        try:
            close = df['close']
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            histogram = macd_line - signal_line
            
            return macd_line.iloc[-1], signal_line.iloc[-1], histogram.iloc[-1]
        except:
            return 0.0, 0.0, 0.0

    def _check_macd_divergence(self, df: pd.DataFrame, direction: str) -> int:
        """
        Détecte les divergences MACD (Puissant signal de Reversal SMC).
        Retourne un score (0 à 25).
        """
        try:
            # Besoin d'au moins 30 bougies
            if len(df) < 30: return 0
            
            close = df['close']
            # Calcul MACD complet pour la série
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            
            # Analyse des derniers swings (10 dernières bougies vs 20 avant)
            current_price_low = close.tail(10).min()
            prev_price_low = close.iloc[-30:-10].min()
            
            current_price_high = close.tail(10).max()
            prev_price_high = close.iloc[-30:-10].max()
            
            current_macd_low = macd_line.tail(10).min()
            prev_macd_low = macd_line.iloc[-30:-10].min()
            
            current_macd_high = macd_line.tail(10).max()
            prev_macd_high = macd_line.iloc[-30:-10].max()
            
            score = 0
            
            if direction == "BUY":
                # Divergence haussière (Bullish Div):
                # Prix fait un Lower Low, mais MACD fait un Higher Low
                if current_price_low < prev_price_low and current_macd_low > prev_macd_low:
                    score = 25 # Divergence forte
                
                # Alignement Momentum (MACD > 0 et croisement récent)
                if score == 0:
                     # Si pas de div, on vérifie l'alignement simple
                     macd_val, signal_val, hist = self._calculate_macd(df)
                     if macd_val > signal_val: score = 10 # Momentum haussier
                     
            else: # SELL
                # Divergence baissière (Bearish Div):
                # Prix fait un Higher High, mais MACD fait un Lower High
                if current_price_high > prev_price_high and current_macd_high < prev_macd_high:
                    score = 25 # Divergence forte
                
                # Alignement Momentum (MACD < 0)
                if score == 0:
                     macd_val, signal_val, hist = self._calculate_macd(df)
                     if macd_val < signal_val: score = 10 # Momentum baissier
            
            return score
        except Exception as e:
            logger.error(f"Erreur MACD: {e}")
            return 0

    def _check_momentum(self, df: pd.DataFrame, direction: str) -> float:
        """Vérifie le momentum (RSI + MACD)."""
        try:
            rsi_score = 0
            close = df['close']
            
            # RSI simplifié
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1]
            
            # Score RSI
            if direction == "BUY":
                if current_rsi < 30: rsi_score = 20
                elif current_rsi < 50: rsi_score = 10
            else:  # SELL
                if current_rsi > 70: rsi_score = 20
                elif current_rsi > 50: rsi_score = 10
            
            # Ajouter le score MACD
            macd_score = self._check_macd_divergence(df, direction)
            
            return max(rsi_score, macd_score) # On prend le meilleur des deux
                    
        except:
            return 0
    
    # =========================================================================
    # 4. TIME-BASED FILTERS
    # =========================================================================
    
    def check_time_filter(self, current_time: datetime = None, symbol: str = "") -> TimeFilter:
        """
        Vérifie si c'est un bon moment pour trader.
        
        Sessions optimales:
        - London Open (08:00-10:00 GMT): PRIME
        - NY Open (13:00-15:00 GMT): PRIME  
        - London (10:00-12:00 GMT): GOOD
        - NY (15:00-17:00 GMT): GOOD
        - Asian (00:00-08:00 GMT): AVOID pour exécution
        - After hours: AVOID
        """
        if current_time is None:
            current_time = datetime.now()
            
        # Détection Crypto
        is_crypto = False
        if symbol:
            is_crypto = "BTC" in symbol or "ETH" in symbol or "LTC" in symbol or "CRYPTO" in symbol
        
        # Convertir en GMT
        gmt_hour = (current_time.hour - self.timezone_offset) % 24
        
        # Vérifier le jour de la semaine
        weekday = current_time.weekday()
        if weekday >= 5:  # Weekend
            if is_crypto:
                return TimeFilter(
                    is_optimal_time=True,
                    current_session="weekend_crypto",
                    session_quality="good",
                    hours_until_close=24,
                    avoid_reason=""
                )
            else:
                return TimeFilter(
                    is_optimal_time=False,
                    current_session="weekend",
                    session_quality="avoid",
                    hours_until_close=0,
                    avoid_reason="Weekend - marché fermé"
                )
        
        # Vendredi après 20h GMT - éviter (Sauf Crypto)
        if weekday == 4 and gmt_hour >= 20 and not is_crypto:
            return TimeFilter(
                is_optimal_time=False,
                current_session="friday_close",
                session_quality="avoid",
                hours_until_close=0,
                avoid_reason="Vendredi proche de la fermeture"
            )
        
        # Déterminer la session
        session = "off_hours"
        quality = "avoid"
        hours_until_close = 0
        avoid_reason = ""
        
        if 0 <= gmt_hour < 8:
            session = "asian"
            # 🛡️ CRYPTO EXCEPTION: La session asiatique est excellente pour la crypto
            if is_crypto:
                quality = "good"
                avoid_reason = ""
            else:
                quality = "avoid"  # Identifier le range, pas trader
                avoid_reason = "Session asiatique - attendre London/NY"
            hours_until_close = 8 - gmt_hour
        elif 8 <= gmt_hour < 10:
            session = "london_open"
            quality = "prime"
            hours_until_close = 10 - gmt_hour
        elif 10 <= gmt_hour < 12:
            session = "london"
            quality = "good"
            hours_until_close = 12 - gmt_hour
        elif 12 <= gmt_hour < 13:
            session = "lunch"
            quality = "avoid"
            avoid_reason = "Déjeuner - faible volume"
            hours_until_close = 1
        elif 13 <= gmt_hour < 15:
            session = "ny_open"
            quality = "prime"
            hours_until_close = 15 - gmt_hour
        elif 15 <= gmt_hour < 20:
            session = "ny_afternoon"
            quality = "good"  # Extension jusqu'à 20h GMT (15h NY/16h NY selon saison)
            hours_until_close = 20 - gmt_hour
        elif 20 <= gmt_hour < 22:
            session = "ny_close"
            # 🧪 CRYPTO: Même les changements de bougies journalières sont intéressants
            if is_crypto:
                quality = "good"
                avoid_reason = ""
            else:
                quality = "avoid"
                avoid_reason = "Fin de session NY - spread élargi"
            hours_until_close = 22 - gmt_hour
        else:
            session = "after_hours"
            if is_crypto:
                quality = "good"
                avoid_reason = ""
            else:
                quality = "avoid"
                avoid_reason = "Après les heures de trading"
        
        is_optimal = quality in ["prime", "good"]
        
        return TimeFilter(
            is_optimal_time=is_optimal,
            current_session=session,
            session_quality=quality,
            hours_until_close=hours_until_close,
            avoid_reason=avoid_reason
        )
    
    # =========================================================================
    # 4.5 SLIPPAGE & SPREAD SENTINEL
    # =========================================================================
    
    def check_spread_safety(self, symbol: str, current_spread_pips: float, 
                           target_ob_height_pips: float = 0, 
                           sl_distance_pips: float = 0) -> Tuple[bool, float, str]:
        """
        Vérifie si le spread actuel est acceptable par rapport au setup SMC.
        Empêche de prendre un trade où le coût (spread) détruit le RR.
        
        Règles d'or:
        - Spread ne doit pas dépasser 20% de la hauteur de l'OB.
        - Spread ne doit pas dépasser 15% de la distance du SL.
        """
        if current_spread_pips <= 0: return True, 1.0, "Spread inconnu"
        
        # 1. Protection contre le spread fixe excessif
        max_absolute_spread = 5.0 # Pips (pour Forex standard)
        if "XAU" in symbol: 
            max_absolute_spread = 80.0 # 80 cents pour Gold
        elif "BTC" in symbol:
            max_absolute_spread = 5000.0
        elif "ETH" in symbol:
            max_absolute_spread = 500.0
        elif "US30" in symbol:
            max_absolute_spread = 100.0
        elif "USTEC" in symbol or "NAS100" in symbol:
            max_absolute_spread = 300.0
        elif "JPY" in symbol:
            max_absolute_spread = 3.0 # JPY un peu plus large parfois
        elif "JP225" in symbol:
             max_absolute_spread = 100.0
        
        if current_spread_pips > max_absolute_spread:
            return False, 0.0, f"Spread excessif ({current_spread_pips:.1f} pips)"
            
        # 2. Ratio Coût/OB (SMC spécifique)
        if target_ob_height_pips > 0:
            cost_ratio_ob = current_spread_pips / target_ob_height_pips
            if cost_ratio_ob > 0.50: # Spread bouffe plus de 50% de la zone d'épaulement
                 return False, 0.0, f"Spread trop large vs OB ({cost_ratio_ob*100:.0f}%)"
            elif cost_ratio_ob > 0.25:
                 return True, 0.7, f"Spread significatif vs OB ({cost_ratio_ob*100:.0f}%)"
                 
        # 3. Ratio Coût/SL (Risk Management)
        if sl_distance_pips > 0:
            cost_ratio_sl = current_spread_pips / sl_distance_pips
            if cost_ratio_sl > 0.30: # 30% du risque est déjà perdu au spread
                return False, 0.0, f"Spread trop large vs SL ({cost_ratio_sl*100:.0f}%)"
            elif cost_ratio_sl > 0.15:
                return True, 0.8, f"Spread correct vs SL ({cost_ratio_sl*100:.0f}%)"
                
        return True, 1.0, "Spread Optimal ✓"

    # =========================================================================
    # 5. ENHANCED SIGNAL GENERATION
    # =========================================================================
    
    def enhance_signal(self, df: pd.DataFrame, signal_direction: str,
                      entry_price: float, symbol: str = "UNKNOWN",
                      htf_df: pd.DataFrame = None,
                      analysis: Dict = None,
                      backtest_mode: bool = False,
                      allow_counter_trend_override: bool = None,
                      intermarket_score: float = 0.0) -> EnhancedSignal:
        """
        Améliore un signal avec le Scoring Matriciel SMC.
        """
        reasons = []
        warnings = []
        score_details = {}
        
        # ✅ FIX: Définir pip_value pour les calculs de hauteur et SL/TP
        pip_value = self._get_pip_value(symbol)
        
        # 1. ATR Analysis (Fondation)
        atr_info = self.calculate_atr(df, symbol)
        
        # Volatilité extrême -> Rejet direct
        if atr_info.volatility_ratio > 3.0:
            return self._create_rejected_signal(signal_direction, entry_price, atr_info, "Volatilité EXTRÊME")

        # --- SYSTÈME DE SCORING MATRICIEL (MASTER SCORING) ---
        
        # A. Alignement Structure (Max: 35 pts)
        policy_allow_ct = allow_counter_trend_override if allow_counter_trend_override is not None else self.allow_counter_trend
        structure = self.validate_structure(df, htf_df, signal_direction, allow_counter_trend=policy_allow_ct)
        
        struct_score = 0
        if structure.is_aligned:
            struct_score = 35 if structure.alignment_score >= 80 else 25
            reasons.append(f"✓ Structure alignée ({structure.alignment_score})")
        else:
            if not policy_allow_ct:
                return self._create_rejected_signal(signal_direction, entry_price, atr_info, "Contre-tendance interdite")
            struct_score = 10
            warnings.append("⚠️ Contre-tendance détectée")
        score_details['Structure'] = struct_score

        # B. Liquidity Sweeps (Max: 25 pts)
        sweep_score = 0
        pdl_data = analysis.get('pdl', {}) if analysis else {}
        asian_data = analysis.get('asian_range', {}) if analysis else {}
        generic_sweeps = analysis.get('sweeps', []) if analysis else []
        
        has_major_sweep = pdl_data.get('confirmed') or asian_data.get('signal') != "NEUTRAL"
        
        if has_major_sweep:
            sweep_score = 25
            reasons.append("🎯 Major Sweep détecté (PDL/Asian)")
        elif generic_sweeps:
            sweep_score = 15
            reasons.append("🎯 Liquidité locale balayée")
        score_details['Liquidity'] = sweep_score

        # C. SMT Divergence (Max: 15 pts)
        smt_score = 0
        smt_data = analysis.get('smt', {}) if analysis else {}
        if smt_data.get('signal') != 'none' and smt_data.get('signal'):
            smt_score = 15
            reasons.append("🔥 SMT Divergence confirmée")
        score_details['SMT'] = smt_score

        # D. Déséquilibre & Déplacement (Max: 15 pts) - FVG/OB
        imbalance_score = 0
        fvgs = analysis.get('fvgs', []) if analysis else []
        ifvgs = analysis.get('ifvgs', []) if analysis else []
        
        if ifvgs:
            imbalance_score = 15
            reasons.append("⚡ iFVG (Inversion) validée")
        elif fvgs:
            imbalance_score = 10
            reasons.append("✓ FVG présent dans la zone")
        score_details['Imbalance'] = imbalance_score

        # E. Zone Premium/Discount (Max: 10 pts)
        zone_score = 0
        pd_zone = analysis.get('pd_zone') if analysis else None
        if pd_zone:
            zone = pd_zone.current_zone.value.upper()
            if (signal_direction == "BUY" and zone == "DISCOUNT") or \
               (signal_direction == "SELL" and zone == "PREMIUM"):
                zone_score = 10
                reasons.append(f"✓ Prix en zone {zone} (Idéal)")
            elif zone == "EQUILIBRIUM":
                zone_score = 5
                reasons.append("~ Prix à l'équilibre")
        score_details['Zone_PD'] = zone_score

        # F. Confluences Techniques (Bonus: RSI/Volume/Session)
        technical_bonus = 0
        
        # Session Filter
        data_time = df.index[-1].to_pydatetime() if backtest_mode else None
        time_filter = self.check_time_filter(data_time, symbol)
        if time_filter.session_quality == "prime": technical_bonus += 10
        elif time_filter.session_quality == "good": technical_bonus += 5
        
        # Volume Pressure
        vol_analysis = self.check_volume_pressure(df, signal_direction)
        if vol_analysis.is_safe: technical_bonus += 5
        
        # G. Slippage & Spread Sentinel (Filtre Sécurité)
        spread_info = analysis.get('current_tick', {})
        current_spread = spread_info.get('spread', 0)
        
        # Récupérer hauteur OB ou FVG pour le ratio
        target_height = 0
        if analysis.get('order_blocks'):
            # On prend la hauteur du dernier OB pertinent
            relevant_obs = analysis.get('bullish_obs' if signal_direction == "BUY" else 'bearish_obs', [])
            if relevant_obs:
                target_height = relevant_obs[-1].height / pip_value
        
        # Calcul distance SL approximative
        sl_dist = atr_info.suggested_sl_pips
        
        is_spread_safe, spread_mult, spread_reason = self.check_spread_safety(
            symbol, current_spread, target_height, sl_dist
        )
        
        score_details['Spread_Sentinel'] = 0 # Pas un score positif, mais peut rejeter
        if not is_spread_safe:
            return self._create_rejected_signal(signal_direction, entry_price, atr_info, spread_reason)
        
        # 2. Momentum
        momentum_score = self._check_momentum(df, signal_direction)
        score_details['Momentum'] = momentum_score
        
        # 3. Confirmation Multi-Bougies
        confirmation = self.check_confirmation(df, signal_direction)
        if confirmation.is_confirmed:
            score_details['Confirmation'] = min(25, confirmation.strength / 4)
            reasons.append(f"Confirmation {signal_direction} ({confirmation.candles_confirmed} bougies) ✓")
            
        # 4. Pro Confluences (NOUVEAU)
        # 4.1 Round Numbers
        if self.check_round_numbers(entry_price, symbol):
            score_details['Round Number'] = 5.0
            reasons.append("💎 Confluence Niveau Institutionnel (Round Number) ✓")
            is_near_round = True
        else:
            is_near_round = False
            
        # 4.2 ADR Exhaustion
        adr_pct = self.check_adr_exhaustion(df, htf_df)
        if adr_pct > 85:
            score_details['ADR Exhaustion'] = -15.0
            warnings.append(f"⚠️ ADR Épuisé ({adr_pct:.1f}%) - Risque de stagnation")
        elif adr_pct < 30:
            score_details['ADR Freshness'] = 5.0 # Pas encore beaucoup bougé, potentiel intact
            
        # 5. Volume Analysis
        vol_analysis = self.check_volume_pressure(df, signal_direction)
        if vol_analysis.is_safe:
            score_details['Volume'] = 15.0
            reasons.append(f"Volume OK ({vol_analysis.pressure_direction} pressure) ✓")
        else:
            score_details['Volume'] = -10.0
            warnings.append(f"⚠️ Volume suspect: {vol_analysis.reason}")
            
        # 6. Intermarket Confluence (NOUVEAU)
        if (signal_direction == "BUY" and intermarket_score > 30) or \
           (signal_direction == "SELL" and intermarket_score < -30):
            score_details['Intermarket'] = 10.0
            reasons.append(f"💎 Intermarket Confluence ({intermarket_score:.1f}) ✓")
        elif (signal_direction == "BUY" and intermarket_score < -30) or \
             (signal_direction == "SELL" and intermarket_score > 30):
            score_details['Intermarket'] = -10.0
            warnings.append(f"⚠️ Conflit Intermarket ({intermarket_score:.1f})")
            
        # Calcul du score final (0-100)
        final_confidence = sum(score_details.values())
        final_confidence = max(0, min(100, final_confidence))
        
        # Déterminer la qualité finale
        quality = SignalQuality.REJECT
        for q, threshold in sorted(self.quality_thresholds.items(), key=lambda x: x[1], reverse=True):
            if final_confidence >= threshold:
                quality = SignalQuality[q.replace("+", "_PLUS")]
                break
                
        # Calculer le multiplicateur de position
        multiplier_map = {
            SignalQuality.A_PLUS: 1.0,
            SignalQuality.A: 0.8,
            SignalQuality.B: 0.5,
            SignalQuality.C: 0.3,
            SignalQuality.REJECT: 0.0
        }
        position_multiplier = multiplier_map.get(quality, 0.0)
        
        # Calculer SL/TP (ATR dynamique)
        if signal_direction == "BUY":
            stop_loss = entry_price - (atr_info.suggested_sl_pips * pip_value)
            take_profit = entry_price + (atr_info.suggested_tp_pips * pip_value)
        else:
            stop_loss = entry_price + (atr_info.suggested_sl_pips * pip_value)
            take_profit = entry_price - (atr_info.suggested_tp_pips * pip_value)

        logger.info(f"[{symbol}] Master Scoring: {final_confidence} pts | Quality: {quality.value}")

        # Retourner le signal amélioré
        return EnhancedSignal(
            original_direction=signal_direction,
            final_direction=signal_direction if quality != SignalQuality.REJECT else "NEUTRAL",
            quality=quality,
            confidence=final_confidence,
            score_details=score_details,
            atr_info=atr_info,
            confirmation=confirmation,
            structure=structure,
            time_filter=time_filter,
            volume_analysis=vol_analysis,
            spread_info={'value': current_spread, 'reason': spread_reason},
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_multiplier=position_multiplier,
            adr_exhaustion=adr_pct,
            is_near_round_number=is_near_round,
            reasons=reasons,
            warnings=warnings
        )

    def _create_rejected_signal(self, dir, price, atr, reason) -> EnhancedSignal:
        return EnhancedSignal(
            original_direction=dir, final_direction="NONE",
            quality=SignalQuality.REJECT, confidence=0, score_details={},
            atr_info=atr, confirmation=None, structure=None,
            time_filter=None, volume_analysis=None,
            spread_info={'value': 0, 'reason': 'rejected'}, # ✅ FIX: Add missing required field
            entry_price=price, stop_loss=price, take_profit=price,
            position_size_multiplier=0.0, reasons=[], warnings=[f"🚫 REJET: {reason}"]
        )
    
    def _get_pip_value(self, symbol: str) -> float:
        """Retourne la valeur d'un pip pour le symbole."""
        if "JPY" in symbol:
            return 0.01
        elif "XAU" in symbol:
            return 0.01  # XAUUSD pip = $0.01
        elif "BTC" in symbol or "ETH" in symbol:
            return 0.01  # Crypto pip = 0.01
        else:
            return 0.0001


# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================

def should_take_trade(enhanced: EnhancedSignal) -> Tuple[bool, str]:
    """
    Décide si un trade doit être pris basé sur le signal amélioré.
    
    Returns:
        (should_trade, reason)
    """
    if enhanced.quality == SignalQuality.REJECT:
        reason = enhanced.warnings[0] if enhanced.warnings else "Signal de qualité insuffisante"
        return False, reason
    
    if enhanced.quality == SignalQuality.C:
        # Trade C seulement si plusieurs conditions sont bonnes
        if len(enhanced.warnings) > 2:
            return False, "Trop d'avertissements pour un signal C"
    
    if not enhanced.time_filter.is_optimal_time:
        if enhanced.quality not in [SignalQuality.A_PLUS, SignalQuality.A]:
            return False, f"Mauvais timing: {enhanced.time_filter.avoid_reason}"
    
    return True, f"Signal {enhanced.quality.value} validé"


def get_position_size(base_lot: float, enhanced: EnhancedSignal, 
                     max_lot: float = 1.0) -> float:
    """
    Calcule la taille de position basée sur la qualité du signal.
    
    Args:
        base_lot: Lot de base configuré
        enhanced: Signal amélioré
        max_lot: Lot maximum autorisé
        
    Returns:
        Taille de lot ajustée
    """
    adjusted = base_lot * enhanced.position_size_multiplier
    return min(adjusted, max_lot)
