"""
Live Trading Monitor
====================
Système de monitoring en temps réel pour le bot SMC.

Fonctionnalités:
- Affichage du status en temps réel
- Anti-Tilt status
- Micro-timing
- Performance tracking
- Alertes Discord (optionnel)

Usage:
    python live_monitor.py
    python live_monitor.py --symbol XAUUSDm
"""

import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from loguru import logger
import json

# Setup
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

# Imports
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    logger.warning("⚠️ MetaTrader5 non disponible")

from strategy.risk_management import RiskManager
from core.micro_timing import ICTMicroTiming

# Couleurs pour le terminal
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def clear_screen():
    """Clear the terminal screen."""
    import os
    os.system('cls' if os.name == 'nt' else 'clear')


def get_mt5_account_info() -> Dict:
    """Récupère les informations du compte MT5."""
    if not MT5_AVAILABLE:
        return {'error': 'MT5 non disponible'}
    
    try:
        if not mt5.initialize():
            return {'error': 'MT5 non initialisé'}
        
        account_info = mt5.account_info()
        if account_info is None:
            return {'error': 'Pas de compte connecté'}
        
        return {
            'login': account_info.login,
            'server': account_info.server,
            'balance': account_info.balance,
            'equity': account_info.equity,
            'profit': account_info.profit,
            'margin': account_info.margin,
            'margin_free': account_info.margin_free,
            'margin_level': account_info.margin_level,
            'leverage': account_info.leverage
        }
    except Exception as e:
        return {'error': str(e)}


def get_open_positions() -> list:
    """Récupère les positions ouvertes."""
    if not MT5_AVAILABLE:
        return []
    
    try:
        positions = mt5.positions_get()
        if positions is None:
            return []
        
        result = []
        for pos in positions:
            result.append({
                'ticket': pos.ticket,
                'symbol': pos.symbol,
                'type': 'BUY' if pos.type == 0 else 'SELL',
                'volume': pos.volume,
                'price_open': pos.price_open,
                'price_current': pos.price_current,
                'sl': pos.sl,
                'tp': pos.tp,
                'profit': pos.profit,
                'time': datetime.fromtimestamp(pos.time)
            })
        return result
    except Exception as e:
        logger.error(f"Erreur positions: {e}")
        return []


def format_profit(profit: float) -> str:
    """Formate le profit avec couleur."""
    if profit >= 0:
        return f"{Colors.GREEN}+${profit:.2f}{Colors.ENDC}"
    else:
        return f"{Colors.RED}${profit:.2f}{Colors.ENDC}"


def format_risk_level(level: str) -> str:
    """Formate le niveau de risque avec couleur."""
    colors = {
        'NORMAL': Colors.GREEN,
        'REDUCED': Colors.YELLOW,
        'MINIMAL': Colors.YELLOW,
        'PAUSED': Colors.RED,
        'STOPPED': Colors.RED
    }
    color = colors.get(level, Colors.ENDC)
    return f"{color}{level}{Colors.ENDC}"


