"""
Trade History Manager
Gestion automatique de l'historique des trades
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from loguru import logger
from dataclasses import dataclass, asdict


@dataclass
class TradeRecord:
    """Représente un trade enregistré."""
    ticket: int
    symbol: str
    direction: str
    volume: float
    entry_price: float
    close_price: float
    sl: float
    tp: float
    profit: float
    pips: float
    open_time: str
    close_time: str
    duration_minutes: int
    result: str  # WIN, LOSS, BREAKEVEN
    smc_compliance: float  # Score SMC (0-100)
    reasons: List[str] = None  # Raisons du signal
    
    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []


class TradeHistoryManager:
    """
    Gestionnaire d'historique des trades.
    
    Fonctionnalités:
    - Sauvegarde automatique des trades
    - Calcul des statistiques
    - Export des données
    """
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.history_file = os.path.join(data_dir, "trade_history.json")
        self.stats_file = os.path.join(data_dir, "performance_stats.json")
        
        # Créer le dossier data si nécessaire
        os.makedirs(data_dir, exist_ok=True)
        
        # Charger l'historique existant
        self.trades: List[Dict] = self._load_history()
        
        logger.info(f"📊 TradeHistoryManager initialisé - {len(self.trades)} trades chargés")
    
    def _load_history(self) -> List[Dict]:
        """Charge l'historique depuis le fichier JSON."""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Erreur chargement historique: {e}")
                return []
        return []
    
    def _save_history(self):
        """Sauvegarde l'historique dans le fichier JSON."""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.trades, f, indent=2, default=str)
            logger.debug(f"Historique sauvegardé: {len(self.trades)} trades")
        except Exception as e:
            logger.error(f"Erreur sauvegarde historique: {e}")
    
    def add_trade(self, trade: TradeRecord):
        """Ajoute un trade à l'historique."""
        trade_dict = asdict(trade)
        
        # Vérifier si le trade existe déjà (par ticket)
        existing = next((t for t in self.trades if t.get('ticket') == trade.ticket), None)
        if existing:
            logger.debug(f"Trade #{trade.ticket} déjà enregistré, mise à jour...")
            self.trades.remove(existing)
        
        self.trades.append(trade_dict)
        self._save_history()
        
        logger.info(f"📝 Trade enregistré: #{trade.ticket} {trade.symbol} {trade.direction} -> {trade.result}")
    
    def record_closed_trade(self, position_data: Dict, signal_reasons: List[str] = None, 
                           smc_score: float = 0) -> Optional[TradeRecord]:
        """
        Enregistre un trade fermé depuis les données de position MT5.
        
        Args:
            position_data: Données de la position (depuis MT5)
            signal_reasons: Raisons du signal SMC
            smc_score: Score de compliance SMC
        """
        try:
            # Calculer les pips
            entry = position_data.get('entry_price', position_data.get('price_open', 0))
            close = position_data.get('close_price', 0)
            symbol = position_data.get('symbol', 'UNKNOWN')
            direction = position_data.get('direction', position_data.get('type', 'UNKNOWN'))
            
            pip_value = 0.01 if 'JPY' in symbol or 'XAU' in symbol else 0.0001
            
            if direction.upper() == 'BUY':
                pips = (close - entry) / pip_value
            else:
                pips = (entry - close) / pip_value
            
            # Déterminer le résultat
            profit = position_data.get('profit', 0)
            if profit > 0:
                result = "WIN"
            elif profit < 0:
                result = "LOSS"
            else:
                result = "BREAKEVEN"
            
            # Calculer la durée
            open_time = position_data.get('open_time', datetime.now())
            close_time = position_data.get('close_time', datetime.now())
            
            if isinstance(open_time, str):
                open_time = datetime.fromisoformat(open_time)
            if isinstance(close_time, str):
                close_time = datetime.fromisoformat(close_time)
            
            duration = int((close_time - open_time).total_seconds() / 60)
            
            trade = TradeRecord(
                ticket=position_data.get('ticket', 0),
                symbol=symbol,
                direction=direction.upper(),
                volume=position_data.get('volume', 0),
                entry_price=entry,
                close_price=close,
                sl=position_data.get('sl', 0),
                tp=position_data.get('tp', 0),
                profit=profit,
                pips=round(pips, 1),
                open_time=open_time.isoformat() if hasattr(open_time, 'isoformat') else str(open_time),
                close_time=close_time.isoformat() if hasattr(close_time, 'isoformat') else str(close_time),
                duration_minutes=duration,
                result=result,
                smc_compliance=smc_score,
                reasons=signal_reasons or []
            )
            
            self.add_trade(trade)
            return trade
            
        except Exception as e:
            logger.error(f"Erreur enregistrement trade: {e}")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Calcule et retourne les statistiques de trading."""
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'total_profit': 0,
                'avg_profit': 0,
                'avg_pips': 0,
                'best_trade': None,
                'worst_trade': None
            }
        
        wins = [t for t in self.trades if t.get('result') == 'WIN']
        losses = [t for t in self.trades if t.get('result') == 'LOSS']
        
        total_profit = sum(t.get('profit', 0) for t in self.trades)
        total_pips = sum(t.get('pips', 0) for t in self.trades)
        
        # Meilleur et pire trade
        sorted_by_profit = sorted(self.trades, key=lambda x: x.get('profit', 0))
        
        stats = {
            'total_trades': len(self.trades),
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'win_rate': round(len(wins) / len(self.trades) * 100, 1) if self.trades else 0,
            'total_profit': round(total_profit, 2),
            'total_pips': round(total_pips, 1),
            'avg_profit': round(total_profit / len(self.trades), 2) if self.trades else 0,
            'avg_pips': round(total_pips / len(self.trades), 1) if self.trades else 0,
            'best_trade': sorted_by_profit[-1] if sorted_by_profit else None,
            'worst_trade': sorted_by_profit[0] if sorted_by_profit else None,
            'avg_duration_min': round(sum(t.get('duration_minutes', 0) for t in self.trades) / len(self.trades), 0) if self.trades else 0
        }
        
        # Sauvegarder les stats
        self._save_stats(stats)
        
        return stats
    
    def _save_stats(self, stats: Dict):
        """Sauvegarde les statistiques."""
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(stats, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Erreur sauvegarde stats: {e}")
    
    def get_trades_by_symbol(self, symbol: str) -> List[Dict]:
        """Retourne les trades pour un symbole spécifique."""
        return [t for t in self.trades if t.get('symbol') == symbol]
    
    def get_trades_today(self) -> List[Dict]:
        """Retourne les trades du jour."""
        today = datetime.now().date().isoformat()
        return [t for t in self.trades if t.get('close_time', '').startswith(today)]
    
    def get_recent_trades(self, count: int = 10) -> List[Dict]:
        """Retourne les N derniers trades."""
        return self.trades[-count:] if len(self.trades) >= count else self.trades
