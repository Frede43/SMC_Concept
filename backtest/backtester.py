import os
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd
import yaml
from loguru import logger
from broker.mt5_connector import MT5Connector
from strategy.smc_strategy import SMCStrategy, SignalType

class TradeResult:
    def __init__(self, success: bool, ticket: Optional[int] = None, message: str = ""):
        self.success = success
        self.ticket = ticket
        self.message = message

class BacktestTrade:
    def __init__(self, symbol: str, entry_price: float, stop_loss: float, take_profit: float, lot_size: float, direction: str, open_time: datetime, pip_value: float, risk_amount: float):
        self.symbol = symbol
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.lot_size = lot_size
        self.direction = direction
        self.open_time = open_time
        self.close_time = None
        self.close_price = None
        self.pip_value = pip_value
        self.risk_amount = risk_amount
        self.pnl = 0
        self.status = 'open'

    def close(self, close_price: float, close_time: datetime):
        self.close_price = close_price
        self.close_time = close_time
        if self.direction == 'BUY':
            self.pnl = (close_price - self.entry_price) * self.pip_value * self.lot_size
        else:
            self.pnl = (self.entry_price - close_price) * self.pip_value * self.lot_size
        self.status = 'closed'

class BacktestConfig:
    def __init__(self, symbols: List[str], start_date: datetime, end_date: datetime, initial_capital: float, data_dir: Path):
        self.symbols = symbols
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.data_dir = data_dir

