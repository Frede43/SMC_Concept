"""
Fundamental Filter - Orchestrateur de l'analyse macro
Combine News, COT, Intermarket pour un score composite

Author: SMC Bot Team
Date: 2026-01-07
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from loguru import logger

from core.cot_analyzer import COTAnalyzer
from core.intermarket import IntermarketAnalyzer
from utils.news_fetcher import NewsFetcher


@dataclass
class FundamentalContext:
    """Contexte fondamental pour un symbole."""
    symbol: str
    timestamp: datetime
    
    # Scores individuels (-100 à +100)
    news_score: float = 0.0
    cot_score: float = 0.0
    intermarket_score: float = 0.0
    
    # Score composite
    composite_score: float = 0.0
    
    # Biais final
    macro_bias: str = "NEUTRAL"  # BULLISH, BEARISH, NEUTRAL
    
    # Alertes
    has_critical_news: bool = False
    news_in_next_hours: List[Dict] = field(default_factory=list)
    
    # Détails
    risk_sentiment: str = "NEUTRAL"  # RISK_ON, RISK_OFF, NEUTRAL
    dxy_bias: str = "NEUTRAL"
    
    # Métadonnées
    reasoning: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class FundamentalFilter:
    """
    Filtre fondamental pour validation des signaux SMC.
    
    Combine:
    - News économiques (calendrier)
    - COT Reports (positionnement institutionnel)
    - Intermarket (DXY, VIX, corrélations)
    
    Usage:
        >>> filter = FundamentalFilter(config)
        >>> context = filter.analyze("EURUSD", direction="BUY")
        >>> 
        >>> if context.has_critical_news:
        ...     print("⚠️ News imminente - Skip trade")
        >>> 
        >>> if context.composite_score < -50:
        ...     print("⚠️ Macro bearish fort - Contre signal BUY")
    
    Attributes:
        config (Dict): Configuration du bot
        enabled (bool): Si le filtre est activé
        news_fetcher (NewsFetcher): Module news
        cot_analyzer (COTAnalyzer): Module COT
        intermarket (IntermarketAnalyzer): Module intermarket
    """
    
    def __init__(self, config: Dict, discord_notifier=None, mt5_api=None):
        """
        Initialise le Fundamental Filter.
        
        Args:
            config: Configuration complète du bot
            discord_notifier: Notifieur Discord optionnel
            mt5_api: Client MT5 pour données temps réel
        """
        self.config = config
        self.discord = discord_notifier
        self.last_biases = {} # Tracking des changements de biais: symbol -> bias
        fund_config = config.get('fundamental', {})
        
        self.enabled = fund_config.get('enabled', False)
        
        if not self.enabled:
            logger.info("🌍 Fundamental Filter: DÉSACTIVÉ (config)")
            logger.info("   💡 Pour activer: fundamental.enabled = true dans settings.yaml")
            return
        
        # Initialiser les sous-modules
        try:
            self.news_fetcher = NewsFetcher(config)
            self.cot_analyzer = COTAnalyzer(config)
            self.intermarket = IntermarketAnalyzer(config, mt5_api=mt5_api)
        except Exception as e:
            logger.error(f"🌍 Erreur init sous-modules: {e}")
            self.enabled = False
            return
        
        # Poids des composants (paramétrable)
        weights = fund_config.get('weights', {})
        self.w_news = weights.get('news', 0.25)
        self.w_cot = weights.get('cot', 0.40)
        self.w_intermarket = weights.get('intermarket', 0.35)
        
        # Seuils de décision
        self.block_threshold = fund_config.get('block_threshold', -60)
        self.reduce_threshold = fund_config.get('reduce_threshold', -40)
        self.boost_threshold = fund_config.get('boost_threshold', 50)
        
        # Calcul des pourcentages pour le log
        p_news = self.w_news * 100
        p_cot = self.w_cot * 100
        p_inter = self.w_intermarket * 100
        
        logger.info(f"🌍 Fundamental Filter: ACTIVÉ")
        logger.info(f"   ⚖️ Configuration: News={p_news:.0f}%, COT={p_cot:.0f}%, Intermarket={p_inter:.0f}%")
        logger.info(f"   🚫 Seuils: Block<{self.block_threshold}, Reduce<{self.reduce_threshold}, Boost>{self.boost_threshold}")
    
    def analyze(self, symbol: str, direction: str = None) -> FundamentalContext:
        """
        Analyse fondamentale complète d'un symbole.
        
        Args:
            symbol: Symbole à analyser (ex: "EURUSD", "XAUUSDm")
            direction: Direction envisagée ("BUY" ou "SELL") pour ajuster scores
        
        Returns:
            FundamentalContext avec scores et recommandations
        
        Example:
            >>> context = filter.analyze("EURUSD", direction="BUY")
            >>> print(f"Score: {context.composite_score}")
            >>> print(f"Bias: {context.macro_bias}")
            >>> for reason in context.reasoning:
            ...     print(reason)
        """
        if not self.enabled:
            return FundamentalContext(
                symbol=symbol,
                timestamp=datetime.now(),
                macro_bias="NEUTRAL",
                composite_score=0.0
            )
        
        logger.debug(f"🌍 Analyse fondamentale: {symbol} ({direction})")
        
        context = FundamentalContext(symbol=symbol, timestamp=datetime.now())
        
        try:
            # 1. Vérifier news imminentes ou récentes
            all_news = self.news_fetcher.get_upcoming_news(symbol, hours=8)
            now = datetime.now()
            
            # Réglages de fenêtre
            news_cfg = self.config.get('fundamental', {}).get('news_filter', {})
            before = news_cfg.get('block_before_minutes', 30)
            after = news_cfg.get('block_after_minutes', 30)
            
            # On ne garde que les news dans une fenêtre pertinente (4h avant à 8h après)
            # pour l'analyse de score et les avertissements
            context.news_in_next_hours = [
                n for n in all_news 
                if -1 <= (n['time'] - now).total_seconds() / 3600 <= 8
            ]
            
            # On ne considère "critique" que les news HIGH imminentes (prochaines 4h)
            context.has_critical_news = any(
                n['impact'] == 'HIGH' and 0 <= (n['time'] - now).total_seconds() / 3600 <= 4
                for n in context.news_in_next_hours
            )
            
            # 2. Score News (court-terme)
            context.news_score = self._calculate_news_score(context.news_in_next_hours)
            
            # 3. Score COT (positionnement institutionnel)
            context.cot_score = self.cot_analyzer.get_score(symbol)
            
            # 4. Score Intermarket (corrélations)
            context.intermarket_score = self.intermarket.get_score(symbol)
            
            # 5. Infos complémentaires
            context.risk_sentiment = self.intermarket.get_risk_sentiment()
            context.dxy_bias = self.intermarket.get_dxy_bias()
            
            # 6. Calcul du score composite
            context.composite_score = (
                context.news_score * self.w_news +
                context.cot_score * self.w_cot +
                context.intermarket_score * self.w_intermarket
            )
            # Garder le score brut pour le tracking
            context.composite_score_raw = context.composite_score
            
            # 7. Déterminer le biais macro
            if context.composite_score > 30:
                context.macro_bias = "BULLISH"
            elif context.composite_score < -30:
                context.macro_bias = "BEARISH"
            else:
                context.macro_bias = "NEUTRAL"
            
            # 8. Ajuster selon la direction du trade (si fournie)
            if direction == "SELL":
                # Pour un SELL, inverser les scores
                context.composite_score = -context.composite_score
                # Inverser aussi le biais
                if context.macro_bias == "BULLISH":
                    context.macro_bias = "BEARISH"
                elif context.macro_bias == "BEARISH":
                    context.macro_bias = "BULLISH"
            
            # 9. Construire le raisonnement
            context.reasoning = self._build_reasoning(context, direction)
            context.warnings = self._build_warnings(context, direction)
            
            # 10. Notification de changement de biais (si global)
            # On vérifie le changement sur le biais AVANT ajustement de direction
            # pour éviter les notifications redondantes BUY/SELL
            raw_bias = "NEUTRAL"
            if context.composite_score_raw > 30: raw_bias = "BULLISH"
            elif context.composite_score_raw < -30: raw_bias = "BEARISH"
            
            if symbol in self.last_biases:
                old_bias = self.last_biases[symbol]
                if old_bias != raw_bias:
                    logger.info(f"🌍 Changement de biais détecté pour {symbol}: {old_bias} -> {raw_bias}")
                    if self.discord:
                        self.discord.notify_macro_bias_change(
                            symbol=symbol,
                            old_bias=old_bias,
                            new_bias=raw_bias,
                            score=context.composite_score_raw,
                            reasons=context.reasoning
                        )
            
            self.last_biases[symbol] = raw_bias
            
            logger.info(f"🌍 {symbol} | Macro: {context.macro_bias} | "
                       f"Score: {context.composite_score:.1f} | "
                       f"Direction: {direction}")
            
        except Exception as e:
            logger.error(f"🌍 Erreur analyse fondamentale {symbol}: {e}")
            context.composite_score = 0.0
            context.macro_bias = "NEUTRAL"
        
        return context
    
    def _calculate_news_score(self, upcoming_news: List[Dict]) -> float:
        """
        Score basé sur les news à venir.
        
        Logique:
        - News HIGH impact dans <1h → Score négatif fort (-50)
        - News MEDIUM impact dans <2h → Score négatif modéré (-20)
        - Pas de news → Score neutre (0)
        
        Args:
            upcoming_news: Liste des événements
        
        Returns:
            Score -100 à 0 (toujours négatif ou neutre car news = risque)
        """
        if not upcoming_news:
            return 0.0
        
        score = 0.0
        now = datetime.now()
        
        for news in upcoming_news:
            try:
                time_to_news = (news['time'] - now).total_seconds() / 3600  # heures
                
                # Ignorer les news passées au-delà de la fenêtre de sécurité (~30-60min)
                if time_to_news < -1.0: 
                    continue
                
                # News FUTURES
                if time_to_news >= 0:
                    if news['impact'] == 'HIGH':
                        if time_to_news < 0.5: score -= 80    # <30min
                        elif time_to_news < 1: score -= 50    # <1h
                        elif time_to_news < 2: score -= 20    # <2h
                    elif news['impact'] == 'MEDIUM':
                        if time_to_news < 1: score -= 30      # <1h
                        elif time_to_news < 2: score -= 10      # <2h
                
                # News RÉCENTES (Volatilité résiduelle)
                else:
                    impact_mult = 1.0 if news['impact'] == 'HIGH' else 0.5
                    if time_to_news > -0.5: # -30min
                        score -= 40 * impact_mult
                    elif time_to_news > -1.0: # -1h
                        score -= 10 * impact_mult
            except Exception as e:
                logger.debug(f"Erreur calcul news score: {e}")
                continue
        
        return max(score, -100)  # Limiter à -100
    
    def _build_reasoning(self, context: FundamentalContext, 
                        direction: str = None) -> List[str]:
        """Construit le raisonnement textuel."""
        reasons = []
        
        # News
        if context.has_critical_news:
            high_news = [n for n in context.news_in_next_hours if n['impact'] == 'HIGH']
            if high_news:
                event = high_news[0]
                time_to = (event['time'] - datetime.now()).total_seconds() / 60
                reasons.append(f"📰 News HIGH: {event['event']} dans {time_to:.0f}min")
        
        # COT
        if abs(context.cot_score) > 50:
            cot_direction = "Bullish" if context.cot_score > 0 else "Bearish"
            reasons.append(f"📊 COT {cot_direction} fort ({context.cot_score:.0f})")
        
        # Intermarket
        if abs(context.intermarket_score) > 40:
            inter_direction = "Bullish" if context.intermarket_score > 0 else "Bearish"
            reasons.append(f"🔗 Intermarket {inter_direction} ({context.intermarket_score:.0f})")
        
        # Risk Sentiment
        if context.risk_sentiment != "NEUTRAL":
            reasons.append(f"💹 Sentiment: {context.risk_sentiment}")
        
        # DXY
        if context.dxy_bias != "NEUTRAL":
            reasons.append(f"💵 DXY: {context.dxy_bias}")
        
        # Biais final
        if context.macro_bias != "NEUTRAL":
            reasons.append(f"🌍 Biais macro: {context.macro_bias}")
        
        return reasons
    
    def _build_warnings(self, context: FundamentalContext,
                       direction: str = None) -> List[str]:
        """Construit les avertissements."""
        warnings = []
        
        # News critique
        if context.has_critical_news:
            warnings.append("⚠️ News HIGH impact dans les 4h à venir")
        
        # Divergence avec direction
        if direction:
            is_buy = direction == "BUY"
            is_bullish_macro = context.macro_bias == "BULLISH"
            
            if is_buy and not is_bullish_macro and context.macro_bias != "NEUTRAL":
                warnings.append(f"⚠️ Divergence: Signal {direction} vs Macro {context.macro_bias}")
        
        # Score extrême négatif
        if context.composite_score < -60:
            warnings.append("⚠️ Score fondamental très négatif")
        
        return warnings
    
    def should_block_trade(self, context: FundamentalContext, 
                          smc_direction: str) -> tuple[bool, str]:
        """
        Détermine si le trade doit être bloqué.
        
        Règles:
        1. News économiques imminentes ou récentes (fenêtre configurable)
        2. Divergence macro-économique forte (> block_threshold)
        """
        # Règle 1: News critique imminente ou récente
        fund_config = self.config.get('fundamental', {})
        news_cfg = fund_config.get('news_filter', {})
        
        if news_cfg.get('enabled', True):
            before = news_cfg.get('block_before_minutes', 30)
            after = news_cfg.get('block_after_minutes', 30)
            high_only = news_cfg.get('high_impact_only', False)

            now = datetime.now()
            for news in context.news_in_next_hours:
                # Filtrer par impact si configuré
                if high_only and news['impact'] != 'HIGH':
                    continue
                
                # Uniquement news HIGH ou MEDIUM par défaut si high_only=False
                if news['impact'] not in ['HIGH', 'MEDIUM']:
                    continue

                time_to = (news['time'] - now).total_seconds() / 60
                
                # Bloquer si on est dans la fenêtre [ -after, +before ]
                if -after <= time_to <= before:
                    if time_to > 0:
                        return True, f"❌ News {news['event']} dans {time_to:.0f}min"
                    else:
                        return True, f"❌ News {news['event']} passée il y a {abs(time_to):.0f}min"
        
        # Règle 2: Divergence macro très forte
        smc_bullish = smc_direction == "BUY"
        macro_bullish = context.macro_bias == "BULLISH"
        
        divergence = smc_bullish != macro_bullish
        strong_macro = abs(context.composite_score) > abs(self.block_threshold)
        
        if divergence and strong_macro and context.macro_bias != "NEUTRAL":
            return True, (f"❌ Divergence forte: SMC={smc_direction} vs "
                         f"Macro={context.macro_bias} ({context.composite_score:.0f})")
        
        return False, ""
    
    def get_position_size_multiplier(self, context: FundamentalContext,
                                     smc_direction: str) -> float:
        """
        Retourne un multiplicateur de position (0.5 à 1.5).
        
        Logique:
        - SMC + Macro alignés et forte conviction → 1.0-1.5x (boost)
        - SMC vs Macro divergence modérée → 0.5-0.8x (réduction)
        - Neutre → 1.0x
        
        Args:
            context: Contexte fondamental
            smc_direction: Direction SMC
        
        Returns:
            Multiplicateur de 0.5 à 1.5
        
        Example:
            >>> multiplier = filter.get_position_size_multiplier(context, "BUY")
            >>> adjusted_lots = base_lots * multiplier
        """
        smc_bullish = smc_direction == "BUY"
        macro_bullish = context.macro_bias == "BULLISH"
        
        # Confluence parfaite
        if smc_bullish == macro_bullish and abs(context.composite_score) > self.boost_threshold:
            # Boost proportionnel au score
            boost_factor = min(abs(context.composite_score) / 100, 0.5)
            return min(1.0 + boost_factor, 1.5)
        
        # Divergence
        if smc_bullish != macro_bullish and abs(context.composite_score) > abs(self.reduce_threshold):
            # Réduction proportionnelle
            reduce_factor = min(abs(context.composite_score) / 100, 0.5)
            return max(1.0 - reduce_factor, 0.5)
        
        # Neutre ou faible conviction
        return 1.0
    
    def get_summary(self, symbol: str, direction: str = None) -> str:
        """
        Retourne un résumé textuel de l'analyse.
        
        Args:
            symbol: Symbole
            direction: Direction optionnelle
        
        Returns:
            Texte formaté
        """
        context = self.analyze(symbol, direction)
        
        summary = f"\n🌍 ANALYSE FONDAMENTALE - {symbol}"
        summary += f"\n{'='*50}\n"
        
        summary += f"\n📊 SCORES:"
        summary += f"\n  • News:        {context.news_score:>6.1f}"
        summary += f"\n  • COT:         {context.cot_score:>6.1f}"
        summary += f"\n  • Intermarket: {context.intermarket_score:>6.1f}"
        summary += f"\n  • COMPOSITE:   {context.composite_score:>6.1f}"
        
        summary += f"\n\n🎯 BIAIS MACRO: {context.macro_bias}"
        summary += f"\n💹 Risk Sentiment: {context.risk_sentiment}"
        summary += f"\n💵 DXY Bias: {context.dxy_bias}"
        
        if context.reasoning:
            summary += f"\n\n📝 RAISONNEMENT:"
            for reason in context.reasoning:
                summary += f"\n  • {reason}"
        
        if context.warnings:
            summary += f"\n\n⚠️ AVERTISSEMENTS:"
            for warning in context.warnings:
                summary += f"\n  • {warning}"
        
        if direction:
            should_block, block_reason = self.should_block_trade(context, direction)
            multiplier = self.get_position_size_multiplier(context, direction)
            
            summary += f"\n\n💼 DÉCISION (pour {direction}):"
            if should_block:
                summary += f"\n  ❌ BLOQUER: {block_reason}"
            else:
                summary += f"\n  ✅ AUTORISER"
                summary += f"\n  📏 Position multiplier: {multiplier:.2f}x"
        
        summary += f"\n{'='*50}\n"
        
        return summary
