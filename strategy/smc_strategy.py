"""
SMC Trading Strategy
Stratégie principale combinant tous les concepts SMC
"""

import pandas as pd
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
from loguru import logger
from datetime import datetime

from core.market_structure import MarketStructure, Trend
from core.order_blocks import OrderBlockDetector, OBType
from core.fair_value_gap import FVGDetector, FVGType
from core.liquidity import LiquidityDetector
from core.premium_discount import PremiumDiscountZones, ZoneType
from core.ote import OTECalculator
from core.breaker import BreakerBlockDetector, BreakerType
from core.killzones import KillzoneDetector, AsianRangeSweepDetector
from core.previous_day_levels import PreviousDayLiquidityDetector
from core.silver_bullet import NYSilverBulletStrategy
from core.amd_detector import AMDDetector
from core.advanced_filters import AdvancedFilters, should_take_trade, get_position_size, SignalQuality
from core.smc_state import SMCStateMachine, SMCStage
from core.smc_state import SMCStateMachine, SMCStage
from core.smt_detector import SMTDetector, SMTType
from strategy.momentum_confirmation import MomentumConfirmationFilter # ⚡ Check Momentum

# 🆕 OPTIMISATIONS RENTABILITÉ (Phase 5)
from core.trend_strength_filter import TrendStrengthFilter  # Filtre ADX
from utils.spread_guard import SpreadGuard  # Protection spread

# 🌍 NOUVEAU: Analyse Fondamentale (Phase 2)
try:
    from core.fundamental_filter import FundamentalFilter
    FUNDAMENTAL_AVAILABLE = True
except ImportError:
    FUNDAMENTAL_AVAILABLE = False
    logger.warning("⚠️ Fundamental Filter non disponible (modules manquants)")



class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    NO_SIGNAL = "no_signal"


@dataclass
class TradeDecision:
    """Bulletin de décision pour le logging et le dashboard"""
    symbol: str
    timestamp: str
    signal_type: str
    final_score: float
    is_taken: bool = False
    rejection_reason: str = ""
    
    def __init__(self, symbol, timestamp, signal_type, final_score):
        self.symbol = symbol
        self.timestamp = timestamp
        self.signal_type = signal_type
        self.final_score = final_score
        self.metadata = {}
        self.components = {}
        self.is_taken = False
        self.rejection_reason = ""

    def log(self):
        status = "TAKEN" if self.is_taken else f"REJECTED ({self.rejection_reason})"
        logger.info(f"[{self.symbol}] Decision: {status} | Score: {self.final_score:.1f}")
        for k, v in self.metadata.items():
            logger.debug(f"   - {k}: {v}")


@dataclass
class TradeSignal:
    signal_type: SignalType
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    reasons: List[str]
    timestamp: pd.Timestamp
    is_secondary: bool = False      # True si signal iFVG (secondaire)
    lot_multiplier: float = 1.0     # Multiplicateur de lot (0.5 pour signaux secondaires)
    
    @property
    def risk_reward(self) -> float:
        if self.signal_type == SignalType.BUY:
            risk = self.entry_price - self.stop_loss
            reward = self.take_profit - self.entry_price
        else:
            risk = self.stop_loss - self.entry_price
            reward = self.entry_price - self.take_profit
        return reward / risk if risk > 0 else 0


