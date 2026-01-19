"""
📊 PAPER TRADING TRACKER - Compte 300$

Script pour suivre et analyser les performances du bot en mode DEMO.
Génère des rapports quotidiens et hebdomadaires.

Auteur: Expert SMC/ICT  
Date: 19 Janvier 2026
"""

import json
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict
import statistics

class PaperTradingTracker:
    """Tracker de performance pour validation paper trading."""
    
    def __init__(self, initial_capital: float = 300.0):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.trades_file = Path("paper_trading_trades.csv")
        self.stats_file = Path("paper_trading_stats.json")
        self.init_tracker()
    
    def init_tracker(self):
        """Initialise les fichiers de tracking."""
        if not self.trades_file.exists():
            with open(self.trades_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Date', 'Heure', 'Symbole', 'Direction', 'Entry', 'SL', 'TP',
                    'Lot Size', 'Résultat', 'P&L $', 'P&L %', 'Balance', 'Notes'
                ])
            print("📊 Fichier trades créé: paper_trading_trades.csv")
        
        if not self.stats_file.exists():
            stats = {
                'start_date': datetime.now().isoformat(),
                'initial_capital': self.initial_capital,
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'breakeven': 0
            }
            with open(self.stats_file, 'w') as f:
                json.dump(stats, f, indent=2)
            print("📊 Fichier stats créé: paper_trading_stats.json")
    
    def add_trade(self, trade_data: Dict):
        """
        Ajoute un trade au tracker.
        
        Args:
            trade_data: {
                'symbol': str,
                'direction': 'BUY'/'SELL',
                'entry': float,
                'sl': float,
                'tp': float,
                'lot_size': float,
                'result': 'WIN'/'LOSS'/'BE',
                'pnl_usd': float,
                'notes': str (optional)
            }
        """
        now = datetime.now()
        
        # Calculer P&L %
        pnl_pct = (trade_data['pnl_usd'] / self.current_capital) * 100
        self.current_capital += trade_data['pnl_usd']
        
        # Ajouter au CSV
        with open(self.trades_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                now.strftime('%Y-%m-%d'),
                now.strftime('%H:%M:%S'),
                trade_data['symbol'],
                trade_data['direction'],
                trade_data['entry'],
                trade_data['sl'],
                trade_data['tp'],
                trade_data['lot_size'],
                trade_data['result'],
                f"{trade_data['pnl_usd']:.2f}",
                f"{pnl_pct:.2f}",
                f"{self.current_capital:.2f}",
                trade_data.get('notes', '')
            ])
        
        # Mettre à jour stats
        with open(self.stats_file, 'r') as f:
            stats = json.load(f)
        
        stats['total_trades'] += 1
        if trade_data['result'] == 'WIN':
            stats['wins'] += 1
        elif trade_data['result'] == 'LOSS':
            stats['losses'] += 1
        else:
            stats['breakeven'] += 1
        
        stats['last_update'] = now.isoformat()
        stats['current_capital'] = self.current_capital
        stats['total_pnl'] = self.current_capital - self.initial_capital
        stats['roi_pct'] = ((self.current_capital - self.initial_capital) / self.initial_capital) * 100
        
        with open(self.stats_file, 'w') as f:
            json.dump(stats, f, indent=2)
        
        print(f"✅ Trade ajouté: {trade_data['symbol']} {trade_data['result']} (P&L: ${trade_data['pnl_usd']:.2f})")
    
    def get_daily_report(self) -> str:
        """Génère un rapport quotidien."""
        with open(self.stats_file, 'r') as f:
            stats = json.load(f)
        
        win_rate = (stats['wins'] / stats['total_trades'] * 100) if stats['total_trades'] > 0 else 0
        
        report = f"""
{'=' * 70}
📊 RAPPORT QUOTIDIEN - PAPER TRADING
{'=' * 70}

Capital Initial: ${self.initial_capital:.2f}
Capital Actuel: ${stats.get('current_capital', self.initial_capital):.2f}
P&L Total: ${stats.get('total_pnl', 0):.2f} ({stats.get('roi_pct', 0):.2f}%)

Trades Total: {stats['total_trades']}
├─ Gagnants: {stats['wins']} ✅
├─ Perdants: {stats['losses']} ❌
└─ Break-Even: {stats['breakeven']} ➖

Win Rate: {win_rate:.1f}%

{'=' * 70}
"""
        return report
    
    def get_weekly_analysis(self) -> str:
        """Analyse hebdomadaire détaillée."""
        # Charger tous les trades
        trades = []
        with open(self.trades_file, 'r') as f:
            reader = csv.DictReader(f)
            trades = list(reader)
        
        if not trades:
            return "⚠️ Aucun trade pour analyse hebdomadaire"
        
        # Analyser dernière semaine
        one_week_ago = datetime.now() - timedelta(days=7)
        weekly_trades = [
            t for t in trades 
            if datetime.strptime(t['Date'], '%Y-%m-%d') >= one_week_ago
        ]
        
        if not weekly_trades:
            return "⚠️ Aucun trade dans les 7 derniers jours"
        
        # Calculs
        total = len(weekly_trades)
        wins = sum(1 for t in weekly_trades if t['Résultat'] == 'WIN')
        losses = sum(1 for t in weekly_trades if t['Résultat'] == 'LOSS')
        win_rate = (wins / total * 100) if total > 0 else 0
        
        pnls = [float(t['P&L $']) for t in weekly_trades]
        total_pnl = sum(pnls)
        avg_win = statistics.mean([p for p in pnls if p > 0]) if wins > 0 else 0
        avg_loss = statistics.mean([p for p in pnls if p < 0]) if losses > 0 else 0
        
        symbols_traded = {}
        for t in weekly_trades:
            symbols_traded[t['Symbole']] = symbols_traded.get(t['Symbole'], 0) + 1
        
        report = f"""
{'=' * 70}
📈 ANALYSE HEBDOMADAIRE (7 derniers jours)
{'=' * 70}

Performance:
├─ Trades: {total}
├─ Win Rate: {win_rate:.1f}%
├─ P&L Total: ${total_pnl:.2f}
├─ Avg Win: ${avg_win:.2f}
└─ Avg Loss: ${avg_loss:.2f}

Symboles Tradés:
"""
        for symbol, count in sorted(symbols_traded.items(), key=lambda x: x[1], reverse=True):
            report += f"├─ {symbol}: {count} trades\n"
        
        report += f"\n{'=' * 70}\n"
        
        # Validation objectifs
        report += "\n🎯 VALIDATION OBJECTIFS PAPER TRADING:\n\n"
        
        checks = [
            (total >= 20, f"{'✅' if total >= 20 else '❌'} 20+ trades ({total}/20)"),
            (win_rate >= 50, f"{'✅' if win_rate >= 50 else '❌'} Win Rate > 50% ({win_rate:.1f}%)"),
            (total_pnl > 0, f"{'✅' if total_pnl > 0 else '❌'} ROI positif (${total_pnl:.2f})"),
        ]
        
        all_passed = all(check[0] for check in checks)
        
        for _, check_str in checks:
            report += f"  {check_str}\n"
        
        if all_passed:
            report += "\n✅✅✅ TOUS OBJECTIFS ATTEINTS! ✅✅✅\n"
            report += "🚀 Bot prêt pour déploiement progressif (50$ → 150$ → 300$)\n"
        else:
            report += "\n⚠️ Objectifs non atteints - Continuer paper trading\n"
        
        report += f"{'=' * 70}\n"
        
        return report
    
    def check_lot_sizes(self) -> str:
        """Vérifie que tous les lot sizes sont dans les limites sécuritaires."""
        trades = []
        with open(self.trades_file, 'r') as f:
            reader = csv.DictReader(f)
            trades = list(reader)
        
        if not trades:
            return "⚠️ Aucun trade à vérifier"
        
        issues = []
        for t in trades:
            lot = float(t['Lot Size'])
            symbol = t['Symbole']
            
            # Vérifications
            if lot > 0.10:
                issues.append(f"⚠️ {symbol} ({t['Date']}): Lot {lot} > 0.10 (petit compte)")
            if lot > 1.0:
                issues.append(f"🚨 {symbol} ({t['Date']}): Lot {lot} > 1.0 ABSOLUTE MAX!")
            if 'BTC' in symbol and lot > 0.05:
                issues.append(f"⚠️ {symbol} ({t['Date']}): Lot {lot} > 0.05 (crypto max)")
        
        if issues:
            report = "🚨 PROBLÈMES DÉTECTÉS:\n\n"
            for issue in issues:
                report += f"  {issue}\n"
            report += "\n⚠️ VÉRIFIER CORRECTIONS RISK MANAGEMENT"
            return report
        else:
            return "✅ Tous les lot sizes dans limites sécuritaires"