class DataManager:
    def __init__(self, config: BacktestConfig):
        self.config = config
        self._data_cache = {}

    def get_historical_data(self, symbol: str, timeframe: str, start_date: datetime, end_date: datetime, use_mt5: bool = True) -> Optional[pd.DataFrame]:
        cache_key = f"{symbol}_{timeframe}_{start_date.date()}_{end_date.date()}"
        parquet_file = self.config.data_dir / f"{cache_key}.parquet"
        pkl_file = self.config.data_dir / f"{cache_key}.pkl"
        
        # 1. Tenter le chargement Parquet (Ultra rapide)
        if parquet_file.exists():
            try:
                # logger.info est désactivé par défaut en backtest, mais conservé pour le mode debug
                df = pd.read_parquet(parquet_file)
                self._data_cache[cache_key] = df
                return df
            except Exception as e:
                pass
        
        # 2. Tenter le chargement Pickle (Legacy)
        if pkl_file.exists():
            try:
                with open(pkl_file, 'rb') as f:
                    df = pickle.load(f)
                    self._data_cache[cache_key] = df
                    return df
            except Exception as e:
                pass

        if use_mt5:
            df = self._download_from_mt5(symbol, timeframe, start_date, end_date)
            if df is not None and len(df) > 0:
                # Sauvegarder en Parquet pour la prochaine fois (Optimisé)
                try:
                    df.to_parquet(parquet_file)
                except Exception as e:
                    with open(pkl_file, 'wb') as f:
                        pickle.dump(df, f)
                
                self._data_cache[cache_key] = df
                return df
        return None

    def _download_from_mt5(self, symbol: str, timeframe: str, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        try:
            import MetaTrader5 as mt5
            tf_map = {
                'M1': mt5.TIMEFRAME_M1,
                'M5': mt5.TIMEFRAME_M5,
                'M15': mt5.TIMEFRAME_M15,
                'M30': mt5.TIMEFRAME_M30,
                'H1': mt5.TIMEFRAME_H1,
                'H4': mt5.TIMEFRAME_H4,
                'D1': mt5.TIMEFRAME_D1,
                'W1': mt5.TIMEFRAME_W1,
            }
            tf = tf_map.get(timeframe.upper())
            if tf is None:
                logger.error(f"Invalid timeframe: {timeframe}")
                return None
            if not mt5.initialize():
                logger.error("Failed to initialize MT5")
                return None
            logger.info(f"Downloading {symbol} {timeframe} from {start_date.date()} to {end_date.date()}...")
            rates = mt5.copy_rates_range(symbol, tf, start_date, end_date)
            if rates is None or len(rates) == 0:
                logger.error(f"No data received for {symbol}")
                return None
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('time', inplace=True)
            df = df.rename(columns={'tick_volume': 'volume'})
            logger.info(f"Downloaded {len(df)} candles for {symbol} {timeframe}")
            return df[['open', 'high', 'low', 'close', 'volume']]
        except ImportError:
            logger.error("MetaTrader5 not installed. Install with: pip install MetaTrader5")
            return None
        except Exception as e:
            logger.error(f"Error downloading MT5: {e}")
            return None

    def generate_synthetic_data(self, symbol: str, timeframe: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        # Placeholder for synthetic data
        pass

class BacktestEngine:
    def __init__(self, config: BacktestConfig, strategy_config: Dict):
        self.config = config
        self.strategy_config = strategy_config
        self.data_manager = DataManager(config)
        self.strategy = None
        self.all_dates = []
        self.current_date = None
        self.current_capital = config.initial_capital
        self.open_trades = []
        self.closed_trades = []
        self.results = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0,
            'max_drawdown': 0,
            'sharpe_ratio': 0,
            'win_rate': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'largest_win': 0,
            'largest_loss': 0,
            'total_fees': 0,
            'net_pnl': 0
        }

    def _init_strategy(self):
        ROOT_DIR = Path(__file__).parent.parent
        config_path = ROOT_DIR / "config" / "settings.yaml"
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # ⚡ OPTIMISATION BACKTEST: Désactiver les filtres temps réel
        if 'fundamental' in config:
            config['fundamental']['enabled'] = False
        if 'filters' in config and 'news' in config['filters']:
            config['filters']['news']['enabled'] = False
            
        # Désactiver les logs verbeux pendant le backtest pour gagner de la vitesse
        import sys
        try:
            from loguru import logger
            logger.remove()
            logger.add(sys.stderr, level="ERROR")  # SEULS les erreurs critiques
        except:
            pass
        
        self.strategy = SMCStrategy(config)
        print("[BACKTEST] Mode Backtest: Logs desactives (seules les erreurs critiques s'affichent)")

    def run(self):
        self._init_strategy()
        data = {}
        ltf = self.strategy_config.get('timeframes', {}).get('ltf', 'M15')
        htf = self.strategy_config.get('timeframes', {}).get('htf', 'D1')
        for symbol in self.config.symbols:
            df_ltf = self.data_manager.get_historical_data(symbol, ltf, self.config.start_date, self.config.end_date)
            df_htf = self.data_manager.get_historical_data(symbol, htf, self.config.start_date, self.config.end_date)
            if df_ltf is None or len(df_ltf) == 0:
                logger.warning(f"Missing data for {symbol}, generating synthetic...")
                df_ltf = self.data_manager.generate_synthetic_data(symbol, ltf, self.config.start_date, self.config.end_date)
            if df_htf is None:
                df_htf = df_ltf.resample('D').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
            data[symbol] = {'ltf': df_ltf, 'htf': df_htf}
            logger.info(f"Data {symbol}: {len(df_ltf)} LTF candles, {len(df_htf)} HTF candles")
        all_dates = set()
        for symbol in self.config.symbols:
            if symbol in data and 'ltf' in data[symbol]:
                all_dates.update(data[symbol]['ltf'].index)
        if not all_dates:
            logger.error("No data available for any symbol")
            return {'error': 'No data available for any symbol'}
        all_dates = sorted(all_dates)
        progress_total = len(all_dates)
        # Pré-slicing des DataFrames pour un accès plus rapide dans les loops
        symbol_data_ltf = {s: data[s]['ltf'] for s in self.config.symbols}
        symbol_data_htf = {s: data[s]['htf'] for s in self.config.symbols}

        for i, current_date in enumerate(all_dates):
            self.current_date = current_date
            row = None
            
            # ⚡ OPTIMISATION: Limiter le lookback à 1000 bars (suffisant pour SMC)
            # Évite le coût O(N^2) de re-calculer sur TOUT l'historique à chaque pas
            LOOKBACK_LTF = 1000 
            LOOKBACK_HTF = 200

            for symbol in self.config.symbols:
                df_ltf = symbol_data_ltf[symbol]
                df_htf = symbol_data_htf[symbol]
                
                if current_date not in df_ltf.index:
                    continue
                
                # Slicing optimisé par position au lieu de index label
                # Trouver la position actuelle
                current_pos = df_ltf.index.get_loc(current_date)
                
                # Fenêtre glissante au lieu de croissance infinie
                start_pos = max(0, current_pos - LOOKBACK_LTF)
                df_ltf_past = df_ltf.iloc[start_pos : current_pos + 1]
                
                # HTF Slicing
                htf_norm_date = current_date.normalize()
                # On utilise searchsorted pour trouver la position HTF rapidement
                htf_pos = df_htf.index.searchsorted(htf_norm_date)
                start_htf_pos = max(0, htf_pos - LOOKBACK_HTF)
                df_htf_past = df_htf.iloc[start_htf_pos : htf_pos]
                
                if len(df_htf_past) < 10:
                    continue
                
                row = df_ltf_past.iloc[-1]
                
                # ✅ CORRECTION: Vérifier les clôtures pour CE symbole AVEC le prix de CE symbole
                self._check_trade_closes(symbol, row['close'], current_date)
                
                # On passe l'analyse
                analysis = self.strategy.analyze(df_ltf_past, df_htf_past, symbol=symbol)
                if analysis is None:
                    continue
                
                signal = self.strategy.generate_signal(df_ltf_past, df_htf_past, symbol, analysis=analysis, current_tick_price=None)
                if signal is None or signal.signal_type == SignalType.NO_SIGNAL:
                    continue
                
                # 🔧 CORRECTION CRITIQUE: Calculer la vraie taille de lot avec RiskManager
                from strategy.risk_management import RiskManager
                risk_manager = RiskManager(self.strategy.config)
                
                # Open trade with spread
                spread_price = self._get_spread_price(symbol)
                entry_price = signal.entry_price
                if signal.signal_type.value.upper() == 'BUY':
                    entry_price += spread_price
                else:
                    entry_price -= spread_price
                
                # Calculer la position size réelle
                pos_size = risk_manager.calculate_position_size(
                    account_balance=self.current_capital,
                    entry_price=entry_price,
                    stop_loss=signal.stop_loss,
                    symbol=symbol
                )
                
                # ✅ APPLIQUER le lot_multiplier comme un MULTIPLICATEUR (pas comme une taille absolue!)
                final_lot_size = pos_size.lot_size * signal.lot_multiplier
                
                # 🔍 DEBUG SIZING: AFFICHER POURQUOI C'EST PETIT
                if i % 5 == 0: # Echantillon
                    print(f"\n[DEBUG] {symbol} | Risk: ${pos_size.risk_amount:.2f} | SL: {pos_size.stop_loss_pips:.1f} pips")
                    print(f"      Base Lot: {pos_size.lot_size:.4f} | Signal Mult: {signal.lot_multiplier:.2f} | FINAL LOT: {final_lot_size:.4f}")
                
                logger.info(f"📊 Position calc: Base={pos_size.lot_size:.4f}, Multiplier={signal.lot_multiplier:.2f}, Final={final_lot_size:.4f}")
                
                trade = self._open_trade(symbol, entry_price, signal.stop_loss, signal.take_profit, final_lot_size, signal.signal_type.value.upper(), pos_size.risk_amount)
                if trade:
                    self.results['total_trades'] += 1
            
            # Check for closes loop deleted (moved inside per-symbol loop)
            # if row is not None:
            #     self._check_trade_closes(row['close'], current_date)
            
            # Log progress every 50 candles (optimisé pour visualisation)
            if i % 50 == 0:
                pct = i / progress_total * 100
                print(f"\rProgression: {pct:.1f}% ({i}/{progress_total} candles) - {current_date.strftime('%Y-%m-%d %H:%M')}", end="", flush=True)
        
        # 🧹 CLEANUP: Clôturer tous les trades restants à la fin du backtest
        print(f"\n\n🔄 Clôture de {len(self.open_trades)} trades restants...")
        for trade in list(self.open_trades):
            if trade.symbol in data:
                df_final = data[trade.symbol]['ltf']
                if not df_final.empty:
                    last_price = df_final.iloc[-1]['close']
                    last_time = df_final.index[-1]
                    
                    trade.close(last_price, last_time)
                    self.closed_trades.append(trade)
                    self.open_trades.remove(trade)
                    self.current_capital += trade.risk_amount + trade.pnl
        
        self._finalize_results()
        return self.results

    def _open_trade(self, symbol, entry_price, stop_loss, take_profit, lot_size, direction, explicit_risk_amount=None):
        pip_value = self._get_pip_value(symbol, entry_price)
        
        # 🔍 LOGGING CRITIQUE POUR DEBUG
        logger.warning(f"\n{'='*60}\n🚨 OUVERTURE TRADE - DETAILS COMPLETS\n{'='*60}")
        logger.warning(f"Symbole:      {symbol}")
        logger.warning(f"Direction:    {direction}")
        logger.warning(f"Entry Price:  {entry_price:.5f}")
        logger.warning(f"Stop Loss:    {stop_loss:.5f}")
        logger.warning(f"Take Profit:  {take_profit:.5f}")
        logger.warning(f"Lot Size:     {lot_size:.4f} lots")
        logger.warning(f"Pip Value:    {pip_value:.2f} (Backtester)")
        
        if direction == 'BUY':
            risk = entry_price - stop_loss
        else:
            risk = stop_loss - entry_price
        
        if explicit_risk_amount is not None:
            risk_amount = explicit_risk_amount
        else:
            risk_amount = risk * pip_value * lot_size
        
        logger.warning(f"Risk (price): {risk:.5f}")
        logger.warning(f"Risk Amount:  ${risk_amount:,.2f}")
        logger.warning(f"Capital:      ${self.current_capital:,.2f}")
        logger.warning(f"{'='*60}\n")
        
        if self.current_capital < risk_amount:
            logger.error(f"❌ Trade rejected: Insufficient capital (need ${risk_amount:,.2f}, have ${self.current_capital:,.2f})")
            return None
        
        trade = BacktestTrade(symbol, entry_price, stop_loss, take_profit, lot_size, direction, self.current_date, pip_value, risk_amount)
        self.open_trades.append(trade)
        self.current_capital -= risk_amount
        return trade

    def _check_trade_closes(self, symbol, current_price, current_time):
        """Check closes ONLY for the specific symbol"""
        # Filter trades for this symbol first
        symbol_trades = [t for t in self.open_trades if t.symbol == symbol]
        
        for trade in symbol_trades:
            if trade.direction == 'BUY':
                if current_price >= trade.take_profit or current_price <= trade.stop_loss:
                    trade.close(current_price, current_time)
                    self.closed_trades.append(trade)
                    self.open_trades.remove(trade)
                    # ✅ RESTITUER LA MARGE + PNL
                    self.current_capital += trade.risk_amount + trade.pnl
            else:
                if current_price <= trade.take_profit or current_price >= trade.stop_loss:
                    trade.close(current_price, current_time)
                    self.closed_trades.append(trade)
                    self.open_trades.remove(trade)
                    # ✅ RESTITUER LA MARGE + PNL
                    self.current_capital += trade.risk_amount + trade.pnl

    def _finalize_results(self):
        """Calculate all professional trading metrics"""
        import numpy as np
        
        # Base PnL
        # Base PnL
        self.results['total_pnl'] = sum(t.pnl for t in self.closed_trades)
        self.results['total_profit'] = self.results['total_pnl']
        self.results['trades'] = self.closed_trades  # ✅ AJOUT: Liste complète des objets trades
        
        # Trade counts
        self.results['winning_trades'] = len([t for t in self.closed_trades if t.pnl > 0])
        self.results['losing_trades'] = len([t for t in self.closed_trades if t.pnl < 0])
        self.results['breakeven_trades'] = len([t for t in self.closed_trades if t.pnl == 0])
        
        # Win Rate as PERCENTAGE (0-100), not ratio
        self.results['win_rate'] = (self.results['winning_trades'] / self.results['total_trades'] * 100) if self.results['total_trades'] > 0 else 0
        
        # Separate wins and losses
        wins = [t.pnl for t in self.closed_trades if t.pnl > 0]
        losses = [abs(t.pnl) for t in self.closed_trades if t.pnl < 0]
        all_pnls = [t.pnl for t in self.closed_trades]
        
        # Average metrics
        self.results['avg_win'] = sum(wins) / len(wins) if wins else 0
        self.results['avg_loss'] = sum(losses) / len(losses) if losses else 0
        self.results['largest_win'] = max(wins) if wins else 0
        self.results['largest_loss'] = max(losses) if losses else 0
        
        # Profit Factor = Gross Profit / Gross Loss
        gross_profit = sum(wins) if wins else 0
        gross_loss = sum(losses) if losses else 0
        self.results['profit_factor'] = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)
        
        # Capital metrics
        self.results['final_capital'] = self.current_capital
        self.results['roi'] = ((self.current_capital - self.config.initial_capital) / self.config.initial_capital) * 100
        
        # Max Drawdown calculation
        equity_curve = [self.config.initial_capital]
        running_capital = self.config.initial_capital
        peak = self.config.initial_capital
        max_dd = 0
        max_dd_pct = 0
        
        for trade in self.closed_trades:
            running_capital += trade.pnl
            equity_curve.append(running_capital)
            if running_capital > peak:
                peak = running_capital
            current_dd = peak - running_capital
            current_dd_pct = (current_dd / peak) * 100 if peak > 0 else 0
            if current_dd_pct > max_dd_pct:
                max_dd_pct = current_dd_pct
                max_dd = current_dd
        
        self.results['max_drawdown'] = max_dd_pct
        self.results['max_drawdown_dollars'] = max_dd
        
        # Sharpe Ratio (annualized, assuming ~250 trading days)
        if len(all_pnls) > 1:
            returns = np.array(all_pnls)
            mean_return = np.mean(returns)
            std_return = np.std(returns)
            # Annualize: sqrt(trades per year) * daily sharpe
            # Assume ~2 trades per day average = 500 trades/year
            trades_per_year = 500
            self.results['sharpe_ratio'] = (mean_return / std_return) * np.sqrt(trades_per_year) if std_return > 0 else 0
        else:
            self.results['sharpe_ratio'] = 0
        
        # Recovery Factor = Total Profit / Max Drawdown
        self.results['recovery_factor'] = abs(self.results['total_profit'] / max_dd) if max_dd > 0 else 0
        
        # Risk/Reward ratio
        self.results['risk_reward_avg'] = self.results['avg_win'] / self.results['avg_loss'] if self.results['avg_loss'] > 0 else 0

    def _get_pip_value(self, symbol, price):
        """Retourne le multiplicateur de contrat pour convertir la différence de prix en Dollars."""
        symbol_upper = symbol.upper()
        if 'BTC' in symbol_upper:
            return 1.0      # 1 lot BTC = 1 Coin ($1 move = $1 profit)
        elif 'ETH' in symbol_upper:
            return 1.0      # 1 lot ETH = 1 Coin
        elif 'XAU' in symbol_upper:
            return 100.0    # 1 lot Gold = 100 oz ($1 move = $100 profit)
        elif any(idx in symbol_upper for idx in ['US30', 'NAS100', 'SPX', 'GER30', 'DE30', 'DE40']):
            return 1.0      # Indices (Standard CFD): 1 lot = 1 Index ($1 move = $1 profit)
        elif 'JPY' in symbol_upper:
            return 1000.0   # Ajustement pour paires JPY (Standard 100k contract / 100)
        else:
            return 100000.0 # Forex Standard: 1 lot = 100,000 units

    def _get_spread_price(self, symbol):
        """Retourne le spread approximatif en unités de prix (ex: 0.00015 pour 1.5 pips)."""
        symbol_upper = symbol.upper()
        if 'BTC' in symbol_upper:
            # BTC spread ~1800 points = $18.00
            return 18.00
        elif 'ETH' in symbol_upper:
            return 2.00
        elif 'XAU' in symbol_upper:
            # XAU spread ~25 points = $0.25 (Exness)
            return 0.25
        elif 'JPY' in symbol_upper:
            return 0.02 # 2 pips
        else:
            return 0.00015 # 1.5 pips majors

