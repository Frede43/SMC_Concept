"""
📊 LIVE TRADING DASHBOARD
Version 1.0 - Interface web temps réel pour le monitoring du bot SMC

Fonctionnalités:
- Vue des positions ouvertes
- Statistiques de performance live
- Graphiques de P&L
- Alertes et notifications
- Session performance heatmap
- Contrôles du bot (pause, resume, kill switch)

Utilise Flask pour le serveur web et auto-refresh JavaScript.
"""

import os
import sys
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

# Ajouter le répertoire racine au path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from loguru import logger

try:
    from flask import Flask, render_template_string, jsonify, request
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    logger.warning("⚠️ Flask non installé. Dashboard non disponible. pip install flask")

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False


# ============================================
# TEMPLATE HTML DU DASHBOARD
# ============================================
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 SMC Trading Bot Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #02040a;
            --bg-secondary: #0d1117;
            --bg-tertiary: #161b22;
            --border-color: #30363d;
            --text-primary: #f0f6fc;
            --text-secondary: #8b949e;
            --accent-blue: #58a6ff;
            --accent-green: #3fb950;
            --accent-red: #f85149;
            --accent-yellow: #d29922;
            --accent-purple: #a371f7;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: radial-gradient(circle at top right, #161b22, #02040a);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 20px;
            line-height: 1.6;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 20px;
        }
        
        .logo {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .logo h1 {
            font-size: 24px;
            font-weight: 600;
        }
        
        .status-badge {
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 500;
            text-transform: uppercase;
        }
        
        .status-running { background: rgba(63, 185, 80, 0.2); color: var(--accent-green); }
        .status-paused { background: rgba(210, 153, 34, 0.2); color: var(--accent-yellow); }
        .status-stopped { background: rgba(248, 81, 73, 0.2); color: var(--accent-red); }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .card {
            background: rgba(13, 17, 23, 0.7);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 24px;
            transition: all 0.4s cubic-bezier(0.165, 0.84, 0.44, 1);
            backdrop-filter: blur(12px);
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        }
        
        .card:hover {
            border-color: rgba(88, 166, 255, 0.5);
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2), 0 10px 10px -5px rgba(0, 0, 0, 0.1);
            transform: translateY(-2px);
        }
        
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 12px;
        }
        
        .card-title {
            font-size: 14px;
            color: var(--text-secondary);
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .card-value {
            font-size: 32px;
            font-weight: 700;
        }
        
        .positive { color: var(--accent-green); }
        .negative { color: var(--accent-red); }
        .neutral { color: var(--text-secondary); }
        
        .stat-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .stat-card {
            background: linear-gradient(135deg, rgba(22, 27, 34, 0.8), rgba(13, 17, 23, 0.9));
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 20px;
            text-align: center;
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
            backdrop-filter: blur(8px);
        }

        .stat-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 4px;
            background: var(--accent-blue);
            opacity: 0.5;
        }
        
        .stat-label {
            font-size: 13px;
            color: var(--text-secondary);
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-weight: 500;
        }
        
        .stat-value {
            font-size: 24px;
            font-weight: 600;
        }
        
        .positions-table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .positions-table th,
        .positions-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
        }
        
        .positions-table th {
            color: var(--text-secondary);
            font-size: 12px;
            font-weight: 500;
            text-transform: uppercase;
        }
        
        .positions-table tr:hover {
            background: var(--bg-tertiary);
        }
        
        .direction-badge {
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 500;
        }
        
        .buy { background: rgba(63, 185, 80, 0.2); color: var(--accent-green); }
        .sell { background: rgba(248, 81, 73, 0.2); color: var(--accent-red); }
        
        .session-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
        }
        
        .session-card {
            background: linear-gradient(145deg, var(--bg-tertiary), rgba(22, 27, 34, 0.4));
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 16px;
            text-align: center;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
            backdrop-filter: blur(10px);
        }

        .session-card:hover {
            transform: translateY(-5px) scale(1.02);
            border-color: var(--accent-blue);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3), 0 0 20px rgba(88, 166, 255, 0.1);
        }

        .session-icon {
            font-size: 24px;
            margin-bottom: 8px;
            display: block;
        }
        
        .session-name {
            font-size: 12px;
            color: var(--text-secondary);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 12px;
        }
        
        .session-wr {
            font-size: 24px;
            font-weight: 800;
            margin-bottom: 8px;
            display: block;
        }

        .wr-bar-container {
            width: 100%;
            height: 6px;
            background: rgba(48, 54, 61, 0.5);
            border-radius: 10px;
            margin: 10px 0;
            overflow: hidden;
        }

        .wr-bar {
            height: 100%;
            border-radius: 10px;
            transition: width 1s ease-out;
        }

        .wr-high { background: linear-gradient(90deg, #238636, #3fb950); }
        .wr-mid { background: linear-gradient(90deg, #d29922, #e3b341); }
        .wr-low { background: linear-gradient(90deg, #da3633, #f85149); }

        .session-trades {
            font-size: 11px;
            color: var(--text-secondary);
            font-style: italic;
        }
        
        .controls {
            display: flex;
            gap: 12px;
        }
        
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .btn-primary { background: var(--accent-blue); color: white; }
        .btn-warning { background: var(--accent-yellow); color: black; }
        .btn-danger { background: var(--accent-red); color: white; }
        
        .btn:hover { opacity: 0.8; transform: translateY(-1px); }
        
        .alerts {
            max-height: 200px;
            overflow-y: auto;
        }
        
        .alert-item {
            display: flex;
            gap: 12px;
            padding: 10px;
            background: var(--bg-tertiary);
            border-radius: 6px;
            margin-bottom: 8px;
            font-size: 13px;
        }
        
        .alert-time {
            color: var(--text-secondary);
            white-space: nowrap;
        }
        
        .refresh-indicator {
            font-size: 12px;
            color: var(--text-secondary);
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .live-dot {
            width: 8px;
            height: 8px;
            background: var(--accent-green);
            border-radius: 50%;
            animation: pulse 2s infinite;
            display: inline-block;
            margin-right: 8px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">
                <span style="font-size: 32px;">🤖</span>
                <h1>SMC Trading Bot</h1>
                <span class="status-badge status-{{ status.lower() }}">{{ status }}</span>
            </div>
            <div class="controls">
                <span class="refresh-indicator"><span class="live-dot"></span>Auto-refresh: 5s</span>
                <button class="btn btn-warning" onclick="pauseBot()">⏸️ Pause</button>
                <button class="btn btn-danger" onclick="killSwitch()">🛑 Kill Switch</button>
            </div>
        </header>
        
        <!-- Stats principales -->
        <div class="stat-grid">
            <div class="stat-card">
                <div class="stat-label">Balance</div>
                <div class="stat-value">${{ "%.2f"|format(account.balance) }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Equity</div>
                <div class="stat-value">${{ "%.2f"|format(account.equity) }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Floating P&L</div>
                <div class="stat-value {{ 'positive' if account.floating_pnl >= 0 else 'negative' }}">
                    {{ "+" if account.floating_pnl >= 0 else "" }}${{ "%.2f"|format(account.floating_pnl) }}
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Today's P&L</div>
                <div class="stat-value {{ 'positive' if stats.daily_pnl >= 0 else 'negative' }}">
                    {{ "+" if stats.daily_pnl >= 0 else "" }}${{ "%.2f"|format(stats.daily_pnl) }}
                </div>
            </div>
        </div>
        
        <div class="grid">
            <!-- Positions ouvertes -->
            <div class="card" style="grid-column: span 2;">
                <div class="card-header">
                    <span class="card-title">📊 Positions Ouvertes ({{ positions|length }})</span>
                </div>
                {% if positions %}
                <table class="positions-table">
                    <thead>
                        <tr>
                            <th>Symbole</th>
                            <th>Setup (SMC)</th>
                            <th>Direction</th>
                            <th>Volume</th>
                            <th>Entry</th>
                            <th>Current</th>
                            <th>P&L</th>
                            <th>Durée</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for pos in positions %}
                        <tr>
                            <td><strong>{{ pos.symbol }}</strong></td>
                            <td style="font-size: 11px; color: var(--accent-blue);">{{ pos.comment }}</td>
                            <td><span class="direction-badge {{ pos.direction.lower() }}">{{ pos.direction }}</span></td>
                            <td>{{ pos.volume }}</td>
                            <td>{{ "%.5f"|format(pos.entry_price) }}</td>
                            <td>{{ "%.5f"|format(pos.current_price) }}</td>
                            <td class="{{ 'positive' if pos.profit >= 0 else 'negative' }}">
                                {{ "+" if pos.profit >= 0 else "" }}${{ "%.2f"|format(pos.profit) }}
                            </td>
                            <td>{{ pos.duration }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                {% else %}
                <p style="color: var(--text-secondary); text-align: center; padding: 40px;">
                    Aucune position ouverte
                </p>
                {% endif %}
            </div>
            
            <!-- Macro Contexte (Nouveau Widget Complet) -->
            <div class="card" style="grid-column: span 2;">
                <div class="card-header">
                    <span class="card-title">🌍 Macro Contexte & News (Mode: {{ trading_mode }})</span>
                </div>
                <div class="session-grid" style="grid-template-columns: repeat(3, 1fr);">
                    <div class="session-card">
                        <div class="session-name">News Source & Status</div>
                        <div class="session-wr positive">{{ news.source }}</div>
                        <div style="font-size: 11px; color: var(--text-secondary);">
                            {{ news.high_impact_count }} High Impact à venir
                        </div>
                    </div>
                    <div class="session-card">
                        <div class="session-name">Prochain Événement</div>
                        <div class="session-wr neutral" style="font-size: 16px;">{{ news.next_event }}</div>
                        <div style="font-size: 11px; color: var(--text-secondary);">Attention Volatilité</div>
                    </div>
                    <div class="session-card">
                        <div class="session-name">Biais DXY (Risk Off)</div>
                        <div class="session-wr {{ 'positive' if 'Bullish' in dxy_bias else 'negative' if 'Bearish' in dxy_bias else 'neutral' }}">
                            {{ dxy_bias }}
                        </div>
                        <div style="font-size: 11px; color: var(--text-secondary);">VIX & Correlation Guard Active</div>
                    </div>
                </div>
            </div>
            
            <!-- Performance par session -->
            <div class="card" style="grid-column: span 2;">
                <div class="card-header">
                    <span class="card-title">🕒 Performance Stratégique par Session</span>
                </div>
                <div class="session-grid">
                    {% for session in sessions %}
                    <div class="session-card">
                        <span class="session-icon">
                            {% if 'ASIAN' in session.name %}🌏
                            {% elif 'OPEN' in session.name %}🔔
                            {% elif 'LONDON' in session.name %}🏟️
                            {% elif 'NY' in session.name %}🗽
                            {% else %}🌙{% endif %}
                        </span>
                        <div class="session-name">{{ session.name }}</div>
                        <div class="session-wr {{ 'positive' if session.win_rate > 55 else 'negative' if session.win_rate < 45 else 'neutral' }}">
                            {{ "%.0f"|format(session.win_rate) }}%
                        </div>
                        <div class="wr-bar-container">
                            <div class="wr-bar {{ 'wr-high' if session.win_rate > 55 else 'wr-mid' if session.win_rate >= 45 else 'wr-low' }}" 
                                 style="width: {{ session.win_rate }}%"></div>
                        </div>
                        <div class="session-trades">{{ session.trades }} trades institutionnels</div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        
        <div class="grid">
            <!-- Statistiques -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">📈 Statistiques</span>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                    <div>
                        <div class="stat-label">Win Rate</div>
                        <div class="stat-value {{ 'positive' if stats.win_rate > 50 else 'negative' }}">{{ "%.1f"|format(stats.win_rate) }}%</div>
                    </div>
                    <div>
                        <div class="stat-label">Profit Factor</div>
                        <div class="stat-value">{{ "%.2f"|format(stats.profit_factor) }}</div>
                    </div>
                    <div>
                        <div class="stat-label">Trades Aujourd'hui</div>
                        <div class="stat-value">{{ stats.trades_today }}</div>
                    </div>
                    <div>
                        <div class="stat-label">Best Trade</div>
                        <div class="stat-value positive">${{ "%.2f"|format(stats.best_trade) }}</div>
                    </div>
                </div>
            </div>
            
            <!-- Top Stratégies -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">🧠 Top Stratégies SMC</span>
                </div>
                <div class="session-grid" style="grid-template-columns: repeat(2, 1fr);">
                    {% for strat in strategies %}
                    <div class="session-card">
                        <div class="session-name">{{ strat.name }}</div>
                        <div class="session-wr {{ 'positive' if strat.win_rate > 50 else 'negative' }}">
                            {{ "%.0f"|format(strat.win_rate) }}%
                        </div>
                        <div style="font-size: 11px; color: var(--text-secondary);">
                            {{ strat.trades }} trades | ${{ "%.0f"|format(strat.profit) }}
                        </div>
                    </div>
                    {% endfor %}
                    {% if not strategies %}
                    <p style="color: var(--text-secondary); text-align: center; padding: 20px;">Pas de données stratégies</p>
                    {% endif %}
                </div>
            </div>

            <!-- Exposition -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">🛡️ Exposition par Devise</span>
                </div>
                {% if exposure %}
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;">
                    {% for currency, data in exposure.items() %}
                    <div class="session-card">
                        <div class="session-name">{{ currency }}</div>
                        <div class="session-wr {{ 'positive' if data.net_lots > 0 else 'negative' if data.net_lots < 0 else 'neutral' }}">
                            {{ "%.2f"|format(data.net_lots) }}
                        </div>
                        <div style="font-size: 11px; color: var(--text-secondary);">{{ data.type }}</div>
                    </div>
                    {% endfor %}
                </div>
                {% else %}
                <p style="color: var(--text-secondary); text-align: center; padding: 20px;">Aucune exposition</p>
                {% endif %}
            </div>
            
            <!-- Alertes récentes -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">🔔 Alertes Récentes</span>
                </div>
                <div class="alerts">
                    {% for alert in alerts %}
                    <div class="alert-item">
                        <span class="alert-time">{{ alert.time }}</span>
                        <span>{{ alert.message }}</span>
                    </div>
                    {% endfor %}
                    {% if not alerts %}
                    <p style="color: var(--text-secondary); text-align: center;">Aucune alerte</p>
                    {% endif %}
                </div>
            </div>
        </div>
        
        <footer style="text-align: center; padding: 20px; color: var(--text-secondary); font-size: 12px;">
            SMC Trading Bot v3.1 | Dernière mise à jour: {{ last_update }}
        </footer>
    </div>
    
    <script>
        // Auto-refresh toutes les 5 secondes
        setTimeout(function() {
            location.reload();
        }, 5000);
        
        function pauseBot() {
            if (confirm('Mettre le bot en pause ?')) {
                fetch('/api/pause', { method: 'POST' })
                    .then(r => r.json())
                    .then(d => alert(d.message));
            }
        }
        
        function killSwitch() {
            if (confirm('⚠️ ATTENTION: Cela va fermer toutes les positions et arrêter le bot. Continuer ?')) {
                fetch('/api/kill', { method: 'POST' })
                    .then(r => r.json())
                    .then(d => alert(d.message));
            }
        }
    </script>
</body>
</html>
"""


class DashboardServer:
    """
    Serveur web pour le dashboard de trading.
    
    Usage:
        dashboard = DashboardServer(port=5000)
        dashboard.start()  # Lance en arrière-plan
    """
    
    def __init__(self, port: int = 5000, host: str = '0.0.0.0'):
        if not FLASK_AVAILABLE:
            raise ImportError("Flask requis: pip install flask")
        
        self.port = port
        self.host = host
        self.app = Flask(__name__)
        self.running = False
        self.thread = None
        
        # État du bot (sera mis à jour par le bot principal)
        self.bot_status = "RUNNING"
        self.alerts: List[Dict] = []
        
        # Configurer les routes
        self._setup_routes()
        
        logger.info(f"📊 Dashboard initialisé sur http://{host}:{port}")
    
    def _setup_routes(self):
        """Configure les routes Flask."""
        
        @self.app.route('/')
        def index():
            return render_template_string(
                DASHBOARD_HTML,
                status=self.bot_status,
                account=self._get_account_info(),
                positions=self._get_positions(),
                stats=self._get_stats(),
                sessions=self._get_session_stats(),
                strategies=self._get_strategy_stats(),
                exposure=self._get_exposure(),
                dxy_bias=self._get_dxy_bias(),
                news=self._get_news_info(),
                trading_mode=self._get_trading_mode(),
                alerts=self.alerts[-10:],  # 10 dernières alertes
                last_update=datetime.now().strftime("%H:%M:%S")
            )
        
        @self.app.route('/api/status')
        def api_status():
            return jsonify({
                'status': self.bot_status,
                'account': self._get_account_info(),
                'positions': self._get_positions(),
                'stats': self._get_stats()
            })
        
        @self.app.route('/api/pause', methods=['POST'])
        def api_pause():
            self.bot_status = "PAUSED"
            self._add_alert("⏸️ Bot mis en pause via dashboard")
            return jsonify({'success': True, 'message': 'Bot mis en pause'})
        
        @self.app.route('/api/resume', methods=['POST'])
        def api_resume():
            self.bot_status = "RUNNING"
            self._add_alert("▶️ Bot repris via dashboard")
            return jsonify({'success': True, 'message': 'Bot repris'})
        
        @self.app.route('/api/kill', methods=['POST'])
        def api_kill():
            self.bot_status = "KILLED"
            self._add_alert("🛑 KILL SWITCH activé via dashboard")
            # TODO: Implémenter la fermeture des positions
            return jsonify({'success': True, 'message': 'Kill switch activé'})
    
    def _get_account_info(self) -> Dict:
        """Récupère les infos du compte MT5."""
        if not MT5_AVAILABLE or not mt5.terminal_info():
            return {'balance': 0, 'equity': 0, 'floating_pnl': 0}
        
        try:
            account = mt5.account_info()
            if account:
                return {
                    'balance': account.balance,
                    'equity': account.equity,
                    'floating_pnl': account.profit,
                    'margin': account.margin,
                    'free_margin': account.margin_free
                }
        except:
            pass
        
        return {'balance': 0, 'equity': 0, 'floating_pnl': 0}
    
    def _get_positions(self) -> List[Dict]:
        """Récupère les positions ouvertes."""
        if not MT5_AVAILABLE or not mt5.terminal_info():
            return []
        
        try:
            positions = mt5.positions_get()
            if positions is None:
                return []
            
            result = []
            for pos in positions:
                # Calculer la durée
                open_time = datetime.fromtimestamp(pos.time)
                duration = datetime.now() - open_time
                hours = int(duration.total_seconds() // 3600)
                minutes = int((duration.total_seconds() % 3600) // 60)
                
                # Prix actuel
                tick = mt5.symbol_info_tick(pos.symbol)
                current_price = tick.bid if pos.type == 0 else tick.ask if tick else pos.price_current
                
                # Setup extraction
                raw_comment = pos.comment if hasattr(pos, 'comment') else ""
                setup_name = raw_comment.replace("SMC Bot:", "").strip()[:20] # Shorten
                
                result.append({
                    'ticket': pos.ticket,
                    'symbol': pos.symbol,
                    'comment': setup_name if setup_name else "Manual/Unknown",
                    'direction': 'BUY' if pos.type == 0 else 'SELL',
                    'volume': pos.volume,
                    'entry_price': pos.price_open,
                    'current_price': current_price,
                    'profit': pos.profit,
                    'duration': f"{hours}h {minutes}m"
                })
            
            return result
        except:
            return []
    
    def _get_stats(self) -> Dict:
        """Récupère les statistiques dynamiquement depuis l'historique."""
        try:
            # On utilise le fichier de performance déjà mis à jour par SessionTracker
            perf_file = Path("logs/session_performance.json")
            if not perf_file.exists():
                return {
                    'win_rate': 0, 'profit_factor': 0, 'trades_today': 0,
                    'daily_pnl': 0, 'best_trade': 0, 'worst_trade': 0
                }
            
            with open(perf_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                trades = data.get('trades', [])
                
            if not trades:
                return {
                    'win_rate': 0, 'profit_factor': 0, 'trades_today': 0,
                    'daily_pnl': 0, 'best_trade': 0, 'worst_trade': 0
                }

            # Filtrer pour aujourd'hui
            today_str = datetime.now().strftime("%Y-%m-%d")
            trades_today = [t for t in trades if t.get('exit_time', '').startswith(today_str)]
            
            total_wins = len([t for t in trades if t.get('is_win')])
            total_trades = len(trades)
            
            profits = [t.get('profit', 0) for t in trades if t.get('profit', 0) > 0]
            losses = [abs(t.get('profit', 0)) for t in trades if t.get('profit', 0) < 0]
            
            win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
            
            sum_losses = sum(losses)
            if sum_losses > 0:
                profit_factor = sum(profits) / sum_losses
            else:
                profit_factor = float('inf') if sum(profits) > 0 else 0
            
            daily_pnl = sum([t.get('profit', 0) for t in trades_today])
            best_trade = max([t.get('profit', 0) for t in trades] + [0])
            worst_trade = min([t.get('profit', 0) for t in trades] + [0])
            
            return {
                'win_rate': round(win_rate, 1),
                'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else "∞",
                'trades_today': len(trades_today),
                'daily_pnl': round(daily_pnl, 2),
                'best_trade': round(best_trade, 2),
                'worst_trade': round(worst_trade, 2)
            }
        except Exception as e:
            logger.error(f"Erreur calcul stats dashboard: {e}")
            return {
                'win_rate': 0, 'profit_factor': 0, 'trades_today': 0,
                'daily_pnl': 0, 'best_trade': 0, 'worst_trade': 0
            }
    
    def _get_session_stats(self) -> List[Dict]:
        """Récupère les stats par session."""
        try:
            from utils.session_tracker import get_session_tracker
            tracker = get_session_tracker()
            summary = tracker.get_session_summary()
            
            result = []
            for name in ['asian', 'london_open', 'london', 'ny_open', 'ny', 'off_hours']:
                if name in summary:
                    s = summary[name]
                    result.append({
                        'name': name.upper().replace('_', ' '),
                        'win_rate': s.get('win_rate', 0),
                        'trades': s.get('trades', 0)
                    })
                else:
                    result.append({
                        'name': name.upper().replace('_', ' '),
                        'win_rate': 0,
                        'trades': 0
                    })
            return result
        except:
            return [{'name': s, 'win_rate': 0, 'trades': 0} 
                    for s in ['ASIAN', 'LONDON OPEN', 'LONDON', 'NY OPEN', 'NY', 'OFF HOURS']]

    def _get_strategy_stats(self) -> List[Dict]:
        """Récupère les stats par stratégie SMC."""
        try:
            from utils.session_tracker import get_session_tracker
            tracker = get_session_tracker()
            matrix = tracker.get_strategy_session_matrix()
            
            result = []
            for name, data in matrix.items():
                if name != 'unknown':
                    result.append({
                        'name': name.upper().replace('_', ' '),
                        'win_rate': data['total']['win_rate'],
                        'trades': data['total']['trades'],
                        'profit': data['total']['net_profit']
                    })
            # Trier par profit décroissant
            return sorted(result, key=lambda x: x['profit'], reverse=True)
        except:
            return []
    
    def _get_dxy_bias(self) -> str:
        """Récupère le biais du DXY en temps réel pour le dashboard."""
        if not MT5_AVAILABLE or not mt5.terminal_info():
            return "UNKNOWN"
        
        try:
            # Essayer les symboles DXY courants sur MT5
            for sym in ['DXYm', 'USDX', 'USDXm', 'DXY', 'USDXOFm']:
                rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 2)
                if rates is not None and len(rates) >= 2:
                    current = rates[1]['close']
                    prev = rates[0]['close']
                    if current > prev:
                        return "BULLISH 📈"
                    elif current < prev:
                        return "BEARISH 📉"
                    else:
                        return "NEUTRAL ↔️"
        except:
            pass
        return "NEUTRAL"

    def _get_exposure(self) -> Dict:
        """Récupère l'exposition par devise."""
        try:
            from utils.correlation_guard import get_correlation_guard
            guard = get_correlation_guard()
            return guard.get_exposure_summary()
        except:
            return {}
    
    def _get_news_info(self) -> Dict:
        """Récupère les infos du news filter depuis le cache."""
        try:
            cache_file = Path("data/news_cache.json")
            if not cache_file.exists():
                return {'source': 'OFFLINE', 'next_event': 'Aucune donnée', 'high_impact_count': 0}
                
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            events = data.get('events', [])
            now = datetime.now()
            
            # Prochain événement High
            upcoming = [e for e in events if datetime.fromisoformat(e['time']) > now]
            high_impact = [e for e in upcoming if e['impact'] == 'high']
            
            next_event = "Aucun"
            if high_impact:
                next_event_obj = high_impact[0]
                time_diff = datetime.fromisoformat(next_event_obj['time']) - now
                hours = int(time_diff.total_seconds() // 3600)
                mins = int((time_diff.total_seconds() % 3600) // 60)
                next_event = f"{next_event_obj['currency']} {next_event_obj['event'][:20]}.. ({hours}h{mins}m)"
            
            return {
                'source': data.get('source', 'Unknown').upper(),
                'next_event': next_event,
                'high_impact_count': len(high_impact)
            }
        except Exception as e:
            return {'source': 'ERROR', 'next_event': str(e), 'high_impact_count': 0}

    def _get_trading_mode(self) -> str:
        """Récupère le mode de trading actif depuis la config."""
        try:
            config_path = Path("config/settings.yaml")
            if config_path.exists():
                import yaml
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                
                # Détecter le mode actif
                mode = config.get('general', {}).get('mode', 'DEMO')
                return mode.upper()
        except:
            return "UNKNOWN"
        return "UNKNOWN"

    def _add_alert(self, message: str):
        """Ajoute une alerte."""
        self.alerts.append({
            'time': datetime.now().strftime("%H:%M:%S"),
            'message': message
        })
        # Garder seulement les 50 dernières
        if len(self.alerts) > 50:
            self.alerts = self.alerts[-50:]
    
    def add_alert(self, message: str):
        """Interface publique pour ajouter une alerte."""
        self._add_alert(message)
    
    def set_status(self, status: str):
        """Met à jour le statut du bot."""
        self.bot_status = status
    
    def start(self, threaded: bool = True):
        """
        Démarre le serveur dashboard.
        
        Args:
            threaded: Si True, lance en arrière-plan
        """
        if threaded:
            self.thread = threading.Thread(
                target=self._run_server,
                daemon=True
            )
            self.thread.start()
            logger.info(f"🌐 Dashboard démarré sur http://{self.host}:{self.port}")
        else:
            self._run_server()
    
    def _run_server(self):
        """Lance le serveur Flask."""
        self.running = True
        # Désactiver les logs Flask verbeux
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
    
    def stop(self):
        """Arrête le serveur."""
        self.running = False
        logger.info("📊 Dashboard arrêté")


# Singleton
_dashboard_instance: Optional[DashboardServer] = None

def get_dashboard(port: int = 5000) -> Optional[DashboardServer]:
    """Retourne l'instance singleton du dashboard."""
    global _dashboard_instance
    if not FLASK_AVAILABLE:
        return None
    if _dashboard_instance is None:
        _dashboard_instance = DashboardServer(port=port)
    return _dashboard_instance


def start_dashboard(port: int = 5000):
    """Démarre le dashboard en arrière-plan."""
    dashboard = get_dashboard(port)
    if dashboard:
        dashboard.start(threaded=True)
        return True
    return False


# Test standalone
if __name__ == "__main__":
    if FLASK_AVAILABLE:
        dashboard = DashboardServer(port=5000)
        dashboard.start(threaded=False)
    else:
        print("❌ Flask non installé. pip install flask")