def print_header():
    """Affiche l'en-tête du monitor."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}")
    print("=" * 70)
    print("  🤖 SMC TRADING BOT - LIVE MONITOR v2.5")
    print("=" * 70)
    print(f"{Colors.ENDC}")


def print_account_info(account: Dict):
    """Affiche les informations du compte."""
    print(f"\n{Colors.BOLD}📊 COMPTE{Colors.ENDC}")
    print("-" * 40)
    
    if 'error' in account:
        print(f"  {Colors.RED}❌ {account['error']}{Colors.ENDC}")
        return
    
    print(f"  Login: {account['login']} @ {account['server']}")
    print(f"  Balance: ${account['balance']:,.2f}")
    print(f"  Equity: ${account['equity']:,.2f}")
    print(f"  Profit: {format_profit(account['profit'])}")
    print(f"  Marge libre: ${account['margin_free']:,.2f}")
    print(f"  Leverage: 1:{account['leverage']}")


def print_positions(positions: list):
    """Affiche les positions ouvertes."""
    print(f"\n{Colors.BOLD}📈 POSITIONS OUVERTES ({len(positions)}){Colors.ENDC}")
    print("-" * 60)
    
    if not positions:
        print("  Aucune position ouverte")
        return
    
    for pos in positions:
        direction = Colors.GREEN + pos['type'] + Colors.ENDC if pos['type'] == 'BUY' else Colors.RED + pos['type'] + Colors.ENDC
        profit_str = format_profit(pos['profit'])
        
        print(f"  #{pos['ticket']} | {pos['symbol']} {direction} {pos['volume']} lots")
        print(f"    Entry: {pos['price_open']:.5f} → Current: {pos['price_current']:.5f}")
        print(f"    SL: {pos['sl']:.5f} | TP: {pos['tp']:.5f}")
        print(f"    Profit: {profit_str} | Open: {pos['time'].strftime('%H:%M:%S')}")
        print()


def print_risk_status(risk_manager: RiskManager):
    """Affiche le status du Risk Manager et Anti-Tilt."""
    print(f"\n{Colors.BOLD}🛡️ RISK MANAGEMENT & ANTI-TILT{Colors.ENDC}")
    print("-" * 40)
    
    status = risk_manager.get_anti_tilt_status()
    
    # Equity info
    eq = status.get('equity', {})
    print(f"  Equity: ${eq.get('current', 0):,.2f}")
    print(f"  Peak: ${eq.get('peak', 0):,.2f}")
    dd = eq.get('drawdown_pct', 0)
    dd_color = Colors.GREEN if dd < 5 else (Colors.YELLOW if dd < 10 else Colors.RED)
    print(f"  Drawdown: {dd_color}{dd:.1f}%{Colors.ENDC}")
    
    # Risk level
    risk = status.get('risk', {})
    level = risk.get('level', 'UNKNOWN')
    print(f"\n  Risk Level: {format_risk_level(level)}")
    print(f"  Multiplier: x{risk.get('multiplier', 1.0):.2f}")
    
    # Kelly
    kelly = status.get('kelly', {})
    if kelly.get('enabled', False):
        print(f"\n  Kelly Optimal: {kelly.get('optimal', 0):.2f}%")
        print(f"  Kelly Adjusted: {kelly.get('adjusted', 0):.2f}%")
    
    # Daily stats
    print(f"\n  Trades Today: {status.get('trades_today', 0)}/{risk_manager.max_daily_trades}")
    
    # Streaks
    streaks = status.get('streaks', {})
    if streaks.get('consecutive_losses', 0) > 0:
        print(f"  {Colors.RED}⚠️ Pertes consécutives: {streaks['consecutive_losses']}{Colors.ENDC}")


def print_timing_status(timing: ICTMicroTiming):
    """Affiche le status du micro-timing."""
    print(f"\n{Colors.BOLD}⏰ ICT MICRO-TIMING{Colors.ENDC}")
    print("-" * 40)
    
    analysis = timing.analyze()
    
    print(f"  Session: {analysis.session_name} ({analysis.session_quality})")
    print(f"  Phase: {analysis.session_phase.value}")
    print(f"  PO3: {analysis.po3_phase.value}")
    
    # Can trade?
    if analysis.can_enter:
        print(f"\n  {Colors.GREEN}✅ TRADING AUTORISÉ{Colors.ENDC}")
        print(f"  Qualité: {analysis.entry_quality}")
    else:
        print(f"\n  {Colors.RED}❌ ATTENDRE{Colors.ENDC}")
        print(f"  Raison: {analysis.reason}")
    
    # Score
    score = timing.get_session_quality_score()
    score_color = Colors.GREEN if score >= 70 else (Colors.YELLOW if score >= 50 else Colors.RED)
    print(f"\n  Score: {score_color}{score}/100{Colors.ENDC}")
    
    # Next window
    next_window = timing.get_next_optimal_window()
    print(f"  Prochaine fenêtre: {next_window.strftime('%H:%M')}")


def print_footer():
    """Affiche le footer avec l'heure."""
    print(f"\n{Colors.CYAN}" + "=" * 70)
    print(f"  Dernière mise à jour: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Appuyez sur Ctrl+C pour quitter")
    print("=" * 70 + f"{Colors.ENDC}\n")


def run_monitor(symbol: str = None, refresh_rate: int = 5):
    """
    Exécute le monitoring en temps réel.
    
    Args:
        symbol: Filtre sur un symbole spécifique
        refresh_rate: Intervalle de rafraîchissement en secondes
    """
    # Initialiser les composants
    import yaml
    config_path = ROOT_DIR / "config" / "settings.yaml"
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    risk_manager = RiskManager(config)
    timing = ICTMicroTiming(
        timezone_offset=config.get('filters', {}).get('killzones', {}).get('timezone_offset', 0)
    )
    
    print(f"\n🚀 Démarrage du monitor...")
    print(f"   Symbol filter: {symbol or 'ALL'}")
    print(f"   Refresh rate: {refresh_rate}s")
    
    # Initialiser MT5
    if MT5_AVAILABLE:
        if not mt5.initialize():
            print(f"{Colors.RED}❌ Impossible d'initialiser MT5{Colors.ENDC}")
            return
    
    try:
        while True:
            clear_screen()
            
            # En-tête
            print_header()
            
            # Compte
            account = get_mt5_account_info()
            print_account_info(account)
            
            # Mettre à jour l'equity dans le risk manager
            if 'equity' in account:
                risk_manager.update_equity(account['equity'])
            
            # Positions
            positions = get_open_positions()
            if symbol:
                positions = [p for p in positions if p['symbol'] == symbol]
            print_positions(positions)
            
            # Risk status
            print_risk_status(risk_manager)
            
            # Timing
            print_timing_status(timing)
            
            # Warnings
            adjusted_risk, reason, warnings = risk_manager.get_adjusted_risk_percent()
            if warnings:
                print(f"\n{Colors.BOLD}{Colors.YELLOW}⚠️ ALERTES{Colors.ENDC}")
                print("-" * 40)
                for w in warnings:
                    print(f"  {w}")
            
            # Footer
            print_footer()
            
            # Attendre
            time.sleep(refresh_rate)
            
    except KeyboardInterrupt:
        print("\n\n👋 Monitor arrêté.")
    finally:
        if MT5_AVAILABLE:
            mt5.shutdown()


def main():
    parser = argparse.ArgumentParser(description='SMC Trading Bot Live Monitor')
    parser.add_argument('--symbol', type=str, default=None,
                       help='Filter by symbol (e.g., XAUUSDm)')
    parser.add_argument('--refresh', type=int, default=5,
                       help='Refresh rate in seconds (default: 5)')
    
    args = parser.parse_args()
    run_monitor(symbol=args.symbol, refresh_rate=args.refresh)


if __name__ == "__main__":
    main()