def demo_usage():
    """Exemple d'utilisation du tracker."""
    print("=" * 70)
    print("📚 EXEMPLE D'UTILISATION - PAPER TRADING TRACKER")
    print("=" * 70)
    print()
    
    tracker = PaperTradingTracker(initial_capital=300.0)
    
    print("📝 COMMENT UTILISER:\n")
    print("1. Créer tracker:")
    print("   tracker = PaperTradingTracker(initial_capital=300.0)\n")
    
    print("2. Ajouter trade gagnant:")
    print("""   tracker.add_trade({
       'symbol': 'EURUSDm',
       'direction': 'BUY',
       'entry': 1.2500,
       'sl': 1.2450,
       'tp': 1.2600,
       'lot_size': 0.01,
       'result': 'WIN',
       'pnl_usd': 1.50,
       'notes': 'PDH sweep + FVG confluence'
   })\n""")
    
    print("3. Ajouter trade perdant:")
    print("""   tracker.add_trade({
       'symbol': 'GBPUSDm',
       'direction': 'SELL',
       'entry': 1.3500,
       'sl': 1.3520,
       'tp': 1.3450,
       'lot_size': 0.01,
       'result': 'LOSS',
       'pnl_usd': -0.60,
       'notes': 'Faux signal, news impact'
   })\n""")
    
    print("4. Voir rapport quotidien:")
    print("   print(tracker.get_daily_report())\n")
    
    print("5. Analyse hebdomadaire:")
    print("   print(tracker.get_weekly_analysis())\n")
    
    print("6. Vérifier lot sizes:")
    print("   print(tracker.check_lot_sizes())\n")
    
    print("=" * 70)
    print("\n📊 FICHIERS CRÉÉS:")
    print("  - paper_trading_trades.csv (tous les trades)")
    print("  - paper_trading_stats.json (statistiques)")
    print("\n✅ Tracker prêt à utiliser!")


if __name__ == "__main__":
    demo_usage()
