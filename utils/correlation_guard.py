"""
🛡️ MULTI-SYMBOL CORRELATION GUARD
Version 1.0 - Protection avancée contre la sur-exposition aux actifs corrélés

Fonctionnalités:
- Détection automatique des groupes de corrélation (USD, EUR, GBP, etc.)
- Blocage des trades multiples sur actifs fortement corrélés
- Calcul de l'exposition nette par devise
- Protection contre le "hedging" accidentel ou inefficace
- Statistiques de corrélation en temps réel

Basé sur les principes de gestion de risque institutionnel.
"""

import MetaTrader5 as mt5
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict
from loguru import logger
import json
from pathlib import Path


@dataclass
class CurrencyExposure:
    """Exposition à une devise spécifique."""
    currency: str
    long_lots: float = 0.0
    short_lots: float = 0.0
    long_symbols: List[str] = field(default_factory=list)
    short_symbols: List[str] = field(default_factory=list)
    
    @property
    def net_lots(self) -> float:
        """Exposition nette (long - short)."""
        return self.long_lots - self.short_lots
    
    @property
    def gross_lots(self) -> float:
        """Exposition brute (long + short)."""
        return self.long_lots + self.short_lots
    
    @property
    def exposure_type(self) -> str:
        if self.net_lots > 0.01:
            return "LONG"
        elif self.net_lots < -0.01:
            return "SHORT"
        else:
            return "NEUTRAL"
    
    def is_over_exposed(self, max_net_lots: float = 0.1) -> bool:
        """Vérifie si l'exposition nette dépasse la limite."""
        return abs(self.net_lots) > max_net_lots


@dataclass
class CorrelationGroup:
    """Groupe d'actifs corrélés."""
    group_name: str
    symbols: List[str] = field(default_factory=list)
    correlation_type: str = "positive"  # positive ou negative
    max_positions: int = 2
    current_positions: int = 0
    current_direction: str = ""  # BUY, SELL, ou ""