class SMCStrategy:
    """
    Stratégie de trading basée sur les Smart Money Concepts.
    
    Combine:
    - Market Structure (BOS/CHoCH)
    - Order Blocks
    - Fair Value Gaps
    - Liquidity Sweeps
    - Premium/Discount Zones
    - OTE (Optimal Trade Entry)
    - Breaker Blocks
    """
    
    def __init__(self, config: Dict[str, Any], discord_notifier=None, mt5_api=None):
        self.config = config
        self.discord = discord_notifier
        self.mt5_api = mt5_api
        
        # Initialiser les détecteurs SMC
        smc_config = config.get('smc', {})
        
        self.market_structure = MarketStructure(
            swing_strength=smc_config.get('structure', {}).get('swing_strength', 5),
            min_impulse_pips=smc_config.get('structure', {}).get('min_impulse_pips', 10)
        )
        
        self.ob_detector = OrderBlockDetector(
            max_age_bars=smc_config.get('order_blocks', {}).get('max_age_bars', 50),
            min_imbalance_ratio=smc_config.get('order_blocks', {}).get('min_imbalance_ratio', 1.5)
        )
        
        self.fvg_detector = FVGDetector(
            min_gap_pips=smc_config.get('fvg', {}).get('min_gap_pips', 5),
            max_age_bars=smc_config.get('fvg', {}).get('max_age_bars', 30)
        )
        
        self.liquidity_detector = LiquidityDetector(
            equal_level_pips=smc_config.get('liquidity', {}).get('equal_level_pips', 3)
        )
        
        self.pd_zones = PremiumDiscountZones(
            equilibrium_buffer=smc_config.get('premium_discount', {}).get('equilibrium_buffer', 5)
        )
        
        self.ote_calculator = OTECalculator(
            fib_start=smc_config.get('ote', {}).get('fib_start', 0.618),
            fib_end=smc_config.get('ote', {}).get('fib_end', 0.786)
        )
        
        self.breaker_detector = BreakerBlockDetector()
        
        # Initialiser les nouveaux détecteurs ICT avancés
        filters_config = config.get('filters', {})
        kz_config = filters_config.get('killzones', {})
        timezone_offset = kz_config.get('timezone_offset', 2)
        
        self.killzone_detector = KillzoneDetector(
            timezone_offset=timezone_offset,
            enabled=kz_config.get('enabled', True)
        )
        
        self.asian_sweep_detector = AsianRangeSweepDetector(
            killzone_detector=self.killzone_detector,
            sweep_buffer_pips=smc_config.get('asian_sweep', {}).get('buffer_pips', 3.0),
            confirmation_pips=smc_config.get('asian_sweep', {}).get('confirmation_pips', 5.0)
        )
        
        self.pdl_detector = PreviousDayLiquidityDetector(
            buffer_pips=smc_config.get('previous_day', {}).get('buffer_pips', 2.0),
            timezone_offset=timezone_offset
        )
        
        # Initialiser NY Silver Bullet Strategy
        silver_bullet_config = smc_config.get('silver_bullet', {})
        self.silver_bullet = NYSilverBulletStrategy(
            timezone_offset=timezone_offset,
            use_pm_window=silver_bullet_config.get('use_pm_window', False),
            min_sweep_pips=silver_bullet_config.get('min_sweep_pips', 5.0),
            fvg_detector=self.fvg_detector,
            pdl_detector=self.pdl_detector
        )
        
        # Initialiser AMD Detector (Phase 3)
        amd_config = smc_config.get('amd', {})
        self.amd_detector = AMDDetector(
            min_range_bars=amd_config.get('min_range_bars', 8),
            max_range_percentage=amd_config.get('max_range_percentage', 1.5),
            sweep_buffer_pips=amd_config.get('sweep_buffer_pips', 3.0),
            confirmation_bars=amd_config.get('confirmation_bars', 2)
        )
        
        # Initialiser SMT Detector
        self.smt_detector = SMTDetector(smc_config.get('smt', {}))

        
        # Configuration des entrées
        self.entry_config = config.get('entry', {})
        self.exit_config = config.get('exit', {})
        
        # Confiance minimale (configurable) - 90% = haute qualité uniquement
        self.min_confidence = self.entry_config.get('min_confidence', 90)
        self.equilibrium_extra_confirmation = self.entry_config.get('equilibrium_extra_confirmation', True)
        
        # Cache par symbole pour les détecteurs
        self._symbol_caches = {}
        
        # Configuration par symbole (OPTIMIZED based on backtest)
        self._symbol_configs = self._build_symbol_configs()
        
        # NOUVEAU: Filtres avancés pour améliorer la qualité des signaux
        adv_settings = config.get('advanced_filters', {})
        advanced_config = {
            'atr_period': adv_settings.get('atr', {}).get('period', 14),
            'atr_multiplier_sl': adv_settings.get('atr', {}).get('multiplier_sl', 1.0),
            'atr_multiplier_tp': adv_settings.get('atr', {}).get('multiplier_tp', 2.0),
            'min_confirmation_candles': adv_settings.get('confirmation', {}).get('min_candles', 1),
            'timezone_offset': filters_config.get('killzones', {}).get('timezone_offset', 2),
            'allow_counter_trend': adv_settings.get('structure', {}).get('allow_counter_trend', False)
        }
        self.advanced_filters = AdvancedFilters(advanced_config)
        
        # ✅ MACHINE D'ÉTAT INSTITUTIONNELLE (Sequencing)
        self.state_machine = SMCStateMachine(expiration_bars=60)
        logger.info("✅ Advanced Filters initialized for enhanced signal quality")
        
        # 🌍 NOUVEAU: Filtre Fondamental (Phase 2)
        if FUNDAMENTAL_AVAILABLE:
            self.fundamental_filter = FundamentalFilter(config, discord_notifier=self.discord, mt5_api=self.mt5_api)
            logger.info("🌍 Fundamental Filter: Initialisé avec succès")
        else:
            self.fundamental_filter = None
            logger.info("🌍 Fundamental Filter: DÉSACTIVÉ (modules non installés)")

        # ⚡ NOUVEAU: Filtre Momentum (Phase 4)
        self.momentum_filter = MomentumConfirmationFilter(config)
        logger.info("⚡ Momentum Filter: Initialisé")

        # 🆕 OPTIMISATIONS RENTABILITÉ (Phase 5)
        # Filtre ADX (tendance forte)
        adx_config = smc_config.get('trend_strength', {})
        if adx_config.get('enabled', False):
            self.trend_strength_filter = TrendStrengthFilter(adx_config)
            logger.info(f"🎯 Trend Strength Filter (ADX): Initialisé (min_adx={adx_config.get('min_adx', 25)})")
        else:
            self.trend_strength_filter = None
            logger.info("🎯 Trend Strength Filter: Désactivé")
        
        # Spread Guard
        self.spread_guard = SpreadGuard({
            'max_spread_pips': config.get('risk', {}).get('max_spread_pips', 2.0)
        })
        logger.info("🛡️ Spread Guard: Initialisé")

        # Symbol-specific configs cache
        self._symbol_configs = self._build_symbol_configs()

        
    def _detect_asset_class(self, symbol: str) -> str:
        """Détecte la classe d'actif basée sur le nom du symbole."""
        s = symbol.upper()
        
        # Crypto
        if any(c in s for c in ['BTC', 'ETH', 'SOL', 'XRP', 'LTC', 'BNB', 'CRYPTO']):
            return 'crypto'
            
        # Commodities
        if any(c in s for c in ['XAU', 'XAG', 'WTI', 'BRENT', 'OIL', 'GOLD', 'SILVER']):
            return 'commodity'
            
        # Indices
        if any(c in s for c in ['US30', 'NAS100', 'USTEC', 'NAS', 'US500', 'SPX', 'GER30', 'DE30', 'UK100']):
            return 'indices'
            
        # Default to Forex Major (safe bet for standard pairs)
        return 'forex_major'

    def _build_symbol_configs(self) -> Dict[str, Dict]:
        """
        Construit la configuration optimisée par symbole.
        Charge les profils d'actifs (Forex, Crypto, Commodity) pour adapter
        les paramètres SMC et Risk à la volatilité spécifique.
        """
        import yaml
        from pathlib import Path
        
        symbols_config = {}
        profiles = {}
        
        # 1. Charger les profils d'actifs
        try:
            profile_path = Path("config/assets/profiles.yaml")
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profiles = yaml.safe_load(f)
                logger.info("✅ Asset profiles loaded successfully")
            else:
                logger.warning("⚠️ config/assets/profiles.yaml not found - Using default parameters")
        except Exception as e:
            logger.error(f"❌ Error loading asset profiles: {e}")
        
        # 2. Construire la config pour chaque symbole
        for symbol_data in self.config.get('symbols', []):
            name = symbol_data.get('name', '')
            strategies = symbol_data.get('strategies', {})
            
            # Déterminer le profil
            asset_class = self._detect_asset_class(name)
            profile_data = profiles.get(asset_class, {})
            
            logger.debug(f"[{name}] Asset Class detected: {asset_class}")
            
            # Fusionner les stratégies: Profil > Config Global
            profile_strategies = profile_data.get('strategies', {})
            
            # Stratégies effectives
            use_pdh_pdl = profile_strategies.get('pdh_pdl_sweep', strategies.get('pdh_pdl_sweep', True))
            use_asian = profile_strategies.get('asian_range_sweep', strategies.get('asian_range_sweep', True))
            use_fvg_entry = profile_strategies.get('fvg_entry', strategies.get('fvg_entry', False))
            use_silver = profile_strategies.get('silver_bullet', strategies.get('silver_bullet', True))
            use_amd = profile_strategies.get('amd', strategies.get('amd', True))
            use_smt = profile_strategies.get('smt', strategies.get('smt', True))

            # Configuration de base
            sym_cfg = {
                'enabled': symbol_data.get('enabled', True),
                'asset_class': asset_class,
                'is_crypto': asset_class == 'crypto',
                # Stratégies (Merged)
                'pdh_pdl_sweep': use_pdh_pdl,
                'asian_range_sweep': use_asian,
                'fvg_entry': use_fvg_entry,
                'silver_bullet': use_silver,
                'amd': use_amd,
                'smt': use_smt,
                'confluence_required': symbol_data.get('confluence_required', 2),
                
                # Paramètres techniques (Override du profil)
                'smc_settings': profile_data.get('smc', {}),
                'risk_settings': profile_data.get('risk', {})
            }
            
            symbols_config[name] = sym_cfg

        
        # Default config for unknown symbols
        default_profile = profiles.get('forex_major', {})
        symbols_config['DEFAULT'] = {
            'enabled': True,
            'asset_class': 'forex_major',
            'is_crypto': False,
            'pdh_pdl_sweep': True,
            'asian_range_sweep': True,
            'fvg_entry': False,
            'silver_bullet': True,
            'amd': True,
            'confluence_required': 2,
            'smc_settings': default_profile.get('smc', {}),
            'risk_settings': default_profile.get('risk', {})
        }
        
        logger.info(f"Symbol configs loaded for: {list(symbols_config.keys())}")
        return symbols_config
    
    def get_symbol_config(self, symbol: str) -> Dict:
        """
        Retourne la configuration spécifique au symbole.
        Gère les suffixes (ex: XAUUSDm -> XAUUSD).
        """
        # 1. Essai exact
        if symbol in self._symbol_configs:
            return self._symbol_configs[symbol]
        
        # 2. Essai sans suffixe (ex: XAUUSDm -> XAUUSD)
        # Suffixes courants: m, pro, c, ., _
        import re
        # Nettoyer le symbole des suffixes courants
        clean_symbol = re.sub(r'[m|c|pro|\.|\_]+$', '', symbol)
        
        if clean_symbol in self._symbol_configs:
            logger.debug(f"Config found for {symbol} using base name {clean_symbol}")
            return self._symbol_configs[clean_symbol]
        
        # 3. Essai partiel (si XAUUSD est dans le nom)
        for config_name in self._symbol_configs:
            if config_name in symbol and len(config_name) > 3:
                logger.debug(f"Config match found: {symbol} -> {config_name}")
                return self._symbol_configs[config_name]
                
        return self._symbol_configs['DEFAULT']
    
    def is_strategy_enabled(self, symbol: str, strategy: str) -> bool:
        """Vérifie si une stratégie est activée pour ce symbole."""
        config = self.get_symbol_config(symbol)
        return config.get(strategy, False)
        
    def analyze(self, df: pd.DataFrame, htf_df: pd.DataFrame = None, mtf_df: pd.DataFrame = None, symbol: str = "UNKNOWN", df_smt: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Analyse complète du marché avec tous les concepts SMC.
        
        Args:
            df: DataFrame LTF (M15)
            htf_df: DataFrame HTF (D1) - Contexte Macro
            mtf_df: DataFrame MTF (H4) - Structure Intermédiaire ✅
            symbol: Symbole en cours d'analyse
            df_smt: DataFrame de l'actif corrélé pour SMT (optionnel)
        """

        logger.info("Running SMC analysis...")
        
        # Reset des détecteurs pour ce symbole (éviter la contamination entre symboles)
        self._reset_symbol_specific_detectors(symbol)

        # APPLY SYMBOL SPECIFIC CONFIGURATION (PROFILES)
        # Ceci adapte les seuils de détection à la volatilité de l'actif (Crypto vs Forex vs Gold)
        sym_config = self.get_symbol_config(symbol)
        smc_settings = sym_config.get('smc_settings', {})
        
        if smc_settings:
            # 1. Update Market Structure settings
            if 'structure' in smc_settings:
                s_cfg = smc_settings['structure']
                if hasattr(self.market_structure, 'swing_length'):
                    self.market_structure.swing_length = s_cfg.get('swing_length', 5)
            
            # 2. Update Liquidity settings
            if 'liquidity' in smc_settings:
                l_cfg = smc_settings['liquidity']
                if hasattr(self.liquidity_detector, 'lookback_bars'):
                    self.liquidity_detector.lookback_bars = l_cfg.get('sweep_lookback', 20)
                if hasattr(self.liquidity_detector, 'min_wick_ratio'):
                    self.liquidity_detector.min_wick_ratio = l_cfg.get('min_wick_ratio', 0.3)
                    
            # 3. Update FVG settings
            if 'fvg' in smc_settings:
                f_cfg = smc_settings['fvg']
                if hasattr(self.fvg_detector, 'min_gap_pips'):
                    self.fvg_detector.min_gap_pips = f_cfg.get('min_size_pips', 2.0)
                if hasattr(self.fvg_detector, 'mitigation_threshold'):
                    self.fvg_detector.mitigation_threshold = f_cfg.get('mitigation_threshold', 0.5)
        
        # 1. Analyser la structure de marché LTF
        structure = self.market_structure.analyze(df)
        
        # 2. Détecter les Order Blocks avec mitigation activée pour identifier les cassés
        order_blocks = self.ob_detector.detect(df, structure.get('structure_breaks'))
        
        # 3. Détecter les Breaker Blocks à partir des Order Blocks cassés
        from core.order_blocks import OBStatus
        broken_obs = [ob for ob in order_blocks if ob.status == OBStatus.INVALIDATED]
        breaker_blocks = self.breaker_detector.detect_from_broken_obs(df, broken_obs)
        
        # 4. Détecter les FVG
        fvgs, ifvgs = self.fvg_detector.detect(df)
        
        # 4. Détecter la liquidité
        swing_highs = structure.get('swing_highs', [])
        swing_lows = structure.get('swing_lows', [])
        
        # ✅ FIX: Passer la valeur de pip correcte pour le symbole (ex: JPY = 0.01)
        pip_val = self._get_pip_value(symbol)
        liquidity_zones, sweeps = self.liquidity_detector.detect(df, swing_highs, swing_lows, pip_value=pip_val)
        
        # 5. Calculer Premium/Discount
        last_hh = structure.get('last_hh')
        last_ll = structure.get('last_ll')
        if last_hh and last_ll:
            hh_price = last_hh.price if hasattr(last_hh, 'price') else last_hh
            ll_price = last_ll.price if hasattr(last_ll, 'price') else last_ll
            pd_zone = self.pd_zones.calculate(df, swing_high=hh_price, swing_low=ll_price)
        else:
            pd_zone = self.pd_zones.calculate(df)
        
        # 6. Analyser HTF (D1) - CONTEXTE
        htf_bias = None
        if htf_df is not None:
            htf_structure = self.market_structure.analyze(htf_df)
            htf_bias = self.market_structure.get_bias()
            htf_trend = htf_structure.get('current_trend')
        else:
            htf_trend = Trend.RANGING
            
        # 🚀 OVERRIDE HTF BIAS (Bull Run / Bear Run Force)
        sym_cfg = self.get_symbol_config(symbol)
        fixed_htf_bias = sym_cfg.get('smc_settings', {}).get('structure', {}).get('fixed_htf_bias')
        
        if fixed_htf_bias:
            if fixed_htf_bias.upper() in ["BULLISH", "BUY"]:
                htf_trend = Trend.BULLISH
                htf_bias = "BUY"
                # logger.debug(f"[{symbol}] HTF Trend Forced: BULLISH")
            elif fixed_htf_bias.upper() in ["BEARISH", "SELL"]:
                htf_trend = Trend.BEARISH
                htf_bias = "SELL"
            
        # 7. Analyser MTF (H4) - STRUCTURE ✅
        mtf_bias = None
        mtf_structure = None
        if mtf_df is not None:
            mtf_structure = self.market_structure.analyze(mtf_df)
            mtf_bias = self.market_structure.get_bias()
        
        # 7. Calculer Previous Day Liquidity (PDH/PDL)
        current_price = df.iloc[-1]['close']
        pdl_levels = self.pdl_detector.calculate_previous_day_levels(df)
        pdl_sweep = self.pdl_detector.check_sweep(current_price)
        pdl_confirmed = self.pdl_detector.confirm_sweep(current_price)
        pdl_bias, pdl_reason = self.pdl_detector.get_trading_bias(current_price)
        
        # ✅ DEBUG: Tracer la confirmation des sweeps
        if pdl_sweep:
            logger.debug(f"[{symbol}] PDL Sweep détecté: {pdl_sweep.sweep_type.value}")
        if pdl_confirmed:
            logger.info(f"[{symbol}] ✅ PDL Sweep CONFIRMÉ: {pdl_confirmed.sweep_type.value} → {pdl_confirmed.direction_after}")
        elif pdl_sweep and not pdl_confirmed:
            logger.debug(f"[{symbol}] ⏳ PDL Sweep en attente de confirmation...")
        
        # 8. Calculer Asian Range Sweep
        asian_sweep_signal, asian_confidence, asian_reason = self.asian_sweep_detector.get_sweep_signal(
            current_price, df
        )
        asian_status = self.asian_sweep_detector.get_asian_range_status()
        
        # ✅ NOUVEAU: Déterminer si un sweep est confirmé pour override le biais
        sweep_confirmed = False
        sweep_direction = None
        
        # Vérifier PDL sweep confirmé (pdl_confirmed est un objet SweepEvent ou None)
        if pdl_confirmed is not None:
            sweep_confirmed = True
            sweep_direction = pdl_bias if pdl_bias != "NEUTRAL" else None
            logger.info(f"🎯 PDL sweep CONFIRMÉ détecté - Direction: {sweep_direction}")
        # ✅ FALLBACK: Si pas confirmé mais détecté récemment, utiliser quand même
        elif pdl_sweep is not None and pdl_bias != "NEUTRAL":
            sweep_confirmed = True
            sweep_direction = pdl_bias
            logger.info(f"🎯 PDL sweep DÉTECTÉ (non confirmé) - Direction: {sweep_direction}")
        
        # Vérifier Asian sweep confirmé
        if asian_sweep_signal != "NEUTRAL":
            sweep_confirmed = True
            sweep_direction = asian_sweep_signal
            logger.info(f"🎯 Asian sweep détecté - Direction: {sweep_direction}")
        
        # Déterminer le biais COMBINÉ (tendance + zone P/D + sweeps)
        trend = structure.get('current_trend')
        trend_str = trend.value if trend else None
        
        # 10. iFVG Signal (Calculé AVANT le biais pour permettre l'override)
        ifvg_signal, ifvg_confidence, ifvg_reason = self.fvg_detector.get_ifvg_signal(current_price, trend_str)
        
        # --- NOUVEAU: Momentum Analysis for State Machine ---
        # Calcul RSI rapide pour alimenter la machine d'état
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        current_rsi = rsi_series.iloc[-1]
        
        # Calcul du biais avec exception iFVG supportée
        combined_bias = self._calculate_combined_bias(trend, pd_zone, sweep_confirmed, sweep_direction, ifvg_signal, ifvg_confidence, rsi_value=current_rsi)
        
        # 9. NY Silver Bullet Analysis
        pdl_info = self.pdl_detector.get_levels_info()
        silver_bullet_setup = self.silver_bullet.analyze(
            df, 
            structure=structure,
            pdh=pdl_info.get('pdh'),
            pdl=pdl_info.get('pdl')
        )
        
        momentum_data = {
            'rsi': current_rsi,
            'is_extreme': current_rsi > 70 or current_rsi < 30,
            'reversal_bias': "SELL" if current_rsi > 70 else ("BUY" if current_rsi < 30 else "NEUTRAL"),
            'context': "BULLISH" if current_rsi > 50 else "BEARISH"
        }
        
        # 11. AMD Analysis (Phase 3 - Accumulation, Manipulation, Distribution)
        amd_setup = self.amd_detector.analyze(df, symbol=symbol)
        
        # 12. SMT Analysis
        smt_signal = SMTType.NONE
        smt_reason = "Non calculé"
        if df_smt is not None:
            smt_config = self.config.get('smc', {}).get('smt', {}).get('pairs', {}).get(symbol)
            if smt_config:
                smt_signal, smt_reason = self.smt_detector.detect(
                    df, df_smt, 
                    correlation_type=smt_config.get('type', 'positive'),
                    main_sweeps=sweeps
                )

        
        # 12. UPDATE STATE MACHINE (Sequential Logic)
        self.state_machine.update(symbol, current_price, {
            'structure': structure,
            'pdl': {'confirmed': pdl_confirmed, 'bias': pdl_bias, 'sweep': pdl_sweep},
            'asian_range': {'signal': asian_sweep_signal},
            'pd_zone': pd_zone,
            'silver_bullet': {'status': silver_bullet_setup.phase.value},
            'fvgs': fvgs,
            'ifvgs': ifvgs
        })
        current_state = self.state_machine.get_state(symbol)
        
        # Killzone Info
        kz_info = self.killzone_detector.get_killzone_info(df)
        
        # 14. TRIPLE TIMEFRAME ALIGNMENT (TTA)
        # Biais idéal: HTF (Trend) + MTF (Bias) + LTF (Bias)
        tta_aligned = False
        if htf_trend != Trend.RANGING and mtf_bias is not None:
            # Pour un BUY: HTF Bullish + MTF Bullish + LTF Bullish
            if combined_bias == "BUY" and mtf_bias == "BUY" and htf_trend == Trend.BULLISH:
                tta_aligned = True
            # Pour un SELL: HTF Bearish + MTF Bearish + LTF Bearish
            elif combined_bias == "SELL" and mtf_bias == "SELL" and htf_trend == Trend.BEARISH:
                tta_aligned = True
        
        analysis = {
            'structure': structure,
            'trend': trend,
            'trend_bias': self.market_structure.get_bias(),  # Biais basé uniquement sur la tendance
            'bias': combined_bias,  # Biais combiné (tendance + zone)
            'htf_bias': htf_bias,
            'htf_trend': htf_trend,
            'mtf_bias': mtf_bias,   # ✅ AJOUT: Biais MTF (H4)
            'tta_aligned': tta_aligned, # ✅ AJOUT: Alignement 3x Timeframes
            'breaker_blocks': breaker_blocks,
            'order_blocks': order_blocks,
            'bullish_obs': self.ob_detector.get_bullish_obs(),
            'bearish_obs': self.ob_detector.get_bearish_obs(),
            'fvgs': fvgs,
            'ifvgs': ifvgs,
            'liquidity_zones': liquidity_zones,
            'sweeps': sweeps,
            'pd_zone': pd_zone,
            'pd_zone_raw': pd_zone.upper_threshold if hasattr(pd_zone, 'upper_threshold') else 50,
            'silver_bullet': {
                'confidence': silver_bullet_setup.confidence,
                'reasons': silver_bullet_setup.reasons,
                'status': silver_bullet_setup.phase.value
            },
            'ifvg': {
                'signal': ifvg_signal,
                'confidence': ifvg_confidence,
                'reason': ifvg_reason,
                'zones': self.fvg_detector.get_all_zones_info()
            },
            # Phase 3: AMD (Accumulation-Manipulation-Distribution)
            'amd': {
                'phase': amd_setup.phase.value,
                'direction': amd_setup.direction,
                'confidence': amd_setup.confidence,
                'reasons': amd_setup.reasons,
                'entry_price': amd_setup.entry_price,
                'stop_loss': amd_setup.stop_loss,
                'take_profit': amd_setup.take_profit,
                'status': self.amd_detector.get_status()
            },
            # Institutional State Machine
            'state_machine': {
                'stage': current_state.stage.value,
                'sweep_type': current_state.sweep_type,
                'sweep_direction': current_state.sweep_direction,
                'valid_entry_zone': current_state.valid_entry_zone
            },
            'smt': {
                'signal': smt_signal.value,
                'reason': smt_reason
            },
            'momentum': momentum_data,
            'killzone': {
                'is_killzone': kz_info.is_killzone,
                'current_session': kz_info.current_session.value,
            }
        }
        
        # Get current price from latest candle for backtest compatibility
        current_price = df.iloc[-1]['close']
        
        # Ajouter la configuration du symbole (OPTIMIZED)
        symbol_config = self.get_symbol_config(symbol)
        analysis['symbol_config'] = symbol_config
        analysis['symbol'] = symbol
        analysis['current_price'] = current_price # Add current_price to the analysis dictionary
        
        # Log amélioré avec les nouvelles données
        # Log amélioré avec les nouvelles données
        logger.info(f"Analysis complete - Combined Bias: {combined_bias}, "
                   f"LTF: {trend}, MTF: {mtf_bias}, HTF: {htf_bias}, "
                   f"Zone: {pd_zone.current_zone.value if pd_zone else 'N/A'}, "
                   f"State: {current_state.stage.value}")
        
        # Log des stratégies actives pour ce symbole
        active_strats = [k for k, v in symbol_config.items() if v is True and k != 'enabled']
        logger.debug(f"[{symbol}] Active strategies: {active_strats}")
        
        # Log des nouvelles fonctionnalités si actives ET activées pour ce symbole
        if pdl_levels and symbol_config.get('pdh_pdl_sweep'):
            logger.debug(f"PDH: {pdl_levels.high:.5f} | PDL: {pdl_levels.low:.5f}")
            if pdl_confirmed:
                logger.info(f"[{symbol}] PDL Sweep CONFIRMED - Signal ready")
                
        if asian_status.get('valid') and symbol_config.get('asian_range_sweep'):
            logger.debug(f"Asian Range: {asian_status.get('low', 0):.5f} - {asian_status.get('high', 0):.5f}")
            if asian_sweep_signal != "NEUTRAL":
                logger.info(f"[{symbol}] Asian Sweep: {asian_sweep_signal} - Signal ready")
        
        # Log Silver Bullet si dans la fenêtre et activé
        if silver_bullet_setup.phase.value != 'waiting' and symbol_config.get('silver_bullet'):
            logger.info(f"Silver Bullet: {silver_bullet_setup.phase.value} - {silver_bullet_setup.direction}")
        
        # Log iFVG si signal
        if ifvg_signal != "NEUTRAL":
            logger.info(f"iFVG Signal: {ifvg_signal} (conf: {ifvg_confidence}%) - {ifvg_reason}")
        
        # Log AMD si phase active et activé
        if amd_setup.phase.value != "none" and symbol_config.get('amd'):
            logger.info(f"AMD: Phase {amd_setup.phase.value} - Direction: {amd_setup.direction}")
            
        # Log SMT
        if smt_signal != SMTType.NONE:
            logger.info(f"🔥 SMT Divergence Detected: {smt_signal.value} - {smt_reason}")

        
        return analysis
    
    def _reset_symbol_specific_detectors(self, symbol: str):
        """
        Reset les détecteurs qui sont spécifiques à chaque symbole.
        
        Évite la contamination des données entre symboles différents
        (ex: éviter que le Asian Range de XAUUSD soit utilisé pour EURUSD).
        """
        # Créer un cache pour ce symbole s'il n'existe pas
        if symbol not in self._symbol_caches:
            # Créer des détecteurs dédiés pour ce symbole
            from core.killzones import KillzoneDetector, AsianRangeSweepDetector
            from core.previous_day_levels import PreviousDayLiquidityDetector
            from core.silver_bullet import NYSilverBulletStrategy
            from core.amd_detector import AMDDetector
            
            smc_config = self.config.get('smc', {})
            filters_config = self.config.get('filters', {})
            timezone_offset = filters_config.get('killzones', {}).get('timezone_offset', 0)
            
            # Créer un KillzoneDetector pour ce symbole
            kz_detector = KillzoneDetector(timezone_offset=timezone_offset)
            
            # Configs spécifiques
            asian_config = smc_config.get('asian_sweep', {})
            pdl_config = smc_config.get('previous_day', {})
            sb_config = smc_config.get('silver_bullet', {})
            amd_config = smc_config.get('amd', {})
            
            # Créer les détecteurs avec les bonnes signatures
            asian_sweep = AsianRangeSweepDetector(
                killzone_detector=kz_detector,
                sweep_buffer_pips=asian_config.get('buffer_pips', 3.0),
                confirmation_pips=asian_config.get('confirmation_pips', 5.0)
            )
            
            pdl_detector = PreviousDayLiquidityDetector(
                buffer_pips=pdl_config.get('buffer_pips', 2.0),
                timezone_offset=timezone_offset
            )
            
            silver_bullet = NYSilverBulletStrategy(
                timezone_offset=timezone_offset,
                use_pm_window=sb_config.get('use_pm_window', False),
                min_sweep_pips=sb_config.get('min_sweep_pips', 5.0)
            )
            
            amd_detector = AMDDetector(
                min_range_bars=amd_config.get('min_range_bars', 8),
                max_range_percentage=amd_config.get('max_range_percentage', 1.5),
                sweep_buffer_pips=amd_config.get('sweep_buffer_pips', 3.0),
                confirmation_bars=amd_config.get('confirmation_bars', 2)
            )
            
            self._symbol_caches[symbol] = {
                'last_pdl_date': None,
                'last_asian_date': None,
                'killzone_detector': kz_detector,
                'asian_sweep_detector': asian_sweep,
                'pdl_detector': pdl_detector,
                'silver_bullet': silver_bullet,
                'amd_detector': amd_detector
            }
            logger.info(f"Created dedicated detectors for {symbol}")
        
        # Utiliser les détecteurs du cache pour ce symbole
        cache = self._symbol_caches[symbol]
        self.killzone_detector = cache['killzone_detector']
        self.asian_sweep_detector = cache['asian_sweep_detector']
        self.pdl_detector = cache['pdl_detector']
        self.silver_bullet = cache['silver_bullet']
        self.amd_detector = cache['amd_detector']
        
        logger.debug(f"Using cached detectors for {symbol}")
    
    def _calculate_combined_bias(self, trend: Trend, pd_zone, sweep_confirmed: bool = False, 
                                  sweep_direction: str = None, ifvg_signal: str = "NEUTRAL", 
                                  ifvg_confidence: float = 0.0, rsi_value: float = 50.0) -> str:
        """
        Calcule le biais combiné basé sur tendance + zone Premium/Discount.
        
        ✅ NOUVEAU: Classification Régime de Marché (Force Trend en Impulsion)
        ✅ v2.3: Filtre strict - Vérifier que le sweep est dans la bonne zone
        ✅ v2.5: iFVG Haute Confiance Exception (Assouplissement zone)
        """
        # --- 1. FILTRE RÉGIME DE MARCHÉ (Priorité Absolue) ---
        # Si momentum extrême dans le sens de la tendance = IMPULSION FORTE
        # On interdit tout Reversal (même si Sweep/Discount).
        
        if trend == Trend.BEARISH and rsi_value < 30:
            logger.warning(f"🚨 MARKET REGIME: IMPULSIVE DOWN (RSI={rsi_value:.1f}).")
            if sweep_direction == "BUY":
                logger.warning(f"⚠️ Reversal BUY risqué vs Momentum Impulsif.")
                # On ne bloque plus totalement, mais on flaggue pour réduction de risque
                # return "NEUTRAL" -> CHANGÉ en autorisation sous haute surveillance
                
        if trend == Trend.BULLISH and rsi_value > 70:
            logger.warning(f"🚨 MARKET REGIME: IMPULSIVE UP (RSI={rsi_value:.1f}).")
            if sweep_direction == "SELL":
                 logger.warning(f"⚠️ Reversal SELL risqué vs Momentum Impulsif.")

        # ✅ PRIORITÉ 1.5 (NOUVEAU): iFVG Haute Confiance ALIGNÉ HTF (Golden Setup)
        # Si on a un iFVG très fort (>80%) dans le sens de la tendance HTF, c'est le signal ROI.
        # Il override même les Sweeps qui sont souvent de l'inducement contre une forte tendance.
        if ifvg_signal and ifvg_signal != "NEUTRAL" and ifvg_confidence >= 80.0:
             # On vérifie l'alignement HTF si disponible (passé via un hack ou accessible via self? non, ici méthode statique/pure souvent)
             # On assume que si >80% c'est structurellement validé par le détecteur iFVG
             logger.info(f"⚡⚡ iFVG GOLDEN ({ifvg_confidence}%) détecté - Override PRIORITAIRE sur Sweep")
             return ifvg_signal

        # ✅ PRIORITÉ 2: Si sweep confirmé, vérifier la zone avant d'override
        if sweep_confirmed and sweep_direction:
            # ✅ v2.3: Filtre strict de zone pour les sweeps
            if pd_zone:
                zone = pd_zone.current_zone
                # Vérifier que le sweep est dans une zone acceptable
                if sweep_direction == "BUY" and zone == ZoneType.PREMIUM:
                    logger.warning(f"⚠️ Sweep BUY rejeté - Prix en zone PREMIUM (contre-tendance)")
                    return "NEUTRAL"
                elif sweep_direction == "SELL" and zone == ZoneType.DISCOUNT:
                    logger.warning(f"⚠️ Sweep SELL rejeté - Prix en zone DISCOUNT (contre-tendance)")
                    return "NEUTRAL"
            
            logger.info(f"🎯 Sweep confirmé override biais - Direction: {sweep_direction}")
            return sweep_direction
        
        # ✅ PRIORITÉ 3: iFVG Haute Confiance (Override Zone Conflict)
        if ifvg_signal and ifvg_signal != "NEUTRAL":
            # Seuil de confiance configurable (70% pour override - réduit de 80% pour plus de flexibilité)
            if ifvg_confidence >= 70.0:
                 logger.info(f"⚡ iFVG Haute Confiance ({ifvg_confidence}%) détecté - Override potentiel")
                 # Ici on autorise le biais IFVG car generate_signal appliquera les checks de sécurité
                 return ifvg_signal
        
        if trend is None or pd_zone is None:
            return "NEUTRAL"
        
        zone = pd_zone.current_zone
        
        # Tendance BULLISH
        if trend == Trend.BULLISH:
            if zone == ZoneType.DISCOUNT:
                return "BUY"  # Setup idéal: tendance up + prix bas
            elif zone == ZoneType.EQUILIBRIUM:
                return "BUY"  # Acceptable: tendance up + prix milieu
            else:  # PREMIUM
                logger.debug(f"Tendance bullish mais prix en premium - attente pullback")
                return "NEUTRAL"  # Pas de BUY en premium
        
        # Tendance BEARISH
        elif trend == Trend.BEARISH:
            if zone == ZoneType.PREMIUM:
                return "SELL"  # Setup idéal: tendance down + prix haut
            elif zone == ZoneType.EQUILIBRIUM:
                return "SELL"  # Acceptable: tendance down + prix milieu  
            else:  # DISCOUNT
                logger.debug(f"Tendance bearish mais prix en discount - attente pullback")
                return "NEUTRAL"  # Pas de SELL en discount
        
        # RANGING
        else:
            logger.debug(f"Tendance ranging - pas de biais directionnel")
            return "NEUTRAL"
    
    def generate_signal(self, df: pd.DataFrame, htf_df: pd.DataFrame = None, 
                       symbol: str = "EURUSD", analysis: Dict = None, 
                       current_tick_price: Dict[str, float] = None) -> Optional[TradeSignal]:
        """
        Génère un signal de trading basé sur l'analyse SMC.
        OPTIMISÉ: Utilise la configuration par symbole basée sur le backtest.
        
        Args:
            analysis: Analyse pré-calculée (optionnel, évite double calcul)
            current_tick_price: Prix réel MT5 (bid, ask) pour précision exécution
        """
        # Utiliser l'analyse fournie ou en calculer une nouvelle
        if analysis is None:
            analysis = self.analyze(df, htf_df, symbol=symbol)
        
        # 🆕 FILTRE 1: TENDANCE FORTE (ADX) - Évite trades en ranging
        if self.trend_strength_filter is not None and htf_df is not None:
            adx_result = self.trend_strength_filter.should_trade(htf_df)
            if not adx_result['allowed']:
                logger.debug(f"❌ [{symbol}] {adx_result['reason']} - Trade bloqué")
                return None
        
        # 🆕 FILTRE 2: SPREAD Guard - Évite trades avec frais excessifs
        current_spread = None
        if self.mt5_api and hasattr(self.mt5_api, 'get_spread'):
            try:
                current_spread = self.mt5_api.get_spread(symbol)
            except:
                pass
        
        if current_spread is None:
            # Utiliser spread estimé basé sur symbole
            spread_estimates = {
                'EURUSD': 1.2, 'GBPUSD': 1.8, 'USDJPY': 1.5,
                'XAUUSD': 3.5, 'BTCUSD': 40.0
            }
            symbol_clean = symbol.replace('m', '').replace('.', '')
            current_spread = spread_estimates.get(symbol_clean, 2.0)
        
        spread_result = self.spread_guard.check_spread(symbol, current_spread)
        if not spread_result['allowed']:
            logger.warning(f"❌ [{symbol}] {spread_result['reason']} - Trade bloqué")
            return None
        
        # Récupérer la configuration du symbole (OPTIMIZED)
        symbol_config = self.get_symbol_config(symbol)
        is_crypto = symbol_config.get('is_crypto', False)

        # 🛑 HARD FILTER: Session Asiatique (00h-08h) INTERDITE pour Gold/Forex
        current_ts = analysis.get('timestamp')
        # S'assurer d'avoir un Timestamp valide
        if hasattr(current_ts, 'hour') is False and current_ts is not None:
             current_ts = pd.Timestamp(current_ts)
             
        if current_ts and not is_crypto:
             if 0 <= current_ts.hour < 8:
                 # logger.debug(f"🛑 [{symbol}] Asian Session (00h-08h) -> Trading INTERDIT.")
                 return None

        # Check killzone - only trade during London and NY sessions for FX
        killzone_info = analysis.get('killzone', {})
        if not killzone_info.get('can_trade', True):
            # Exception pour les Cryptos: Trading 24/7 autorisé si le signal est fort
            if is_crypto:
                logger.debug(f"[{symbol}] Crypto détectée - Trading hors killzone autorisé sous haute surveillance.")
            else:
                logger.debug(f"[{symbol}] Signal rejeté - Hors killzone (seulement London/NY sessions)")
                return None
        
        # Utiliser le prix tick en priorité pour l'exécution, sinon le prix close de l'analyse
        if current_tick_price:
            current_price = current_tick_price['bid']  # Utiliser BID comme référence par défaut
            # Sauvegarder dans l'analyse pour les filtres (Spread Sentinel)
            analysis['current_tick'] = current_tick_price
            if 'spread' not in analysis['current_tick'] and 'ask' in current_tick_price:
                pip_val = self._get_pip_value(symbol)
                analysis['current_tick']['spread'] = abs(current_tick_price['ask'] - current_tick_price['bid']) / pip_val
        else:
            current_price = analysis['current_price']
            analysis['current_tick'] = {'bid': current_price, 'ask': current_price, 'spread': 0.0}
            logger.warning(f"⚠️ [{symbol}] Utilisation du prix historique ({current_price}) au lieu du tick réel")
        bias = analysis['bias']
        trend = analysis['trend']
        pd_zone = analysis['pd_zone']
        
        # Récupérer la configuration du symbole (OPTIMIZED)
        symbol_config = self.get_symbol_config(symbol)
        
        reasons = []
        confidence = 0.0
        
        # ============================================
        # OPTIMIZED: Vérifier les sweeps AVANT de rejeter pour biais NEUTRAL
        # Les sweeps confirmés peuvent générer un signal même en cas de conflit
        # Basé sur backtest: PDH/PDL 76% WR, Asian Sweep 80% WR
        # ============================================
        
        sweep_confirmed = False
        sweep_bonus = 0
        sweep_direction = None
        
        # 1. PDH/PDL Sweep (XAUUSD: 76% WR)
        if symbol_config.get('pdh_pdl_sweep', True):
            pdl_data = analysis.get('pdl', {})
            if pdl_data.get('confirmed'):
                pdl_bias = pdl_data.get('bias')
                if pdl_bias and pdl_bias != 'NEUTRAL':
                    sweep_confirmed = True
                    sweep_bonus = 30  # Bonus important - WR 76%!
                    sweep_direction = pdl_bias
                    reasons.append(f"PDL Sweep confirmé [{pdl_bias}] ✓✓")
                    logger.info(f"[{symbol}] PDL Sweep CONFIRMED - Direction: {pdl_bias}")
        
        # 2. Asian Range Sweep (EURUSD: 80% WR, GBPUSD: 56% WR)
        if symbol_config.get('asian_range_sweep', True):
            asian_data = analysis.get('asian_range', {})
            asian_signal = asian_data.get('signal', 'NEUTRAL')
            if asian_signal != 'NEUTRAL':
                sweep_confirmed = True
                sweep_bonus = 25  # Bonus pour Asian Sweep
                sweep_direction = asian_signal
                reasons.append(f"Asian Range Sweep [{asian_signal}] ✓✓")
                logger.info(f"[{symbol}] Asian Sweep CONFIRMED - Direction: {asian_signal}")
        
        # 3. Silver Bullet Sweep (ICT Reversal)
        if symbol_config.get('silver_bullet', True):
            sb_data = analysis.get('silver_bullet', {})
            if sb_data.get('phase') == 'sweep_detected':
                sweep_confirmed = True
                sweep_bonus = 30
                sweep_direction = sb_data.get('direction')
                reasons.append(f"Silver Bullet Sweep [{sweep_direction}] ✓✓")
                logger.info(f"[{symbol}] Silver Bullet Sweep CONFIRMED - Direction: {sweep_direction}")
        
        # 4. AMD Manipulation Sweep
        if symbol_config.get('amd', True):
            amd_data = analysis.get('amd', {})
            if amd_data.get('phase') == 'manipulation':
                sweep_confirmed = True
                sweep_bonus = 25
                sweep_direction = amd_data.get('direction')
                reasons.append(f"AMD Manipulation Sweep [{sweep_direction}] ✓✓")
                logger.info(f"[{symbol}] AMD Sweep CONFIRMED - Direction: {sweep_direction}")
        
        # 5. SMT Divergence Confirmation (CRITICAL ICT TOOL)
        if symbol_config.get('smt', True):
            smt_data = analysis.get('smt', {})
            if smt_data.get('signal') != 'none':
                smt_type_val = smt_data.get('signal')
                smt_dir = "BUY" if smt_type_val == "bullish" else "SELL"
                # SMT est un bonus de confiance majeur
                sweep_confirmed = True
                sweep_bonus += 30 
                reasons.append(f"🔥 SMT Divergence [{smt_dir}] ✓✓✓")
                if bias == "NEUTRAL":
                    bias = smt_dir
                    reasons.append(f"SMT sweep override biais NEUTRAL → {smt_dir}")

        
        # OPTIMIZED: Si sweep confirmé, utiliser la direction du sweep même si biais NEUTRAL
        if sweep_confirmed and sweep_direction:
            if bias == "NEUTRAL":
                bias = sweep_direction  # Override le biais avec la direction du sweep
                reasons.append(f"Sweep override biais NEUTRAL → {sweep_direction}")
                logger.info(f"[{symbol}] Sweep override: NEUTRAL → {sweep_direction}")
        
        # 🛑 RSI CONTRARIAN FILTER (Mean Reversion logic)
        # Filtre CRITIQUE pour H1 Trend Following:
        # Empêche d'entrer en fin de mouvement.
        rsi_val = analysis.get('momentum', {}).get('rsi', 50)
        
        if bias == 'BUY' and rsi_val > 55:
            # logger.debug(f"🛑 REJET BUY: RSI trop haut ({rsi_val:.1f} > 55) - Trop tard")
            # Invalider le signal
            return None 
            
        if bias == 'SELL' and rsi_val < 45:
            # logger.debug(f"🛑 REJET SELL: RSI trop bas ({rsi_val:.1f} < 45) - Trop tard")
            # Invalider le signal
            return None
        
        # 3. State Machine Confirmation (Sync Strategy with State Machine)
        smc_state = analysis.get('state_machine', {})
        if smc_state.get('stage') == 'LIQUIDITY_SWEEP':
             # The State Machine detected a valid sweep (Hunting Mode)
             sweep_confirmed = True
             sweep_bonus = 25
             state_dir = smc_state.get('sweep_direction')
             if state_dir and bias == "NEUTRAL":
                 bias = state_dir
                 reasons.append(f"SMC State Sweep ({state_dir}) ✓✓")
                 logger.info(f"[{symbol}] Sweep override: NEUTRAL → {sweep_direction}")
        
        # ============================================
        # INSTITUTIONAL STATE MACHINE OVERRIDE
        # Si la machine d'état valide la séquence complète (Sweep -> CHoCH -> Entry Zone)
        # On active le trade MÊME SI le biais synchrone est NEUTRAL
        # ============================================
        smc_state = analysis.get('state_machine', {})
        if smc_state.get('stage') == 'ENTRY_READY' and smc_state.get('valid_entry_zone'):
            state_dir = smc_state.get('sweep_direction')
            if state_dir:
                bias = state_dir
                confidence += 40 # Gros bonus pour séquence validée
                reasons.append(f"🔥 Séquence Institutionnelle Complète ({smc_state.get('sweep_type')}) ✓✓✓")
                logger.info(f"[{symbol}] 🔥 Séquence SMC Complète validée: {state_dir}")
        
        # ============================================
        # 🛡️ FILTRE SÉCURITÉ TENDANCE (PROFILES)
        # Blocage STRICT pour les actifs conservateurs (Forex Major)
        # Override les exceptions de sweep si le profil l'interdit.
        # ============================================
        sym_req_config = self.get_symbol_config(symbol)
        risk_profile = sym_req_config.get('risk_settings', {})
        allow_counter_trend = risk_profile.get('allow_counter_trend', True) 
        
        # Récupérer la direction de fond (HTF Bias > HTF Trend > MTF Trend)
        htf_bias_dir = analysis.get('htf_bias') # "BUY" / "SELL"
        if not htf_bias_dir and analysis.get('htf_trend'):
             # Fallback sur Trend Enum si Bias pas clair
             t_enum = analysis.get('htf_trend')
             if hasattr(t_enum, 'name'):
                 if t_enum.name == 'BULLISH': htf_bias_dir = 'BUY'
                 elif t_enum.name == 'BEARISH': htf_bias_dir = 'SELL'
        
        if not allow_counter_trend and htf_bias_dir:
            # Si le trade est opposé au HTF Bias
            if (bias == "BUY" and htf_bias_dir == "SELL") or \
               (bias == "SELL" and htf_bias_dir == "BUY"):
                
                # Vérifier si c'est vraiment un Reversal (pas juste un pullback)
                # Mais si allow_counter_trend est False, on ne cherche pas à comprendre.
                # On veut du Trend Following pur.
                logger.warning(f"⛔ [STRICT TREND SAFETY] {symbol} Signal {bias} rejeté (HTF: {htf_bias_dir}) - Contre-tendance interdite par profil.")
                
                # Log decision
                decision = TradeDecision(
                    symbol=symbol, timestamp=datetime.now().strftime("%H:%M:%S"),
                    signal_type="NONE", final_score=0.0
                )
                decision.rejection_reason = "Strict Trend Safety (Profile)"
                decision.log()
                
                return None

        # ============================================
        # 🆕 FILTRE RÉGIME IMPULSIF AMÉLIORÉ
        # Bloque les trades contre-tendance pendant les marchés impulsifs
        # SAUF si exceptions validées (SMT divergence, Sweep+FVG)
        # ============================================
        momentum = analysis.get('momentum', {}) if analysis else {}
        current_rsi = momentum.get('rsi', 50.0)
        
        # Récupérer la configuration du filtre impulsif
        impulsive_config = self.config.get('risk', {}).get('impulsive_regime_filter', {})
        filter_enabled = impulsive_config.get('enabled', True)
        rsi_low = impulsive_config.get('rsi_extreme_low', 25)
        rsi_high = impulsive_config.get('rsi_extreme_high', 75)
        block_counter = impulsive_config.get('block_counter_trend', True)
        allow_smt = impulsive_config.get('allow_with_smt_divergence', True)
        allow_sweep_fvg = impulsive_config.get('allow_with_sweep_fvg', True)
        
        if filter_enabled and block_counter:
            is_impulsive_down = current_rsi < rsi_low  # Marché en chute libre
            is_impulsive_up = current_rsi > rsi_high    # Marché en surchauffe
            
            # Vérifier les exceptions
            has_smt_exception = False
            has_sweep_fvg_exception = False
            
            smt_data = analysis.get('smt', {})
            smt_signal = smt_data.get('signal', 'none')
            
            # Exception SMT: Divergence confirmée dans la direction opposée
            if allow_smt and smt_signal != 'none':
                smt_dir = "BUY" if smt_signal == "bullish" else "SELL"
                if (is_impulsive_down and smt_dir == "BUY") or (is_impulsive_up and smt_dir == "SELL"):
                    has_smt_exception = True
                    reasons.append("⚡ SMT Exception: Divergence institutionnelle détectée")
                    logger.info(f"[{symbol}] 🔓 SMT Exception activée - Trade contre-impulsion autorisé")
            
            # Exception Sweep+FVG: Sweep confirmé avec FVG présent
            # 🛑 CRITIQUE: N'activer cette exception QUE si le contre-tendance est autorisé globalement (ou si le biais est aligné)
            if allow_sweep_fvg and sweep_confirmed:
                # Vérifier si on a le droit de jouer ce reversal
                is_counter_trend_move = False
                if htf_bias_dir:
                    if (bias == "BUY" and htf_bias_dir == "SELL") or (bias == "SELL" and htf_bias_dir == "BUY"):
                        is_counter_trend_move = True
                
                # Si contre-tendance interdite et mouvement contre-tendance -> PAS D'EXCEPTION
                if not allow_counter_trend and is_counter_trend_move:
                     logger.warning(f"🔒 [{symbol}] Sweep+FVG Exception BLOQUÉE par politique 'No Counter Trend'")
                else:
                    fvgs = analysis.get('fvgs', [])
                    ifvgs = analysis.get('ifvgs', [])
                    if fvgs or ifvgs:
                        has_sweep_fvg_exception = True
                        reasons.append("⚡ Sweep+FVG Exception: Setup institutionnel complet")
                        logger.info(f"[{symbol}] 🔓 Sweep+FVG Exception activée - Trade autorisé")
            
            # ✅ v2.4: Exception iFVG Golden (Bull Run Sniper)
            strong_ifvg_exception = False
            ifvg_d = analysis.get('ifvg', {})
            ifvg_s = ifvg_d.get('signal', 'NEUTRAL')
            ifvg_c = ifvg_d.get('confidence', 0)
            
            if ifvg_s == bias and htf_bias_dir and ifvg_s == htf_bias_dir and ifvg_c >= 80.0:
                 strong_ifvg_exception = True
                 reasons.append(f"⚡ Golden iFVG Exception: Sniper Entry sur {ifvg_s}")
                 logger.info(f"[{symbol}] 🔓 Golden iFVG Exception activée - Impulsive Filter Bypass")

            # Appliquer le veto si pas d'exception
            if is_impulsive_down and bias == "BUY":
                if not (has_smt_exception or has_sweep_fvg_exception or strong_ifvg_exception):
                    logger.warning(f"🚫 [IMPULSIVE FILTER] {symbol} RSI={current_rsi:.1f} < {rsi_low} - BUY bloqué (Chute libre)")
                    logger.warning(f"   → Exceptions: SMT={has_smt_exception}, Sweep+FVG={has_sweep_fvg_exception}, Gold={strong_ifvg_exception}")
                    return None
                else:
                    logger.info(f"✅ [IMPULSIVE FILTER] {symbol} BUY autorisé malgré RSI={current_rsi:.1f} (Exception active)")
                    
            if is_impulsive_up and bias == "SELL":
                if not (has_smt_exception or has_sweep_fvg_exception):
                    logger.warning(f"🚫 [IMPULSIVE FILTER] {symbol} RSI={current_rsi:.1f} > {rsi_high} - SELL bloqué (Surchauffe)")
                    logger.warning(f"   → Exceptions: SMT={has_smt_exception}, Sweep+FVG={has_sweep_fvg_exception}")
                    return None
                else:
                    logger.info(f"✅ [IMPULSIVE FILTER] {symbol} SELL autorisé malgré RSI={current_rsi:.1f} (Exception active)")

        # Initialiser le bulletin de décision
        decision = TradeDecision(
            symbol=symbol,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            signal_type="NONE",
            final_score=0.0
        )
        
        # Métadonnées de contexte
        htf_trend = analysis.get('htf_trend', Trend.RANGING)
        decision.metadata['Price'] = f"{current_price:.5f}"
        decision.metadata['HTF Trend'] = htf_trend.value if hasattr(htf_trend, 'value') else str(htf_trend)
        decision.metadata['LTF Trend'] = trend.value if hasattr(trend, 'value') else str(trend)

        # ----------------------------------------------------
        # SCORING & LOGIC (Adapted for Decision Logger)
        # ----------------------------------------------------
        
        
        signal_type = SignalType.BUY if bias == "BUY" else SignalType.SELL
        decision.signal_type = signal_type.name

        mtf_bias_dir = analysis.get('mtf_bias')
        risk_profile_cfg = sym_req_config.get('risk_settings', {})
        block_mtf_conflict = risk_profile_cfg.get('block_mtf_conflict', False)
        mtf_conflict_symbols = risk_profile_cfg.get('mtf_conflict_symbols', ["EURUSD", "GBPUSD"])
        symbol_upper = symbol.upper()
        if block_mtf_conflict and any(s in symbol_upper for s in mtf_conflict_symbols):
            if mtf_bias_dir in ["BUY", "SELL"]:
                is_conflict = (signal_type == SignalType.BUY and mtf_bias_dir == "SELL") or (signal_type == SignalType.SELL and mtf_bias_dir == "BUY")

                ifvg_data = analysis.get('ifvg', {})
                ifvg_signal_val = ifvg_data.get('signal', 'NEUTRAL')
                ifvg_conf_val = ifvg_data.get('confidence', 0)
                signal_dir = "BUY" if signal_type == SignalType.BUY else "SELL"
                has_valid_ifvg_exception = (ifvg_signal_val == signal_dir and ifvg_conf_val >= 80.0)

                if is_conflict and not (sweep_confirmed or has_valid_ifvg_exception):
                    logger.warning(f"⛔ [{symbol}] Signal {signal_type.value.upper()} rejeté (MTF Bias: {mtf_bias_dir})")
                    decision.rejection_reason = "MTF Bias Conflict"
                    decision.log()
                    return None

        # --- Filtre Zone (Premium/Discount) ---
        if pd_zone:
            zone = pd_zone.current_zone
            decision.metadata['Zone'] = zone.value
            
            # Vérifier exceptions
            has_quality_exception = False
            exception_reasons = []
            
            if sweep_confirmed:
                has_quality_exception = True
                exception_reasons.append(f"Sweep confirmed (+{sweep_bonus})")
            
            ifvg_data = analysis.get('ifvg', {})
            ifvg_conf = ifvg_data.get('confidence', 0)
            if ifvg_conf >= 70:
                has_quality_exception = True
                exception_reasons.append(f"High Conf iFVG ({ifvg_conf}%)")

            # Logique Zone
            if signal_type == SignalType.BUY and zone == ZoneType.PREMIUM:
                if not has_quality_exception:
                    decision.rejection_reason = f"BUY in PREMIUM zone (Counter-trend)"
                    decision.log()
                    return None
                else:
                    decision.components['Counter-Zone Warning'] = -10
                    confidence -= 10
            elif signal_type == SignalType.SELL and zone == ZoneType.DISCOUNT:
                if not has_quality_exception:
                    decision.rejection_reason = f"SELL in DISCOUNT zone (Counter-trend)"
                    decision.log()
                    return None
                else:
                    decision.components['Counter-Zone Warning'] = -10
                    confidence -= 10
        
        # --- Force Long/Short Check ---
        if signal_type == SignalType.SELL and symbol_config.get('force_long_only', False):
             decision.rejection_reason = "Force Long Only mode (Bull Run)"
             decision.log()
             return None
        if signal_type == SignalType.BUY and symbol_config.get('force_short_only', False):
             decision.rejection_reason = "Force Short Only mode (Bear Trend)"
             decision.log()
             return None


        # --- 🚀 NEW: MOMENTUM CONFIRMATION CHECK ---
        # Avant d'attribuer le score final, vérification du momentum pour les zones extrêmes
        pd_zone_data = analysis.get('pd_zone')
        pd_pct = pd_zone_data.current_percentage if pd_zone_data else 50.0
        atr_val = analysis.get('volatility', {}).get('atr_value', 0.001)

        momentum_ok = True
        momentum_reason = ""
        
        if signal_type == SignalType.BUY:
             momentum_ok, momentum_reason = self.momentum_filter.check_buy_confirmation(df, pd_pct, atr_val)
        else:
             momentum_ok, momentum_reason = self.momentum_filter.check_sell_confirmation(df, pd_pct, atr_val)
             
        if not momentum_ok:
            decision.rejection_reason = f"Momentum Veto: {momentum_reason}"
            decision.log()
            return None # STOP NET

        # --- Scoring Components ---
        
        # 1. Zone Score
        pd_score = 0
        if signal_type == SignalType.BUY:
            if pd_zone and pd_zone.current_zone == ZoneType.DISCOUNT:
                pd_score = 25
            elif pd_zone and pd_zone.current_zone == ZoneType.EQUILIBRIUM:
                pd_score = 15
        else:
            if pd_zone and pd_zone.current_zone == ZoneType.PREMIUM:
                pd_score = 25
            elif pd_zone and pd_zone.current_zone == ZoneType.EQUILIBRIUM:
                pd_score = 15
        
        if pd_score > 0:
            decision.components['Zone Alignment'] = pd_score
            confidence += pd_score

        # 2. Trend Score
        decision.components['LTF Trend Alignment'] = 15
        confidence += 15
        
        # 3. Order Block & iFVG Logic
        secondary_config = self.entry_config.get('secondary_signals', {})
        ifvg_config = secondary_config.get('ifvg', {})
        has_valid_ifvg = False
        
        ifvg_data = analysis.get('ifvg', {})
        ifvg_signal = ifvg_data.get('signal', 'NEUTRAL')
        ifvg_conf = ifvg_data.get('confidence', 0)
        
        if (secondary_config.get('enabled', False) and ifvg_config.get('enabled', False) and \
            ifvg_signal == bias and ifvg_conf >= ifvg_config.get('min_confidence', 85)) or \
           (ifvg_signal == bias and ifvg_conf >= 80.0):
            has_valid_ifvg = True
            decision.metadata['Valid iFVG'] = f"{ifvg_signal} ({ifvg_conf}%)"

        # Check SMC Entry Settings (Breaker Only Mode)
        smc_settings = symbol_config.get('smc_settings', {})
        entry_params = smc_settings.get('entry', {})
        use_breakers_only = entry_params.get('use_breakers_only', False)

        # Check OB
        require_ob = self.entry_config.get('require_ob', True)
        if use_breakers_only:
            require_ob = False # En mode Breaker Only, l'OB n'est plus requis (le Breaker le remplace)

        if require_ob and not sweep_confirmed and not has_valid_ifvg:
            ob_type = OBType.BULLISH if signal_type == SignalType.BUY else OBType.BEARISH
            in_ob, ob = self.ob_detector.is_price_in_ob(current_price, ob_type)
            
            if in_ob:
                decision.components['In Order Block'] = 40
                confidence += 40
            else:
                decision.rejection_reason = f"Price NOT in {ob_type.value} Order Block"
                # Log the available OBs for context
                available_obs = analysis.get('bullish_obs' if ob_type == OBType.BULLISH else 'bearish_obs', [])
                if available_obs:
                     # Find closest
                    closest_dist = min([abs(current_price - (o.high+o.low)/2) for o in available_obs])
                    decision.metadata['Closest OB Dist'] = f"{closest_dist:.5f}"
                else:
                    decision.metadata['Available OBs'] = "NONE"
                
                decision.log()
                return None
        elif sweep_confirmed:
            decision.components['Sweep Bonus (OB Bypass)'] = 20
            confidence += 20
        elif has_valid_ifvg:
            decision.components['iFVG Bonus (OB Bypass)'] = 15
            confidence += 15

        # 4. FVG Bonus
        fvg_type = FVGType.BULLISH if signal_type == SignalType.BUY else FVGType.BEARISH
        in_fvg, fvg = self.fvg_detector.is_price_in_fvg(current_price)
        if in_fvg and fvg.type == fvg_type:
            decision.components['In FVG'] = 20
            confidence += 20

        # 4b. Breaker Bonus & Check (Pro Crypto)
        has_breaker_signal = False
        breaker_blocks = analysis.get('breaker_blocks', [])
        target_breaker_type = BreakerType.BULLISH if signal_type == SignalType.BUY else BreakerType.BEARISH
        for bb in breaker_blocks:
            if bb.is_valid() and bb.type == target_breaker_type:
                if bb.low <= current_price <= bb.high:
                    decision.components['In Breaker Block'] = 30 # Augmenté car signal fort
                    confidence += 30
                    has_breaker_signal = True
                    break
        
        # ⚡ BREAKER MODE CHECK (Intelligent)
        strong_continuation_setup = False
        htf_t_enum = analysis.get('htf_trend')
        htf_dir_check = "NEUTRAL"
        if htf_t_enum and hasattr(htf_t_enum, 'name'):
             if htf_t_enum.name == 'BULLISH': htf_dir_check = "BUY"
             elif htf_t_enum.name == 'BEARISH': htf_dir_check = "SELL"
        
        if has_valid_ifvg and ifvg_signal == htf_dir_check and ifvg_conf >= 80.0:
            strong_continuation_setup = True
            decision.metadata['Breaker Bypass'] = "Strong iFVG Continuation"

        if use_breakers_only and not has_breaker_signal and not strong_continuation_setup:
             decision.rejection_reason = "Strict Mode: Breaker Block REQUIRED (No active breaker found at price)"
             decision.log()
             return None

        # 5. Liquidity Sweep Bonus
        recent_sweeps = analysis.get('sweeps', [])
        if recent_sweeps:
            last_sweep = recent_sweeps[-1]
            if (signal_type == SignalType.BUY and last_sweep.type.value == "sell_side") or \
               (signal_type == SignalType.SELL and last_sweep.type.value == "buy_side"):
                decision.components['Recent Liq Sweep'] = 15
                confidence += 15

        # ============================================
        # 🆕 7. HTF ALIGNMENT - SYSTÈME PONDÉRÉ HIÉRARCHIQUE
        # HTF = 40% du score (PRIORITÉ ABSOLUE)
        # Implémentation du "Veto HTF" intelligent
        # ============================================
        htf_bias = analysis.get('htf_bias')
        htf_trend = analysis.get('htf_trend')
        mtf_bias = analysis.get('mtf_bias')
        
        # Convertir HTF Trend Enum en direction si nécessaire
        htf_direction = htf_bias
        if not htf_direction and htf_trend:
            if hasattr(htf_trend, 'name'):
                if htf_trend.name == 'BULLISH':
                    htf_direction = 'BUY'
                elif htf_trend.name == 'BEARISH':
                    htf_direction = 'SELL'
                else:
                    htf_direction = 'NEUTRAL'
        
        # Calculer le score HTF (max 40 points - 40% du score total)
        htf_score = 0
        htf_conflict_detected = False
        
        if htf_direction:
            if htf_direction == bias:
                # ✅ ALIGNEMENT PARFAIT - Maximum de points
                htf_score = 40
                decision.components['🎯 HTF Alignment (D1)'] = htf_score
                decision.metadata['HTF Status'] = f"✅ ALIGNED ({htf_direction})"
                logger.info(f"✅ [{symbol}] HTF ALIGNED: {htf_direction} = {bias} (+40 pts)")
                
            elif htf_direction == 'NEUTRAL':
                # NEUTRE - Points moyens (pas idéal mais acceptable)
                htf_score = 20
                decision.components['HTF Neutral (D1)'] = htf_score
                decision.metadata['HTF Status'] = f"~ NEUTRAL (Ranging)"
                logger.info(f"~ [{symbol}] HTF NEUTRAL: Ranging market (+20 pts)")
                
            else:
                # ❌ CONFLIT DÉTECTÉ - Application du Veto Intelligent
                htf_conflict_detected = True
                decision.metadata['HTF Status'] = f"❌ CONFLICT ({htf_direction} vs {bias})"
                
                logger.warning(f"⚠️ [{symbol}] HTF CONFLICT DETECTED: HTF={htf_direction} vs Signal={bias}")
                
                # ============================================
                # VÉRIFICATION DES EXCEPTIONS AU VETO
                # ============================================
                exception_granted = False
                exception_type = None
                lot_reduction_factor = 1.0
                
                # EXCEPTION 1: SMT Divergence Extrême (>90% confidence)
                smt_data = analysis.get('smt', {})
                smt_signal = smt_data.get('signal', 'none')
                if smt_signal != 'none':
                    smt_dir = "BUY" if smt_signal == "bullish" else "SELL"
                    # SMT doit être dans notre direction ET avec haute confiance
                    if smt_dir == bias and sweep_bonus >= 30:  # SMT donne +30
                        exception_granted = True
                        exception_type = "SMT Divergence Extrême"
                        lot_reduction_factor = 0.7  # Réduire lot à 70%
                        htf_score = 10  # Score partiel
                        logger.info(f"🔓 [{symbol}] EXCEPTION 1: SMT Divergence validée (lot 70%)")
                
                # EXCEPTION 2: Reversal Institutionnel (CHoCH sur MTF + Sweep)
                if not exception_granted and sweep_confirmed:
                    # Vérifier si MTF montre un CHoCH (changement de caractère)
                    structure = analysis.get('structure', {})
                    choch_list = structure.get('choch', [])
                    if choch_list and len(choch_list) > 0:
                        last_choch = choch_list[-1]
                        # Si CHoCH récent dans notre direction
                        choch_dir = "BUY" if last_choch.direction.name == "BULLISH" else "SELL"
                        if choch_dir == bias:
                            exception_granted = True
                            exception_type = "CHoCH + Sweep (Reversal Setup)"
                            lot_reduction_factor = 0.6  # Réduire lot à 60% (plus risqué)
                            htf_score = 5  # Score minimal
                            logger.info(f"🔓 [{symbol}] EXCEPTION 2: CHoCH+Sweep validé (lot 60%)")
                
                # EXCEPTION 3: iFVG Très Haute Confiance (>85%) + HTF Ranging
                if not exception_granted and has_valid_ifvg:
                    if ifvg_conf >= 85 and htf_direction == 'NEUTRAL':
                        exception_granted = True
                        exception_type = "iFVG Haute Conf + HTF Ranging"
                        lot_reduction_factor = 0.8  # Réduire lot à 80%
                        htf_score = 15
                        logger.info(f"🔓 [{symbol}] EXCEPTION 3: iFVG {ifvg_conf}% (lot 80%)")
                
                # ============================================
                # DÉCISION FINALE SUR LE CONFLIT HTF
                # ============================================
                if exception_granted:
                    # Exception accordée - Trade autorisé avec réduction
                    decision.components[f'⚠️ HTF Conflict (Exception: {exception_type})'] = htf_score
                    decision.metadata['Exception'] = exception_type
                    decision.metadata['Lot Multiplier'] = f"{lot_reduction_factor:.0%}"
                    
                    # Appliquer la réduction de lot
                    if not hasattr(decision, 'lot_multiplier'):
                        decision.lot_multiplier = lot_reduction_factor
                    else:
                        decision.lot_multiplier *= lot_reduction_factor
                    
                    reasons.append(f"⚠️ HTF Conflict résolu par {exception_type} (Lot {lot_reduction_factor:.0%})")
                    
                else:
                    # ❌ AUCUNE EXCEPTION - VETO APPLIQUÉ
                    # On applique un MALUS SÉVÈRE au lieu d'un rejet total
                    # Cela permet au système de scorer bas et de rejeter naturellement
                    
                    htf_score = -30  # MALUS de -30 points (au lieu de 0)
                    decision.components['❌ HTF Conflict (VETO)'] = htf_score
                    lot_reduction_factor = 0.5  # Si le trade passe quand même, réduire à 50%
                    
                    if not hasattr(decision, 'lot_multiplier'):
                        decision.lot_multiplier = lot_reduction_factor
                    else:
                        decision.lot_multiplier *= lot_reduction_factor
                    
                    logger.warning(f"🚫 [{symbol}] HTF VETO: -30 pts | Lot réduit à 50% si trade passe")
                    logger.warning(f"   → Raison: Trade {bias} contre HTF {htf_direction} sans exception valide")
                    
                    reasons.append(f"⛔ HTF Conflict non résolu (-30 pts, Lot 50%)")
        
        else:
            # HTF direction inconnue - Score neutre
            htf_score = 10
            decision.components['HTF Unknown'] = htf_score
            decision.metadata['HTF Status'] = "? UNKNOWN"
        
        confidence += htf_score
        
        # ============================================
        # 🆕 7b. MTF ALIGNMENT - 30% du score
        # ============================================
        mtf_score = 0
        if mtf_bias:
            if mtf_bias == bias:
                mtf_score = 30
                decision.components['✅ MTF Alignment (H4)'] = mtf_score
                logger.debug(f"✅ [{symbol}] MTF ALIGNED: {mtf_bias} (+30 pts)")
            elif mtf_bias != 'NEUTRAL':
                # MTF conflict - Malus modéré
                mtf_score = -10
                decision.components['⚠️ MTF Conflict'] = mtf_score
                logger.warning(f"⚠️ [{symbol}] MTF CONFLICT: {mtf_bias} vs {bias} (-10 pts)")
            else:
                # MTF neutral
                mtf_score = 15
                decision.components['MTF Neutral'] = mtf_score
        
        confidence += mtf_score

        # 8. Sweep Bonus
        if sweep_confirmed:
            decision.components['Sweep Confirmed Bonus'] = sweep_bonus
            confidence += sweep_bonus
            decision.metadata['Sweep Confirmed'] = "YES"

            # 🆕 ICT DISPLACEMENT CHECK (Expert Experience)
            # Un sweep est 2x plus puissant s'il est suivi d'une impulsion immédiate
            is_displaced = False
            for i in range(1, 3): # Regarder les 2 dernières bougies (LTF)
                if self.market_structure._is_displaced(df, len(df)-i):
                    is_displaced = True
                    break
            
            if is_displaced:
                disp_bonus = 10
                decision.components['Institutional Displacement'] = disp_bonus
                confidence += disp_bonus
                reasons.append(f"⚡ Displacement détecté post-sweep (+{disp_bonus}%)")
            else:
                # Si pas de déplacement, on est plus prudent
                reasons.append("⚠️ Pas de déplacement post-sweep (Reversal lent)")
        
        # ============================================
        # 🆕 PHASE 2: INSTITUTIONAL PRO SCORING
        # ============================================
        
        # 1. TRIPLE TIMEFRAME ALIGNMENT (TTA) BONUS (+20%)
        # Si HTF + MTF + LTF sont tous alignés dans la même direction
        if analysis.get('tta_aligned', False):
            tta_bonus = 20 # Augmenté de 15 à 20 car c'est le setup 'Holy Grail'
            decision.components['TTA Alignment'] = tta_bonus
            confidence += tta_bonus
            reasons.append(f"💎 Triple Timeframe Alignment (HTF/MTF/LTF) ✓ (+{tta_bonus}%)")
            logger.info(f"[{symbol}] 💎 TTA Alignment détecté ! Bonus de confiance stratégique appliqué.")

        # 2. INTERMARKET / DXY CONFLUENCE (+10% à +20%)
        # Utilise le Dollar Index (DXY) pour confirmer les paires USD
        if self.fundamental_filter and getattr(self.fundamental_filter, 'enabled', False) and hasattr(self.fundamental_filter, 'intermarket'):
            intermarket_score = self.fundamental_filter.intermarket.get_score(symbol)
            # Rappel: Score > 0 = Bullish pour le symbole (ex: EURUSD bullish = DXY bearish)
            if (bias == "BUY" and intermarket_score > 30) or (bias == "SELL" and intermarket_score < -30):
                bonus = 15 if abs(intermarket_score) > 60 else 10
                decision.components['Intermarket Confluence'] = bonus
                confidence += bonus
                reasons.append(f"🔗 Intermarket Confluence ({'DXY' if 'USD' in symbol else 'Global'}) ✓ (+{bonus}%)")
                logger.info(f"[{symbol}] 🔗 Confluence Intermarket confirmée (Score: {intermarket_score:.1f})")
            elif (bias == "BUY" and intermarket_score < -30) or (bias == "SELL" and intermarket_score > 30):
                # Malus si le marché inter-actif est opposé (ex: Acheter EURUSD alors que DXY explose à la hausse)
                penalty = -15
                decision.components['Intermarket Conflict'] = penalty
                confidence += penalty
                reasons.append(f"⚠️ Conflit Intermarket ({intermarket_score:.1f}%) ✗ ({penalty}%)")
                logger.warning(f"[{symbol}] ⚠️ Risque Intermarket détecté (Conflit avec DXY/VIX)")

        # Cap de confiance à 99%
        confidence = min(99.0, max(0.0, confidence))

        # Mise à jour du score final dans la décision
        decision.final_score = confidence
        
        # 🛡️ FILTRE DE SCORE MINIMAL (PROFIL SENSITIVITY)
        smc_config = symbol_config.get('smc_settings', {})
        min_conf_score = smc_config.get('min_confidence_score', 70) # Default 70
        
        # =========================================================================
        # 🛡️ FILTRES DE PHILOSOPHIE SMC STRICTE (PROFITABLE OPTIMIZATION)
        # =========================================================================
        
        # RÈGLE 1: PAS DE TRADE À L'ÉQUILIBRE SI CONTRE-TENDANCE
        # Si on est contre la tendance HTF ou MTF, on exige d'être en zone EXTRÊME
        is_counter_trend = (
            (bias == 'BUY' and (htf_trend == Trend.BEARISH or mtf_bias == 'SELL')) or
            (bias == 'SELL' and (htf_trend == Trend.BULLISH or mtf_bias == 'BUY'))
        )
        
        if is_counter_trend:
            # Pour vendre contre-tendance, il faut être en PREMIUM (pas equilibrium)
            current_zone = pd_zone.current_zone.value if pd_zone else 'N/A'
            zone_pct = pd_zone.current_percentage if pd_zone else 50.0
            
            # Vérification BUY
            if bias == 'BUY' and zone_pct > 30: # On veut acheter bas (<30%)
                logger.info(f"⛔ [{symbol}] REJET PHILOSOPHIE SMC: Achat Contre-Tendance hors Discount ({zone_pct:.1f}% > 30%)")
                decision.rejection_reason = "Counter-Trend Buy not in Deep Discount"
                decision.log()
                return None
                
            # Vérification SELL
            if bias == 'SELL' and zone_pct < 70: # On veut vendre haut (>70%)
                logger.info(f"⛔ [{symbol}] REJET PHILOSOPHIE SMC: Vente Contre-Tendance hors Premium ({zone_pct:.1f}% < 70%)")
                decision.rejection_reason = "Counter-Trend Sell not in Deep Premium"
                decision.log()
                return None
                
            # RÈGLE 2: SWEEP OBLIGATOIRE POUR CONTRE-TENDANCE
            if not sweep_confirmed:
                logger.info(f"⛔ [{symbol}] REJET PHILOSOPHIE SMC: Contre-Tendance sans Sweep de Liquidité")
                decision.rejection_reason = "Counter-Trend requires Liquidity Sweep"
                decision.log()
                return None

        if confidence < min_conf_score:
            decision.rejection_reason = f"Score Insuffisant ({confidence:.0f} < {min_conf_score})"
            decision.final_score = confidence
            decision.log()
            logger.info(f"🚫 [{symbol}] Score Final {confidence:.0f} insuffisant (Requis: {min_conf_score})")
            return None

        # ============================================
        # SYSTÈME À 2 NIVEAUX DE SIGNAUX
        # (Suite de la logique inchangée...)
        # ============================================
        
        is_secondary_signal = False
        # ... (reste de la logique de détermination secondaire) ...
        secondary_config = self.entry_config.get('secondary_signals', {})
        
        # Si pas de sweep confirmé, vérifier les signaux secondaires (iFVG)
        if not sweep_confirmed:
            # 🛑 MODE GOLDEN SETUP ACTIVÉ:
            # On rejette TOUT signal qui n'a pas nettoyé de liquidité (Sweep).
            # Les iFVG seuls ne suffisent plus.
            logger.warning(f"🚫 [{symbol}] REJET: Pas de Liquidity Sweep confirmé (Golden Setup Only)")
            decision.rejection_reason = "No Liquidity Sweep (Golden Setup Mode)"
            decision.log()
            return None
            
            # (Ancien code désactivé pour Backtest Strict)
            # logger.debug(f"[{symbol}] No sweep confirmed, checking iFVG secondary signals...")
            
            # Vérifier si les signaux secondaires sont activés
            if secondary_config.get('enabled', False):
                ifvg_config = secondary_config.get('ifvg', {})
                
                if ifvg_config.get('enabled', False):
                    # Récupérer le signal iFVG depuis l'analyse
                    ifvg_data = analysis.get('ifvg', {})
                    ifvg_signal = ifvg_data.get('signal', 'NEUTRAL')
                    ifvg_conf = ifvg_data.get('confidence', 0)
                    ifvg_min = ifvg_config.get('min_confidence', 85)
                    
                    logger.debug(f"[{symbol}] iFVG check: signal={ifvg_signal}, conf={ifvg_conf}, min={ifvg_min}")
                    
                    # Vérifier si iFVG signal est valide
                    if ifvg_signal != 'NEUTRAL' and ifvg_conf >= ifvg_min:
                        # Vérifier alignement tendance si requis
                        require_trend = ifvg_config.get('require_trend_alignment', True)
                        trend_str = trend.value if hasattr(trend, 'value') else str(trend)
                        trend_aligned = (
                            (ifvg_signal == 'BUY' and 'bullish' in trend_str.lower()) or
                            (ifvg_signal == 'SELL' and 'bearish' in trend_str.lower())
                        )
                        
                        # Vérifier zone si requis
                        require_zone = ifvg_config.get('require_zone_alignment', True)
                        zone_aligned = True
                        if require_zone and pd_zone:
                            zone = pd_zone.current_zone.value
                            zone_aligned = (
                                (ifvg_signal == 'BUY' and zone in ['discount', 'equilibrium']) or
                                (ifvg_signal == 'SELL' and zone in ['premium', 'equilibrium'])
                            )
                        
                        logger.debug(f"[{symbol}] iFVG alignment: trend={trend_str}, trend_aligned={trend_aligned}, zone={pd_zone.current_zone.value if pd_zone else 'N/A'}, zone_aligned={zone_aligned}")
                        
                        # Si tous les critères sont remplis, utiliser iFVG comme signal secondaire
                        if (not require_trend or trend_aligned) and zone_aligned:
                            is_secondary_signal = True
                            bias = ifvg_signal
                            signal_type = SignalType.BUY if bias == "BUY" else SignalType.SELL
                            confidence = ifvg_conf
                            reasons.append(f"iFVG Signal [{ifvg_signal}] (conf: {ifvg_conf}%) ✓")
                            reasons.append(f"Signal Secondaire - Lot réduit à {ifvg_config.get('lot_multiplier', 0.5)*100:.0f}%")
                            logger.info(f"[{symbol}] ✅ iFVG SECONDARY SIGNAL ACCEPTED - Direction: {ifvg_signal}, Conf: {ifvg_conf}%")
                        else:
                            logger.info(f"[{symbol}] ❌ iFVG signal rejected: trend_aligned={trend_aligned}, zone_aligned={zone_aligned}")
                    else:
                        logger.debug(f"[{symbol}] iFVG signal not valid: signal={ifvg_signal}, conf={ifvg_conf} < min={ifvg_min}")
                else:
                    logger.debug(f"[{symbol}] iFVG not enabled in config")
            else:
                logger.debug(f"[{symbol}] Secondary signals not enabled")
            
            # Si toujours pas de signal secondaire et le symbole exige un sweep
            if not is_secondary_signal:
                if symbol_config.get('pdh_pdl_sweep', False) or symbol_config.get('asian_range_sweep', False):
                    logger.debug(f"[{symbol}] Pas de sweep confirmé et pas de signal iFVG valide")
                    return None
        
        # Valider le signal - SEUIL CONFIGURABLE
        min_conf = self.min_confidence if not is_secondary_signal else secondary_config.get('ifvg', {}).get('min_confidence', 85)
        
        # 🛡️ CRYPTO AGNOSTIC MONITORING: Si hors killzone, on exige une confidence d'élite (>80%)
        if is_crypto and not killzone_info.get('can_trade', True):
            min_conf = max(min_conf, 80.0) 
            logger.debug(f"[{symbol}] Hors killzone - Seuil de confiance élevé requis pour Crypto: {min_conf}%")
        if confidence < min_conf:
            # ✅ AMÉLIORATION: Logs détaillés pour comprendre la confidence basse
            logger.warning(f"❌ SIGNAL REJETÉ [{symbol}] - Confidence trop basse")
            logger.warning(f"   📊 Confidence: {confidence:.1f}% (min requis: {min_conf}%)")
            logger.warning(f"   🎯 Type: {'Secondaire (iFVG)' if is_secondary_signal else 'Principal (Sweep)'}")
            logger.warning(f"   📝 Raisons actuelles: {', '.join(reasons) if reasons else 'Aucune'}")
            logger.warning(f"   💡 Suggestion: Baisser 'min_confidence' dans settings.yaml")
            return None
        
        # Calculer SL et TP avec distances CORRECTES selon le symbole
        # ============================================
        # PROFESSIONAL DYNAMIC SL/TP CALCULATION
        # ============================================
        
        # 1. Calculer l'ATR pour la volatilité dynamique
        # ✅ PRÉCISION: Utiliser Ask pour BUY, Bid pour SELL si dispo pour les calculs précis
        if current_tick_price:
            entry_price = current_tick_price['ask'] if signal_type == SignalType.BUY else current_tick_price['bid']
        else:
            entry_price = current_price
            
        atr_period = 14
        atr_period = 14
        atr_value = 0.0
        if 'TR' not in df.columns:
            # Calcul simple ATR si pas présent
            high_low = df['high'] - df['low']
            high_close = (df['high'] - df['close'].shift()).abs()
            low_close = (df['low'] - df['close'].shift()).abs()
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr_value = tr.rolling(window=atr_period).mean().iloc[-1]
        else:
            atr_value = df['ATR'].iloc[-1] if 'ATR' in df.columns else df['high'].iloc[-1] - df['low'].iloc[-1]
            
        # Buffer dynamique basé sur l'ATR (plus robuste que pips fixes)
        # Nécessite pip_value pour la conversion
        pip_value = self._get_pip_value(symbol)
        
        # Pour SL: 10% de l'ATR ou min pips du symbole
        sl_buffer = max(atr_value * 0.1, self._get_min_sl_distance(symbol) * pip_value * 0.5) 
        
        # --- CALCUL DU STOP LOSS (SMC STYLE) ---
        # Utiliser les nouvelles méthodes robustes
        stop_loss, sl_reason = self._calculate_dynamic_sl(
            entry_price, signal_type, analysis.get('structure'), 
            analysis, current_tick_price
        )
        
        # 🛡️ CRYPTO SHIELD BUFFER APP
        # Si config 'sl_multiplier' (ex: 1.5 pour BTC)
        sl_mult = symbol_config.get('risk_settings', {}).get('sl_multiplier', 1.0)
        if sl_mult > 1.0:
            original_sl_dist = abs(entry_price - stop_loss)
            new_sl_dist = original_sl_dist * sl_mult
            
            if signal_type == SignalType.BUY:
                stop_loss = entry_price - new_sl_dist
            else:
                stop_loss = entry_price + new_sl_dist
            
            reasons.append(f"🛡️ Crypto Shield: SL Buffer x{sl_mult}")
            logger.info(f"[{symbol}] 🛡️ Crypto Shield activé: SL élargi de {original_sl_dist:.2f} à {new_sl_dist:.2f}")
        
        # --- CALCUL DU TAKE PROFIT (LIQUIDITY TARGETING) ---
        take_profit, tp_reason = self._find_liquidity_target(
            entry_price, signal_type, analysis.get('structure'), 
            analysis
        )
        
        reasons.append(f"SL: {sl_reason}")
        reasons.append(f"TP: {tp_reason}")
        
        # Application du TP avec Fallback RR Fixe si nécessaire
        risk = abs(entry_price - stop_loss)
        min_rr = 2.0 # Standard SMC
        
        target_type = tp_reason
        
        # SÉCURITÉ FINALE: Clamping du TP
        # Si le TP calculé est invalide (SELL > Entry ou BUY < Entry) à cause de la volatilité
        # ou d'une cible bizarre, on force un RR fixe pour garantir la validité.
        min_tp_dist = risk * 1.0 # Min 1:1
        
        if signal_type == SignalType.BUY:
            if take_profit <= entry_price + min_tp_dist:
                 take_profit = entry_price + (risk * min_rr)
                 target_type = "Adjusted (Safety)"
        else: # SELL
            if take_profit >= entry_price - min_tp_dist:
                 take_profit = entry_price - (risk * min_rr)
                 target_type = "Adjusted (Safety)"

                
        logger.info(f"   🎯 Target Mode: {target_type} | ATR: {atr_value:.5f}")
        
        # Validation finale des stops - ROBUSTE
        # 1. Vérifier direction correcte
        if signal_type == SignalType.BUY:
            if stop_loss >= entry_price or take_profit <= entry_price:
                logger.error(f"❌ Stops invalides pour BUY: Entry={entry_price:.5f}, SL={stop_loss:.5f}, TP={take_profit:.5f}")
                logger.error(f"   Règle: BUY doit avoir SL < Entry < TP")
                return None
        else:
            if stop_loss <= entry_price or take_profit >= entry_price:
                logger.error(f"❌ Stops invalides pour SELL: Entry={entry_price:.5f}, SL={stop_loss:.5f}, TP={take_profit:.5f}")
                logger.error(f"   Règle: SELL doit avoir TP < Entry < SL")
                return None
        
        # 2. Vérifier distance minimale (protection contre stops trop serrés)
        min_sl_distance = self._get_min_sl_distance(symbol) * pip_value
        actual_sl_distance = abs(entry_price - stop_loss)
        required_min_distance = min_sl_distance
        
        if actual_sl_distance < required_min_distance:
            logger.warning(f"⚠️ SL trop proche de l'entrée pour {symbol} ({actual_sl_distance:.5f} < {required_min_distance:.5f})")
            logger.warning(f"   🔧 Ajustement automatique du SL à la distance minimale.")
            
            # Ajuster le SL pour respecter le minimum
            if signal_type == SignalType.BUY:
                stop_loss = entry_price - required_min_distance
            else:
                stop_loss = entry_price + required_min_distance
                
            # Recalculer le risque et mettre à jour le TP si besoin pour maintenir le RR
            risk = abs(entry_price - stop_loss)
            
            # OPTIONNEL: Ajuster le TP pour maintenir le RR initial si on veut être strict
            # Ici on laisse le TP d'origine sauf s'il devient < 1R (géré par la suite)
        
        # 3. Vérifier RR minimum acceptable (STRICT FILTER)
        # On ne triche pas en repoussant le TP artificiellement. Si le setup technique ne donne pas 1:1.5, on jette.
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        actual_rr = reward / risk if risk > 0 else 0
        
        # Récupérer le RR min de la config ou utiliser 1.5 par défaut
        min_rr_config = self.config.get('risk', {}).get('risk_reward', {}).get('min', 1.5)
        
        if actual_rr < min_rr_config:
            # Tenter UNE FOIS d'ajuster si on est très proche (ex: 1.45 pour 1.5)
            # Mais si on est loin (ex: 0.8), c'est un mauvais trade.
            if actual_rr > (min_rr_config * 0.8):
                # Petit boost autorisé
                logger.debug(f"⚠️ RR limite ({actual_rr:.2f}), ajustement léger du TP pour atteindre {min_rr_config}")
                if signal_type == SignalType.BUY:
                    take_profit = entry_price + (risk * min_rr_config)
                else:
                    take_profit = entry_price - (risk * min_rr_config)
            else:
                 # REJET STRICT
                 logger.warning(f"⛔ SIGNAL REJETÉ: Risk/Reward insuffisant (1:{actual_rr:.2f}). Requis: 1:{min_rr_config}")
                 logger.warning(f"   Risk: {risk:.5f} | Reward: {reward:.5f}")
                 return None
        
        logger.debug(f"✅ Validation stops OK - SL distance: {abs(entry_price - stop_loss):.5f}, RR Final: 1:{actual_rr:.2f}")
        
        # ============================================
        # NOUVEAU: Appliquer les filtres avancés
        # ============================================
        direction = "BUY" if signal_type == SignalType.BUY else "SELL"
        htf_df_for_filter = None
        if 'htf_df' in dir() and htf_df is not None:
            htf_df_for_filter = htf_df
        
        enhanced = self.advanced_filters.enhance_signal(
            df=df,
            signal_direction=direction,
            entry_price=entry_price,
            symbol=symbol,
            htf_df=htf_df_for_filter,
            analysis=analysis,
            allow_counter_trend_override=(sweep_confirmed or has_valid_ifvg)  # ✅ FIX: Autoriser contre-tendance pour sweeps ET iFVG haute confiance
        )
        
        # Vérifier si le signal doit être pris
        should_trade, trade_reason = should_take_trade(enhanced)
        
        if not should_trade:
            logger.info(f"🚫 Signal rejeté par filtres avancés: {trade_reason}")
            return None
        
        # Utiliser les niveaux SL/TP dynamiques si de meilleure qualité
        if enhanced.quality in [SignalQuality.A_PLUS, SignalQuality.A]:
            # Utiliser ATR dynamique pour les meilleurs signaux
            stop_loss = enhanced.stop_loss
            take_profit = enhanced.take_profit
            reasons.append(f"✓ SL/TP ATR dynamique (Qualité {enhanced.quality.value})")
        
        # Ajouter les raisons des filtres avancés
        reasons.extend(enhanced.reasons)
        
        # Ajouter les warnings
        if enhanced.warnings:
            for warning in enhanced.warnings:
                reasons.append(warning)

        pip_value = self._get_pip_value(symbol)
        if signal_type == SignalType.BUY:
            if stop_loss >= entry_price or take_profit <= entry_price:
                logger.error(f"❌ Stops invalides pour BUY: Entry={entry_price:.5f}, SL={stop_loss:.5f}, TP={take_profit:.5f}")
                logger.error(f"   Règle: BUY doit avoir SL < Entry < TP")
                return None
        else:
            if stop_loss <= entry_price or take_profit >= entry_price:
                logger.error(f"❌ Stops invalides pour SELL: Entry={entry_price:.5f}, SL={stop_loss:.5f}, TP={take_profit:.5f}")
                logger.error(f"   Règle: SELL doit avoir TP < Entry < SL")
                return None

        min_sl_distance = self._get_min_sl_distance(symbol) * pip_value
        actual_sl_distance = abs(entry_price - stop_loss)
        if actual_sl_distance < min_sl_distance:
            logger.warning(f"⚠️ SL trop proche de l'entrée pour {symbol} ({actual_sl_distance:.5f} < {min_sl_distance:.5f})")
            logger.warning(f"   🔧 Ajustement automatique du SL à la distance minimale.")
            if signal_type == SignalType.BUY:
                stop_loss = entry_price - min_sl_distance
            else:
                stop_loss = entry_price + min_sl_distance

        risk = abs(entry_price - stop_loss)
        actual_rr = abs(take_profit - entry_price) / risk if risk > 0 else 0.0
        if actual_rr < 1.0:
            logger.warning(f"⚠️ RR dégradé après filtres avancés: {actual_rr:.2f} (minimum 1:1 requis)")
            min_rr_recovery = 1.5
            if signal_type == SignalType.BUY:
                take_profit = entry_price + (risk * min_rr_recovery)
            else:
                take_profit = entry_price - (risk * min_rr_recovery)
            logger.info(f"   🔧 TP ajusté pour RR 1.5: {take_profit:.5f}")

        # Calculer le multiplicateur de lot (ajusté par qualité du signal)
        lot_mult = enhanced.position_size_multiplier
        if is_secondary_signal:
            lot_mult = min(lot_mult, secondary_config.get('ifvg', {}).get('lot_multiplier', 0.5))
            decision.metadata['Signal Level'] = "SECONDARY (iFVG)"
        
        # 🧠 RISK: Counter-Momentum Reduction - SUPPRIMÉ
        # La logique précédente réduisait le risque en zone Oversold/Overbought
        # Ce qui est contre-productif pour une stratégie Mean Reversion / Discount
        # On garde la taille pleine pour les retournements.
        pass
        
        # ============================================
        # 🆕 APPLICATION DU LOT MULTIPLIER HTF VETO
        # Si un veto HTF a été appliqué, le decision object contient un lot_multiplier
        # ============================================
        if hasattr(decision, 'lot_multiplier'):
            htf_lot_factor = decision.lot_multiplier
            lot_mult *= htf_lot_factor
            logger.warning(f"🛡️ [{symbol}] HTF Veto Multiplier Applied: {htf_lot_factor:.0%}")
            logger.warning(f"   → Lot Final: {lot_mult*100:.0f}%")
        
        # Mettre à jour la confiance avec le score du Maître du Scoring (Poids 70%)
        final_confidence = (confidence * 0.3 + enhanced.confidence * 0.7)
        decision.final_score = final_confidence
        decision.metadata['Master Score'] = f"{enhanced.confidence:.1f}"
        decision.metadata['Strategy Score'] = f"{confidence:.1f}"
        decision.metadata['Final Lot Multiplier'] = f"{lot_mult:.0%}"
        if enhanced.spread_info:
            decision.metadata['Spread'] = f"{enhanced.spread_info['value']:.1f} pips"
            decision.metadata['Spread Quality'] = enhanced.spread_info['reason']
        decision.is_taken = True
        
        # 🛡️ FILTRE 1: Minimum Risk/Reward Ratio (CRITIQUE pour Profit Factor)
        risk_dist = abs(entry_price - stop_loss)
        reward_dist = abs(take_profit - entry_price)
        
        if risk_dist <= 0:
            rr_ratio = 0
        else:
            rr_ratio = reward_dist / risk_dist
            
        min_rr_config = self.config.get('risk', {}).get('risk_reward', {}).get('min', 2.0)
        
        if rr_ratio < min_rr_config:
            logger.warning(f"🛑 [{symbol}] Signal rejected: Poor Risk/Reward ({rr_ratio:.2f}R < {min_rr_config}R)")
            decision.metadata['Status'] = 'Rejected (Low RR)'
            return None
            
        # 🛡️ FILTRE 2: Minimum Confidence (Filtre Quantité)
        min_conf_config = self.config.get('smc', {}).get('min_confidence', 0.80) * 100 # Convert to 0-100 scale
        
        # NOTE: final_confidence est sur 0-100
        if final_confidence < min_conf_config:
            logger.warning(f"🛑 [{symbol}] Signal rejected: Low Confidence ({final_confidence:.1f}% < {min_conf_config}%)")
            decision.metadata['Status'] = 'Rejected (Low Confidence)'
            return None
        
        signal = TradeSignal(
            signal_type=signal_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=min(100, final_confidence),
            reasons=reasons,
            timestamp=pd.Timestamp.now(),
            is_secondary=is_secondary_signal,
            lot_multiplier=lot_mult  # ← LOT MULTIPLIER AVEC VETO HTF APPLIQUÉ
        )
        
        signal_level = "SECONDARY (iFVG)" if is_secondary_signal else "PRIMARY (Sweep)"
        quality_str = enhanced.quality.value
        logger.info(f"✅ Signal [{signal_level}] [{quality_str}] generated: {signal_type.value.upper()} @ {entry_price:.5f}, "
                   f"SL: {stop_loss:.5f}, TP: {take_profit:.5f}, Conf: {final_confidence:.0f}%, Lot: {lot_mult*100:.0f}%")
        
        # Log final decision
        decision.log()
        
        # 🧠 LOGIQUE "ELITE OR NOTHING"
        # 1. PROMOTION: Si un signal est de haute confiance (>75), on le force en risque PLEIN
        # Cela "sauve" les bons setups iFVG qui étaient bridés à 0.5
        if decision.final_score >= 75.0:
            if lot_mult < 1.0:
                logger.info(f"🚀 [{symbol}] PROMOTION: Signal upgradé à 1.0 (Score {decision.final_score:.1f} >= 75)")
                lot_mult = 1.0
                reasons.append("🚀 Promoted to Full Risk (High Score)")
        
        decision.metadata['Final Lot Multiplier'] = f"{lot_mult:.0%}"
        
        # 2. GUILLOTINE: Si après promotion on est toujours un "demi-trade", on rejette.
        # Les stats montrent que les trades à 0.5 perdent de l'argent.
        if lot_mult < 0.9:
            logger.warning(f"⛔ [{symbol}] REJET QUALITÉ: Multiplier {lot_mult:.2f} < 0.9 (Score: {decision.final_score:.1f})")
            return None

        # 🌍 NOUVEAU: Application du Filtre Fondamental (Phase 2)
        if self.fundamental_filter and self.fundamental_filter.enabled:
            signal = self._apply_fundamental_filter(signal, symbol)
        
        # Mise à jour finale du multiplier dans le signal
        signal.lot_multiplier = lot_mult
        
        return signal
    
    def _get_pip_value(self, symbol: str) -> float:
        """Retourne la valeur d'un pip pour le symbole."""
        symbol_upper = symbol.upper()
        if "JPY" in symbol_upper:
            return 0.01
        elif "XAU" in symbol_upper:
            return 0.01  # XAUUSD pip = $0.01
        elif "BTC" in symbol_upper:
            return 0.01  # BTCUSD pip = $0.01
        elif "ETH" in symbol_upper:
            return 0.01
        else:
            return 0.0001
    
    def _get_min_sl_distance(self, symbol: str) -> float:
        """Retourne la distance SL minimum en pips/points."""
        symbol_upper = symbol.upper()
        if "BTC" in symbol_upper:
            return 1000   # $10.00 Min SL (vs $100 avant)
        elif "ETH" in symbol_upper:
            return 500    # $5.00 Min SL
        elif "XAU" in symbol_upper:
            return 100    # $1.00 Min SL (vs $20 avant) - Permet SL serré sur Gold
        elif "JPY" in symbol_upper:
            return 5      # 5 pips (0.050 JPY)
        else:
            return 3      # 3.0 pips (0.00030) - Standard SMC M1/M5
    
    def _calculate_dynamic_sl(self, entry_price: float, signal_type: SignalType, structure: Dict, analysis: Dict, current_tick_price: Dict) -> Tuple[float, str]:
        """Calcule un SL structurel intelligent avec buffer de volatilité."""
        pip_value = 0.0001
        if "JPY" in analysis.get('symbol', ''): pip_value = 0.01
        buffer = 5.0 * pip_value
        
        sl_price = entry_price
        reason = "Fixed"
        
        last_swing = None
        if signal_type == SignalType.BUY:
            swing_lows = structure.get('swing_lows', [])
            if swing_lows:
                valid_lows = [sl for sl in swing_lows if hasattr(sl, 'price') and sl.price < entry_price]
                if not valid_lows:
                     valid_lows = [sl['price'] for sl in swing_lows if isinstance(sl, dict) and sl['price'] < entry_price]
                if valid_lows:
                    last_swing = valid_lows[-1] 
                    if hasattr(last_swing, 'price'): last_swing = last_swing.price
                    sl_price = last_swing - buffer
                    reason = "Structure Low"
        else:
            swing_highs = structure.get('swing_highs', [])
            if swing_highs:
                valid_highs = [sh for sh in swing_highs if hasattr(sh, 'price') and sh.price > entry_price]
                if not valid_highs:
                     valid_highs = [sh['price'] for sh in swing_highs if isinstance(sh, dict) and sh['price'] > entry_price]
                if valid_highs:
                    last_swing = valid_highs[-1]
                    if hasattr(last_swing, 'price'): last_swing = last_swing.price
                    sl_price = last_swing + buffer
                    reason = "Structure High"

        if reason == "Fixed":
            fixed_dist = 40 * pip_value
            sl_price = entry_price - fixed_dist if signal_type == SignalType.BUY else entry_price + fixed_dist
                
        return sl_price, reason

    def _find_liquidity_target(self, entry_price: float, signal_type: SignalType, structure: Dict, analysis: Dict) -> Tuple[float, str]:
        """Trouve la prochaine zone de liquidité logique pour le TP."""
        tp_price = entry_price
        reason = "Fixed RR"
        pip_value = 0.0001
        target_found = False
        
        if signal_type == SignalType.BUY:
            pdl_info = analysis.get('pdl', {}).get('levels', {})
            pdh = pdl_info.get('pdh')
            if pdh and pdh > entry_price:
                tp_price = pdh
                target_found = True
                reason = "PDH Liquidity"
            
            swing_highs = structure.get('swing_highs', [])
            candidates = []
            for sh in swing_highs:
                price = sh.price if hasattr(sh, 'price') else sh.get('price') if isinstance(sh, dict) else sh
                if price > entry_price: candidates.append(price)
            
            if candidates:
                nearest_major = max(candidates) 
                if not target_found or (target_found and nearest_major < tp_price):
                    tp_price = nearest_major
                    target_found = True
                    reason = "Swing High Liq"
        else:
            pdl_info = analysis.get('pdl', {}).get('levels', {})
            pdl = pdl_info.get('pdl')
            if pdl and pdl < entry_price:
                tp_price = pdl
                target_found = True
                reason = "PDL Liquidity"
            
            swing_lows = structure.get('swing_lows', [])
            candidates = []
            for sl in swing_lows:
                price = sl.price if hasattr(sl, 'price') else sl.get('price') if isinstance(sl, dict) else sl
                if price < entry_price: candidates.append(price)
            
            if candidates:
                nearest_major = min(candidates)
                if not target_found or (target_found and nearest_major > tp_price):
                    tp_price = nearest_major
                    target_found = True
                    reason = "Swing Low Liq"
        
        if not target_found:
             distance = 50 * pip_value
             tp_price = entry_price + distance if signal_type == SignalType.BUY else entry_price - distance
             reason = "Fixed 50 pips"
             
        return tp_price, reason
    
    def _apply_fundamental_filter(self, signal: TradeSignal, symbol: str) -> TradeSignal:
        """
        Applique le filtre fondamental au signal SMC.
        
        Actions possibles:
        - Bloquer le trade (divergence macro forte ou news critique)
        - Réduire la position (divergence modérée)
        - Booster la position (confluence SMC + Macro)
        - Ajouter des warnings (news imminentes)
        
        Args:
            signal: Signal SMC à valider
            symbol: Symbole tradé
        
        Returns:
            Signal modifié (ou NO_SIGNAL si bloqué)
        """
        try:
            # Déterminer la direction
            direction = "BUY" if signal.signal_type == SignalType.BUY else "SELL"
            
            # Analyse fondamentale
            logger.debug(f"🌍 Application filtre fondamental pour {symbol} ({direction})")
            context = self.fundamental_filter.analyze(symbol, direction)
            
            # 1. Vérifier si le trade doit être bloqué
            should_block, block_reason = self.fundamental_filter.should_block_trade(
                context, direction
            )

            # 🛑 VETO STRICT BIAIS (OVERRIDE)
            # Si le biais macro est clairement opposé (ex: BEARISH vs BUY), on bloque,
            # même si le score numérique n'est pas extrême (ex: -35% vs -30%).
            if not should_block:
                is_buy = direction == "BUY"
                macro_bearish = context.macro_bias == "BEARISH"
                macro_bullish = context.macro_bias == "BULLISH"
                
                if (is_buy and macro_bearish) or (not is_buy and macro_bullish):
                     should_block = True
                     block_reason = f"❌ HARD VETO: Trade {direction} vs Macro {context.macro_bias} (Score: {context.composite_score:.1f})"
                     logger.warning(f"🛡️ Protection Macro Activée: {block_reason}")
            
            if should_block:
                logger.warning(f"🌍 {block_reason}")
                # Bloquer le signal
                signal.signal_type = SignalType.NO_SIGNAL
                signal.reasons.append(f"❌ FUNDAMENTAL BLOCK: {block_reason}")
                logger.info(f"🌍 Trade BLOQUÉ: {block_reason}")
                return signal
            
            # 2. Ajuster la taille de position selon contexte macro
            multiplier = self.fundamental_filter.get_position_size_multiplier(
                context, direction
            )
            
            original_lot = signal.lot_multiplier
            signal.lot_multiplier *= multiplier
            
            # Logger l'ajustement
            if multiplier != 1.0:
                action = "BOOSTÉ" if multiplier > 1.0 else "RÉDUIT"
                logger.info(f"🌍 Position {action}: {original_lot:.2f} → {signal.lot_multiplier:.2f} "
                           f"(x{multiplier:.2f}) - Score Macro: {context.composite_score:.1f}")
            
            # 3. Ajouter warnings si news
            if context.has_critical_news:
                warning = "⚠️ News HIGH impact dans les 4h à venir"
                signal.reasons.append(warning)
                logger.warning(f"🌍 {warning}")
            
            # 4. Ajouter le raisonnement fondamental aux raisons du signal
            if context.reasoning:
                for reason in context.reasoning:
                    signal.reasons.append(f"🌍 {reason}")
            
            # 5. Logger le résumé
            logger.info(f"🌍 Fundamental Analysis: Score={context.composite_score:.1f}, "
                       f"Bias={context.macro_bias}, Risk={context.risk_sentiment}, "
                       f"DXY={context.dxy_bias}")
            
            logger.info(f"🌍 Décision finale: {'✅ AUTORISER' if signal.signal_type != SignalType.NO_SIGNAL else '❌ BL OQUER'} "
                       f"| Multiplier: {multiplier:.2f}x")
            
        except Exception as e:
            logger.error(f"🌍 Erreur application fundamental filter: {e}")
            # En cas d'erreur, ne pas bloquer (fail-safe)
            # Juste logger et continuer avec le signal SMC original
            import traceback
            logger.debug(traceback.format_exc())
        
        return signal
    
    def get_dashboard_data(self, analysis: Dict) -> Dict:
        """Retourne les données pour le dashboard."""
        return {
            'bias': analysis.get('bias', 'NEUTRAL'),
            'trend': analysis.get('trend', Trend.RANGING).value if hasattr(analysis.get('trend'), 'value') else 'ranging',
            'bullish_obs_count': len(analysis.get('bullish_obs', [])),
            'bearish_obs_count': len(analysis.get('bearish_obs', [])),
            'fvg_count': len(analysis.get('fvgs', [])),
            'pd_zone': analysis.get('pd_zone').current_zone.value if analysis.get('pd_zone') else 'unknown',
            'current_price': analysis.get('current_price', 0)
        }
