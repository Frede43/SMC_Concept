"""
📊 MODULE DE JOURNAL DE TRADING AMÉLIORÉ
Version 2.0 - Journalisation détaillée pour analyse et optimisation

Enregistre chaque trade avec:
- Contexte de marché (RSI, zone P/D, tendance HTF/LTF)
- Confluences utilisées (Sweep, FVG, SMT, etc.)
- Stratégie déclencheuse
- Score de confiance détaillé
- Résultats et métriques
"""

import os
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from loguru import logger


class TradeJournal:
    """Gère l'enregistrement détaillé des trades dans un fichier CSV."""
    
    def __init__(self, filename: str = "logs/trade_journal.csv"):
        self.filepath = Path(filename)
        # Créer le dossier logs si nécessaire
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        
        # Chemin pour le fichier de décisions (trades rejetés aussi)
        self.decisions_filepath = Path("logs/trade_decisions.csv")
        
        # Initialiser les fichiers avec les en-têtes s'ils n'existent pas
        if not self.filepath.exists():
            self._create_header()
        if not self.decisions_filepath.exists():
            self._create_decisions_header()
    
    def _create_header(self):
        """Crée l'en-tête du journal principal (trades exécutés)."""
        headers = [
            # Identifiants
            "timestamp", "ticket", "symbol", "direction",
            # Prix
            "entry_price", "sl", "tp", "lots",
            # Risque
            "risk_usd", "risk_pips", "risk_reward_ratio",
            # Contexte de marché
            "rsi", "pd_zone", "pd_percentage", "ltf_trend", "htf_trend", "mtf_bias",
            # Confluences
            "setup_type", "confluences", "confidence_score",
            # Stratégie
            "pdl_sweep", "asian_sweep", "silver_bullet", "smt_signal", "amd_phase",
            # Session
            "session", "is_killzone",
            # Résultats
            "exit_price", "exit_time", "duration_minutes",
            "profit_usd", "profit_pips", "profit_pct",
            # Statut
            "status", "exit_reason"
        ]
        with open(self.filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
    
    def _create_decisions_header(self):
        """Crée l'en-tête du fichier des décisions (toutes, y compris rejetées)."""
        headers = [
            "timestamp", "symbol", "decision", "direction", "score",
            "rejection_reason", "rsi", "pd_zone", "htf_trend", "ltf_trend",
            "sweep_detected", "smt_signal", "session", "confluences"
        ]
        with open(self.decisions_filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)

    def log_entry(self, ticket: int, symbol: str, direction: str, entry: float, 
                 sl: float, tp: float, lots: float, risk: float, setup: str, confidence: float,
                 analysis: Dict[str, Any] = None):
        """
        Enregistre l'ouverture d'un trade avec contexte complet.
        
        Args:
            ticket: Numéro du ticket MT5
            symbol: Symbole tradé
            direction: BUY ou SELL
            entry: Prix d'entrée
            sl: Stop loss
            tp: Take profit
            lots: Taille de la position
            risk: Montant à risque en USD
            setup: Description du setup
            confidence: Score de confiance (0-100)
            analysis: Dictionnaire d'analyse complet (optionnel)
        """
        # Extraire les données de contexte si disponibles
        pip_value = 0.0001 if "JPY" not in symbol and "XAU" not in symbol else 0.01
        risk_pips = abs(entry - sl) / pip_value if pip_value > 0 else 0
        reward_pips = abs(tp - entry) / pip_value if pip_value > 0 else 0
        rr_ratio = reward_pips / risk_pips if risk_pips > 0 else 0
        
        # Contexte de marché
        rsi = 50.0
        pd_zone = "unknown"
        pd_pct = 50.0
        ltf_trend = "unknown"
        htf_trend = "unknown"
        mtf_bias = "unknown"
        session = "unknown"
        is_killzone = False
        
        # Stratégies
        pdl_sweep = False
        asian_sweep = False
        silver_bullet = False
        smt_signal = "none"
        amd_phase = "none"
        confluences_list = []
        
        if analysis:
            # Momentum
            momentum = analysis.get('momentum', {})
            rsi = momentum.get('rsi', 50.0)
            
            # Premium/Discount
            pd_zone_obj = analysis.get('pd_zone')
            if pd_zone_obj:
                pd_zone = pd_zone_obj.current_zone.value if hasattr(pd_zone_obj, 'current_zone') else str(pd_zone_obj)
                pd_pct = pd_zone_obj.current_percentage if hasattr(pd_zone_obj, 'current_percentage') else 50.0
            
            # Tendances
            trend = analysis.get('trend')
            ltf_trend = trend.value if hasattr(trend, 'value') else str(trend) if trend else "unknown"
            htf_trend_obj = analysis.get('htf_trend')
            htf_trend = htf_trend_obj.value if hasattr(htf_trend_obj, 'value') else str(htf_trend_obj) if htf_trend_obj else "unknown"
            mtf_bias = str(analysis.get('mtf_bias', 'unknown'))
            
            # Session/Killzone
            kz = analysis.get('killzone', {})
            session = kz.get('current_session', 'unknown')
            is_killzone = kz.get('is_killzone', False)
            
            # Stratégies déclencheuses
            pdl_data = analysis.get('pdl', {})
            pdl_sweep = pdl_data.get('confirmed', False)
            
            asian_data = analysis.get('asian_range', {})
            asian_sweep = asian_data.get('signal', 'NEUTRAL') != 'NEUTRAL'
            
            sb_data = analysis.get('silver_bullet', {})
            silver_bullet = sb_data.get('phase', 'waiting') in ['sweep_detected', 'entry_ready']
            
            smt_data = analysis.get('smt', {})
            smt_signal = smt_data.get('signal', 'none')
            
            amd_data = analysis.get('amd', {})
            amd_phase = amd_data.get('phase', 'none')
            
            # Construire la liste des confluences
            if pdl_sweep: confluences_list.append("PDL_Sweep")
            if asian_sweep: confluences_list.append("Asian_Sweep")
            if silver_bullet: confluences_list.append("Silver_Bullet")
            if smt_signal != 'none': confluences_list.append(f"SMT_{smt_signal}")
            if amd_phase not in ['none', 'waiting']: confluences_list.append(f"AMD_{amd_phase}")
            # Detection fine des FVG (A+ ou Standard)
            fvgs = analysis.get('fvgs', [])
            if fvgs:
                # Vérifier si un FVG est marqué 'is_a_plus_setup'
                is_a_plus = any(f.is_a_plus_setup for f in fvgs if hasattr(f, 'is_a_plus_setup'))
                confluences_list.append("FVG_A+" if is_a_plus else "FVG")
            
            # Detection Breaker Blocks
            breakers = analysis.get('breaker_blocks', [])
            if breakers:
                confluences_list.append("Breaker")
            
            if analysis.get('ifvgs'): confluences_list.append("iFVG")
        
        data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticket": ticket,
            "symbol": symbol,
            "direction": direction,
            "entry_price": f"{entry:.5f}",
            "sl": f"{sl:.5f}",
            "tp": f"{tp:.5f}",
            "lots": lots,
            "risk_usd": f"{risk:.2f}",
            "risk_pips": f"{risk_pips:.1f}",
            "risk_reward_ratio": f"{rr_ratio:.2f}",
            "rsi": f"{rsi:.1f}",
            "pd_zone": pd_zone,
            "pd_percentage": f"{pd_pct:.1f}",
            "ltf_trend": ltf_trend,
            "htf_trend": htf_trend,
            "mtf_bias": mtf_bias,
            "setup_type": setup,
            "confluences": "|".join(confluences_list) if confluences_list else "none",
            "confidence_score": f"{confidence:.0f}",
            "pdl_sweep": pdl_sweep,
            "asian_sweep": asian_sweep,
            "silver_bullet": silver_bullet,
            "smt_signal": smt_signal,
            "amd_phase": amd_phase,
            "session": session,
            "is_killzone": is_killzone,
            "exit_price": "",
            "exit_time": "",
            "duration_minutes": "",
            "profit_usd": "",
            "profit_pips": "",
            "profit_pct": "",
            "status": "OPEN",
            "exit_reason": ""
        }
        self._write_row(data)
        logger.info(f"📝 Trade journalisé: #{ticket} {symbol} {direction} | Confluences: {', '.join(confluences_list)}")

    def log_exit(self, ticket: int, exit_price: float, profit_usd: float, profit_pct: float,
                 entry_price: float = None, entry_time: datetime = None, exit_reason: str = ""):
        """
        Met à jour un trade fermé dans le journal.
        
        Args:
            ticket: Numéro du ticket
            exit_price: Prix de sortie
            profit_usd: Profit/perte en USD
            profit_pct: Profit/perte en pourcentage
            entry_price: Prix d'entrée (pour calculer les pips)
            entry_time: Heure d'entrée (pour calculer la durée)
            exit_reason: Raison de la sortie (TP, SL, Manual, etc.)
        """
        # Calculer les métriques si possible
        profit_pips = ""
        duration = ""
        
        if entry_price:
            pip_val = 0.0001  # Simplifié, pourrait être dynamique
            profit_pips = f"{abs(exit_price - entry_price) / pip_val:.1f}"
            if profit_usd < 0:
                profit_pips = f"-{profit_pips}"
        
        if entry_time:
            duration_td = datetime.now() - entry_time
            duration = f"{duration_td.total_seconds() / 60:.0f}"
        
        # Déterminer la raison de sortie si non fournie
        if not exit_reason:
            if profit_usd > 0:
                exit_reason = "TP" if profit_pct > 1 else "Manual_Profit"
            else:
                exit_reason = "SL" if profit_pct <= -0.5 else "Manual_Loss"
        
        data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticket": ticket,
            "symbol": "---EXIT---",
            "direction": "",
            "entry_price": "",
            "sl": "",
            "tp": "",
            "lots": "",
            "risk_usd": "",
            "risk_pips": "",
            "risk_reward_ratio": "",
            "rsi": "",
            "pd_zone": "",
            "pd_percentage": "",
            "ltf_trend": "",
            "htf_trend": "",
            "mtf_bias": "",
            "setup_type": "",
            "confluences": "",
            "confidence_score": "",
            "pdl_sweep": "",
            "asian_sweep": "",
            "silver_bullet": "",
            "smt_signal": "",
            "amd_phase": "",
            "session": "",
            "is_killzone": "",
            "exit_price": f"{exit_price:.5f}",
            "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration_minutes": duration,
            "profit_usd": f"{profit_usd:.2f}",
            "profit_pips": profit_pips,
            "profit_pct": f"{profit_pct:.2f}",
            "status": "CLOSED",
            "exit_reason": exit_reason
        }
        self._write_row(data)
        status_emoji = "🟢" if profit_usd > 0 else "🔴"
        logger.info(f"📝 Exit journalisé: #{ticket} | {status_emoji} ${profit_usd:.2f} ({profit_pct:.2f}%) | Raison: {exit_reason}")

    def log_decision(self, symbol: str, is_taken: bool, direction: str, score: float,
                    rejection_reason: str = "", analysis: Dict[str, Any] = None):
        """
        Enregistre TOUTES les décisions de trading (prises OU rejetées).
        Utile pour analyser pourquoi certains trades n'ont pas été pris.
        
        Args:
            symbol: Symbole analysé
            is_taken: True si le trade a été exécuté
            direction: Direction du signal
            score: Score de confiance
            rejection_reason: Raison du rejet (si applicable)
            analysis: Dictionnaire d'analyse complet
        """
        # Extraire le contexte
        rsi = 50.0
        pd_zone = "unknown"
        htf_trend = "unknown"
        ltf_trend = "unknown"
        sweep_detected = False
        smt_signal = "none"
        session = "unknown"
        confluences = []
        
        if analysis:
            momentum = analysis.get('momentum', {})
            rsi = momentum.get('rsi', 50.0)
            
            pd_zone_obj = analysis.get('pd_zone')
            pd_zone = pd_zone_obj.current_zone.value if pd_zone_obj and hasattr(pd_zone_obj, 'current_zone') else "unknown"
            
            trend = analysis.get('trend')
            ltf_trend = trend.value if hasattr(trend, 'value') else str(trend) if trend else "unknown"
            htf_trend_obj = analysis.get('htf_trend')
            htf_trend = htf_trend_obj.value if hasattr(htf_trend_obj, 'value') else str(htf_trend_obj) if htf_trend_obj else "unknown"
            
            # Sweeps
            pdl_data = analysis.get('pdl', {})
            asian_data = analysis.get('asian_range', {})
            sweep_detected = pdl_data.get('confirmed', False) or asian_data.get('signal', 'NEUTRAL') != 'NEUTRAL'
            
            smt_data = analysis.get('smt', {})
            smt_signal = smt_data.get('signal', 'none')
            
            kz = analysis.get('killzone', {})
            session = kz.get('current_session', 'unknown')
            
            # Confluences
            if pdl_data.get('confirmed'): confluences.append("PDL")
            if asian_data.get('signal', 'NEUTRAL') != 'NEUTRAL': confluences.append("Asian")
            if analysis.get('silver_bullet', {}).get('phase') in ['sweep_detected', 'entry_ready']: confluences.append("SB")
            if smt_signal != 'none': confluences.append("SMT")
        
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            symbol,
            "TAKEN" if is_taken else "REJECTED",
            direction,
            f"{score:.0f}",
            rejection_reason,
            f"{rsi:.1f}",
            pd_zone,
            htf_trend,
            ltf_trend,
            sweep_detected,
            smt_signal,
            session,
            "|".join(confluences) if confluences else "none"
        ]
        
        try:
            with open(self.decisions_filepath, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except Exception as e:
            logger.error(f"Erreur écriture décision: {e}")

    def _write_row(self, data: dict):
        """Écrit une ligne dans le fichier CSV principal."""
        headers = [
            "timestamp", "ticket", "symbol", "direction",
            "entry_price", "sl", "tp", "lots",
            "risk_usd", "risk_pips", "risk_reward_ratio",
            "rsi", "pd_zone", "pd_percentage", "ltf_trend", "htf_trend", "mtf_bias",
            "setup_type", "confluences", "confidence_score",
            "pdl_sweep", "asian_sweep", "silver_bullet", "smt_signal", "amd_phase",
            "session", "is_killzone",
            "exit_price", "exit_time", "duration_minutes",
            "profit_usd", "profit_pips", "profit_pct",
            "status", "exit_reason"
        ]
        row = [data.get(h, "") for h in headers]
        try:
            with open(self.filepath, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except Exception as e:
            logger.error(f"Erreur écriture journal trade: {e}")
    
    def get_stats_summary(self) -> Dict[str, Any]:
        """
        Génère un résumé statistique des trades journalisés.
        
        Returns:
            Dict avec les statistiques clés
        """
        try:
            import pandas as pd
            df = pd.read_csv(self.filepath)
            
            # Filtrer les lignes de trades (pas les exits)
            trades = df[df['status'] == 'OPEN']
            exits = df[df['status'] == 'CLOSED']
            
            # Calculer les stats
            total_trades = len(trades)
            if total_trades == 0:
                return {"total_trades": 0, "message": "Aucun trade journalisé"}
            
            # Nombre de trades par stratégie
            strategy_counts = {
                "pdl_sweep": trades['pdl_sweep'].sum() if 'pdl_sweep' in trades else 0,
                "asian_sweep": trades['asian_sweep'].sum() if 'asian_sweep' in trades else 0,
                "silver_bullet": trades['silver_bullet'].sum() if 'silver_bullet' in trades else 0,
            }
            
            # Sessions
            session_counts = trades['session'].value_counts().to_dict() if 'session' in trades else {}
            
            return {
                "total_trades": total_trades,
                "strategies": strategy_counts,
                "sessions": session_counts,
                "avg_confidence": trades['confidence_score'].astype(float).mean() if 'confidence_score' in trades else 0,
            }
        except Exception as e:
            logger.error(f"Erreur calcul stats journal: {e}")
            return {"error": str(e)}