class CorrelationGuard:
    """
    Garde de corrélation pour éviter la sur-exposition.
    
    Protège contre:
    1. Trades multiples sur même devise (EURUSD + EURGBP = double exposition EUR)
    2. Trades contradictoires sur actifs corrélés (EURUSD long + DXY long)
    3. Dépassement de limites par groupe de corrélation
    """
    
    # Groupes de corrélation statiques
    CORRELATION_GROUPS = {
        'USD_MAJORS': {
            'symbols': ['EURUSDm', 'GBPUSDm', 'AUDUSDm', 'NZDUSDm'],
            'correlation': 'positive',
            'note': 'Tous inversement corrélés au USD'
        },
        'JPY_PAIRS': {
            'symbols': ['USDJPYm', 'EURJPYm', 'GBPJPYm', 'AUDJPYm'],
            'correlation': 'positive',
            'note': 'Risk-on/Risk-off ensemble'
        },
        'EUR_CROSSES': {
            'symbols': ['EURUSDm', 'EURGBPm', 'EURJPYm', 'EURCHFm'],
            'correlation': 'positive',
            'note': 'Même devise de base EUR'
        },
        'GBP_CROSSES': {
            'symbols': ['GBPUSDm', 'GBPJPYm', 'EURGBPm', 'GBPAUDm'],
            'correlation': 'mixed',
            'note': 'GBP sensible aux news UK'
        },
        'GOLD_RELATED': {
            'symbols': ['XAUUSDm', 'XAGUSDm'],
            'correlation': 'positive',
            'note': 'Métaux précieux'
        },
        'CRYPTO': {
            'symbols': ['BTCUSDm', 'ETHUSDm'],
            'correlation': 'positive',
            'note': 'Marché crypto corrélé'
        }
    }
    
    # Paires de corrélation spécifiques pour SMT
    SMT_PAIRS = {
        'GBPUSDm': {'correlated': 'EURUSDm', 'type': 'positive'},
        'EURUSDm': {'correlated': 'GBPUSDm', 'type': 'positive'},
        'AUDUSDm': {'correlated': 'NZDUSDm', 'type': 'positive'},
        'NZDUSDm': {'correlated': 'AUDUSDm', 'type': 'positive'},
        # Corrélation négative avec DXY
        'EURUSDm_DXY': {'correlated': 'DXm', 'type': 'negative'},
    }
    
    def __init__(self, config: Dict = None, max_exposure_per_currency: float = 0.15,
                 max_positions_per_group: int = 2):
        """
        Args:
            config: Configuration du bot
            max_exposure_per_currency: Exposition max en lots par devise
            max_positions_per_group: Positions max par groupe de corrélation
        """
        self.config = config or {}
        self.max_exposure_per_currency = max_exposure_per_currency
        self.max_positions_per_group = max_positions_per_group
        
        # État actuel
        self.currency_exposures: Dict[str, CurrencyExposure] = {}
        self.group_positions: Dict[str, CorrelationGroup] = {}
        self.active_positions: Dict[int, Dict] = {}  # ticket -> info
        
        # Historique des blocages
        self.block_history: List[Dict] = []
        
        # Charger la config personnalisée si disponible
        self._load_custom_groups()
        
        # Charger les overrides depuis la config globale (settings.yaml)
        if self.config and 'correlation_guard' in self.config:
            cg_settings = self.config['correlation_guard']
            self.max_exposure_per_currency = cg_settings.get('max_exposure_per_currency', self.max_exposure_per_currency)
            self.max_positions_per_group = cg_settings.get('max_positions_per_group', self.max_positions_per_group)
        
        logger.info(f"🛡️ CorrelationGuard initialisé | Max exposure: {self.max_exposure_per_currency} lots/currency")
    
    def _load_custom_groups(self):
        """Charge les groupes de corrélation personnalisés depuis la config."""
        custom_groups = self.config.get('risk', {}).get('correlation_groups', {})
        for group_name, group_config in custom_groups.items():
            self.CORRELATION_GROUPS[group_name] = group_config
    
    def _extract_currencies(self, symbol: str) -> Tuple[str, str]:
        """
        Extrait les deux devises d'un symbole.
        
        Ex: GBPUSDm -> (GBP, USD)
            XAUUSDm -> (XAU, USD)
        """
        # Nettoyer le suffixe broker (m, .m, etc.)
        clean_symbol = symbol.rstrip('m').replace('.', '').upper()
        
        # Cas spéciaux
        if 'XAU' in clean_symbol:
            return ('XAU', 'USD')
        if 'XAG' in clean_symbol:
            return ('XAG', 'USD')
        if 'BTC' in clean_symbol:
            return ('BTC', 'USD')
        if 'ETH' in clean_symbol:
            return ('ETH', 'USD')
        
        # Forex standard (6 caractères)
        if len(clean_symbol) >= 6:
            return (clean_symbol[:3], clean_symbol[3:6])
        
        return ('UNKNOWN', 'UNKNOWN')
    
    def _update_positions_from_mt5(self):
        """Met à jour l'état depuis MT5."""
        try:
            positions = mt5.positions_get()
            if positions is None:
                positions = []
            
            # Reset
            self.currency_exposures = {}
            self.active_positions = {}
            
            for pos in positions:
                symbol = pos.symbol
                ticket = pos.ticket
                volume = pos.volume
                is_buy = pos.type == mt5.ORDER_TYPE_BUY
                direction = "BUY" if is_buy else "SELL"
                
                # Stocker la position
                self.active_positions[ticket] = {
                    'symbol': symbol,
                    'direction': direction,
                    'volume': volume,
                    'profit': pos.profit
                }
                
                # Extraire les devises
                base, quote = self._extract_currencies(symbol)
                
                # Mettre à jour l'exposition de la devise de base
                if base not in self.currency_exposures:
                    self.currency_exposures[base] = CurrencyExposure(currency=base)
                
                if is_buy:
                    self.currency_exposures[base].long_lots += volume
                    self.currency_exposures[base].long_symbols.append(symbol)
                else:
                    self.currency_exposures[base].short_lots += volume
                    self.currency_exposures[base].short_symbols.append(symbol)
                
                # Mettre à jour l'exposition de la devise de cotation (inversée)
                if quote not in self.currency_exposures:
                    self.currency_exposures[quote] = CurrencyExposure(currency=quote)
                
                if is_buy:
                    # Acheter EURUSD = vendre USD
                    self.currency_exposures[quote].short_lots += volume
                    self.currency_exposures[quote].short_symbols.append(symbol)
                else:
                    # Vendre EURUSD = acheter USD
                    self.currency_exposures[quote].long_lots += volume
                    self.currency_exposures[quote].long_symbols.append(symbol)
                    
        except Exception as e:
            logger.error(f"❌ Erreur update positions MT5: {e}")
    
    def can_open_trade(self, symbol: str, direction: str, volume: float = 0.01, confidence: float = 0.0) -> Tuple[bool, List[str]]:
        """
        Vérifie si un trade peut être ouvert sans violer les règles de corrélation.
        VERSION 2.0 - Ajout de la détection de congestion directionnelle.
        
        Args:
            symbol: Symbole à trader
            direction: BUY ou SELL
            volume: Volume prévu
            confidence: Score de confiance du signal (0-100)
            
        Returns:
            (can_trade, reasons) - Liste des raisons si refusé
        """
        reasons = []
        
        # Mettre à jour l'état
        self._update_positions_from_mt5()
        
        # Extraire les devises
        base, quote = self._extract_currencies(symbol)
        is_buy = direction.upper() == "BUY"
        
        # 1. DÉTECTION DE CONGESTION DIRECTIONNELLE (Expert Experience)
        # -----------------------------------------------------------
        # Si on a déjà 2 trades dans la même direction sur une devise majeure,
        # le 3ème doit avoir une confiance > 85%.
        
        for curr in [base, quote]:
            exposure = self.currency_exposures.get(curr, CurrencyExposure(currency=curr))
            
            # Déterminer le sens du nouveau trade pour 'curr'
            new_dir = ""
            if curr == base:
                new_dir = "LONG" if is_buy else "SHORT"
            else: # quote
                new_dir = "SHORT" if is_buy else "LONG"
            
            # Compter positions existantes dans ce sens
            existing_count = 0
            if new_dir == "LONG":
                existing_count = len(exposure.long_symbols)
            else:
                existing_count = len(exposure.short_symbols)
                
            if existing_count >= 2 and confidence < 85.0:
                reasons.append(
                    f"🛑 CONGESTION {curr} ({new_dir}): {existing_count} positions existent. "
                    f"Confiance requise: 85% (Actuelle: {confidence:.1f}%)"
                )

        # 2. VÉRIFICATION DE L'EXPOSITION MAX
        # -----------------------------------------------------------
        base_exposure = self.currency_exposures.get(base, CurrencyExposure(currency=base))
        quote_exposure = self.currency_exposures.get(quote, CurrencyExposure(currency=quote))
        
        # Impact sur devise de base
        new_base_net = base_exposure.net_lots + (volume if is_buy else -volume)
        if abs(new_base_net) > self.max_exposure_per_currency:
            reasons.append(
                f"⚠️ Sur-exposition {base}: {abs(new_base_net):.2f} lots > {self.max_exposure_per_currency} max"
            )
        
        # Impact sur devise de cotation (inversé)
        new_quote_net = quote_exposure.net_lots + (-volume if is_buy else volume)
        if abs(new_quote_net) > self.max_exposure_per_currency:
            reasons.append(
                f"⚠️ Sur-exposition {quote}: {abs(new_quote_net):.2f} lots > {self.max_exposure_per_currency} max"
            )
        
        # 3. VÉRIFIER LES GROUPES DE CORRÉLATION
        # -----------------------------------------------------------
        for group_name, group_config in self.CORRELATION_GROUPS.items():
            if symbol in group_config.get('symbols', []):
                group_positions = [p for p in self.active_positions.values() if p['symbol'] in group_config['symbols']]
                
                # Limite brute de positions
                if len(group_positions) >= self.max_positions_per_group:
                    reasons.append(
                        f"⚠️ Groupe {group_name}: {len(group_positions)}/{self.max_positions_per_group} positions max"
                    )
                
                # Cohérence directionnelle (ICT: Ne pas être bidirectionnel sur un même thème)
                if group_config.get('correlation') == 'positive' and group_positions:
                    group_dir = group_positions[0]['direction']
                    if group_dir != direction.upper() and confidence < 90.0:
                        reasons.append(
                            f"⚠️ Conflit Thématique {group_name}: Position {group_dir} active. "
                            f"Setup opposé nécessite 90% confiance."
                        )
        
        # 4. HEDGE PROTECTION (Empêche de se battre contre soi-même)
        # -----------------------------------------------------------
        for ticket, pos_info in self.active_positions.items():
            if pos_info['symbol'] == symbol:
                if pos_info['direction'] != direction.upper():
                    reasons.append(
                        f"⚠️ Double-sens interdit sur {symbol} ({pos_info['direction']} en cours)"
                    )
        
        can_trade = len(reasons) == 0
        
        if not can_trade:
            self._log_block(symbol, direction, volume, reasons)
        
        return can_trade, reasons
    
    def _log_block(self, symbol: str, direction: str, volume: float, reasons: List[str]):
        """Enregistre un blocage pour analyse."""
        entry = {
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'symbol': symbol,
            'direction': direction,
            'volume': volume,
            'reasons': reasons
        }
        self.block_history.append(entry)
        
        # Garder seulement les 100 derniers
        if len(self.block_history) > 100:
            self.block_history = self.block_history[-100:]
        
        logger.warning(f"🛡️ Trade bloqué: {symbol} {direction} | {', '.join(reasons)}")
    
    def get_exposure_summary(self) -> Dict[str, Dict]:
        """Retourne un résumé de l'exposition par devise."""
        self._update_positions_from_mt5()
        
        summary = {}
        for currency, exposure in self.currency_exposures.items():
            summary[currency] = {
                'net_lots': round(exposure.net_lots, 2),
                'gross_lots': round(exposure.gross_lots, 2),
                'type': exposure.exposure_type,
                'long': round(exposure.long_lots, 2),
                'short': round(exposure.short_lots, 2),
                'is_over_exposed': exposure.is_over_exposed(self.max_exposure_per_currency)
            }
        return summary
    
    def get_group_summary(self) -> Dict[str, Dict]:
        """Retourne un résumé des positions par groupe de corrélation."""
        self._update_positions_from_mt5()
        
        summary = {}
        for group_name, group_config in self.CORRELATION_GROUPS.items():
            group_symbols = group_config.get('symbols', [])
            positions_in_group = []
            
            for ticket, pos_info in self.active_positions.items():
                if pos_info['symbol'] in group_symbols:
                    positions_in_group.append({
                        'symbol': pos_info['symbol'],
                        'direction': pos_info['direction'],
                        'volume': pos_info['volume']
                    })
            
            summary[group_name] = {
                'symbols': group_symbols,
                'correlation': group_config.get('correlation', 'unknown'),
                'positions': positions_in_group,
                'count': len(positions_in_group),
                'max': self.max_positions_per_group
            }
        
        return summary
    
    def print_exposure_report(self):
        """Affiche un rapport d'exposition."""
        exposure = self.get_exposure_summary()
        groups = self.get_group_summary()
        
        print("\n" + "=" * 60)
        print("🛡️ CORRELATION GUARD - EXPOSURE REPORT")
        print("=" * 60)
        
        print("\n📊 EXPOSITION PAR DEVISE:")
        print("-" * 50)
        print(f"{'Devise':<8} {'Net':>8} {'Gross':>8} {'Type':<10} {'Status':<15}")
        print("-" * 50)
        
        for currency, data in sorted(exposure.items()):
            status = "⚠️ OVER" if data['is_over_exposed'] else "✅ OK"
            print(f"{currency:<8} {data['net_lots']:>8.2f} {data['gross_lots']:>8.2f} {data['type']:<10} {status:<15}")
        
        print("\n📈 GROUPES DE CORRÉLATION:")
        print("-" * 50)
        
        for group_name, data in groups.items():
            if data['count'] > 0:
                print(f"\n{group_name} ({data['correlation']}):")
                for pos in data['positions']:
                    print(f"  - {pos['symbol']} {pos['direction']} {pos['volume']} lots")
                print(f"  Total: {data['count']}/{data['max']}")
        
        print("\n" + "=" * 60)


# Singleton
_guard_instance: Optional[CorrelationGuard] = None

def get_correlation_guard(config: Dict = None) -> CorrelationGuard:
    """Retourne l'instance singleton du garde de corrélation."""
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = CorrelationGuard(config=config)
    return _guard_instance


# Test
if __name__ == "__main__":
    guard = CorrelationGuard()
    
    # Simuler quelques tests
    print("\n--- Test 1: Premier trade EURUSD ---")
    can_trade, reasons = guard.can_open_trade("EURUSDm", "BUY", 0.05)
    print(f"Can trade: {can_trade}")
    if reasons:
        for r in reasons:
            print(f"  {r}")
    
    print("\n--- Rapport d'exposition ---")
    guard.print_exposure_report()