def run_backtest(years: int, symbols: List[str], capital: float):
    ROOT_DIR = Path(__file__).parent.parent
    config_path = ROOT_DIR / "config" / "settings.yaml"
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365 * years)
    backtest_config = BacktestConfig(symbols, start_date, end_date, capital, ROOT_DIR / "backtest" / "data")
    engine = BacktestEngine(backtest_config, config.get('smc', {}))
    results = engine.run()
    print_summary(results)
    save_results(results, ROOT_DIR / "backtest" / "results")
    return results

def print_summary(results):
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"Total Trades: {results['total_trades']}")
    print(f"Winning Trades: {results['winning_trades']}")
    print(f"Losing Trades: {results['losing_trades']}")
    print(f"Win Rate: {results['win_rate']:.1f}%")
    print(f"Total PnL: ${results['total_pnl']:.2f}")
    print(f"Average Win: ${results['avg_win']:.2f}")
    print(f"Average Loss: ${results['avg_loss']:.2f}")
    print(f"Largest Win: ${results['largest_win']:.2f}")
    print(f"Largest Loss: ${results['largest_loss']:.2f}")

def save_results(results, results_dir):
    results_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = results_dir / f"backtest_results_{timestamp}.json"
    import json
    # Copier pour ne pas modifier l'original qui contient des objets
    results_to_save = results.copy()
    if 'trades' in results_to_save:
        # Convertir objets en dicts pour JSON
        results_to_save['trades'] = [
            {
                'symbol': t.symbol, 'entry': t.entry_price, 'exit': t.close_price, 
                'pnl': t.pnl, 'open_time': str(t.open_time), 'close_time': str(t.close_time),
                'direction': t.direction
            } 
            for t in results_to_save['trades']
        ]
        
    with open(results_file, 'w') as f:
        json.dump(results_to_save, f, indent=4, default=str)

def progress_callback(pct, msg):
    print(f"Progression: {pct:.1f}% - {msg}", end="", flush=True)
