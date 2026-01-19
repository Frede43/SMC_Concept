"""
Tests Unitaires pour le Fundamental Filter
Author: SMC Bot Team
Date: 2026-01-07
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.fundamental_filter import FundamentalFilter, FundamentalContext


class TestFundamentalFilter:
    """Tests pour le FundamentalFilter."""
    
    @pytest.fixture
    def config(self):
        """Configuration de test."""
        return {
            'fundamental': {
                'enabled': True,
                'weights': {
                    'news': 0.25,
                    'cot': 0.40,
                    'intermarket': 0.35
                },
                'block_threshold': -60,
                'reduce_threshold': -40,
                'boost_threshold': 50,
                'news_filter': {
                    'enabled': True,
                    'block_before_minutes': 30,
                    'block_after_minutes': 30,
                    'high_impact_only': False
                },
                'cot_analysis': {
                    'enabled': False,  # Désactivé pour tests
                    'extreme_threshold': 2.0
                },
                'intermarket': {
                    'enabled': True,
                    'risk_off_vix_threshold': 20
                }
            }
        }
    
    @pytest.fixture
    def mock_filter(self, config):
        """FundamentalFilter mocké pour éviter dépendances externes."""
        with patch('core.fundamental_filter.NewsFetcher'), \
             patch('core.fundamental_filter.COTAnalyzer'), \
             patch('core.fundamental_filter.IntermarketAnalyzer'):
            filter = FundamentalFilter(config)
            
            # Mock des sous-modules
            filter.news_fetcher = MagicMock()
            filter.cot_analyzer = MagicMock()
            filter.intermarket = MagicMock()
            
            return filter
    
    def test_initialization_enabled(self, config):
        """Test que le filtre s'initialise correctement quand enabled."""
        with patch('core.fundamental_filter.NewsFetcher'), \
             patch('core.fundamental_filter.COTAnalyzer'), \
             patch('core.fundamental_filter.IntermarketAnalyzer'):
            filter = FundamentalFilter(config)
            assert filter.enabled == True
            assert filter.w_news == 0.25
            assert filter.w_cot == 0.40
            assert filter.w_intermarket == 0.35
    
    def test_initialization_disabled(self):
        """Test que le filtre se désactive si config disabled."""
        config = {'fundamental': {'enabled': False}}
        filter = FundamentalFilter(config)
        assert filter.enabled == False
    
    def test_calculate_news_score_no_news(self, mock_filter):
        """Test score news quand aucune news."""
        score = mock_filter._calculate_news_score([])
        assert score == 0.0
    
    def test_calculate_news_score_high_impact_imminent(self, mock_filter):
        """Test score news pour HIGH impact imminent."""
        now = datetime.now()
        upcoming_news = [
            {
                'time': now + timedelta(minutes=20),  # Dans 20min
                'impact': 'HIGH',
                'event': 'NFP'
            }
        ]
        score = mock_filter._calculate_news_score(upcoming_news)
        assert score < -50  # Doit être fortement négatif
    
    def test_calculate_news_score_medium_impact(self, mock_filter):
        """Test score news pour MEDIUM impact."""
        now = datetime.now()
        upcoming_news = [
            {
                'time': now + timedelta(minutes=45),
                'impact': 'MEDIUM',
                'event': 'Retail Sales'
            }
        ]
        score = mock_filter._calculate_news_score(upcoming_news)
        assert score < 0  # Négatif mais moins fort
        assert score > -50
    
    def test_should_block_trade_critical_news(self, mock_filter):
        """Test blocage pour news critique imminente."""
        context = FundamentalContext(
            symbol="EURUSD",
            timestamp=datetime.now(),
            has_critical_news=True,
            news_in_next_hours=[{
                'time': datetime.now() + timedelta(minutes=15),
                'event': 'FOMC Decision',
                'impact': 'HIGH'
            }],
            composite_score=50  # Score positif mais news bloque
        )
        
        should_block, reason = mock_filter.should_block_trade(context, "BUY")
        assert should_block == True
        assert "FOMC" in reason or "15" in reason
    
    def test_should_block_trade_strong_divergence(self, mock_filter):
        """Test blocage pour divergence macro forte."""
        context = FundamentalContext(
            symbol="EURUSD",
            timestamp=datetime.now(),
            has_critical_news=False,
            composite_score=-70,  # Très bearish
            macro_bias="BEARISH"
        )
        
        should_block, reason = mock_filter.should_block_trade(context, "BUY")
        assert should_block == True
        assert "divergence" in reason.lower() or "macro" in reason.lower()
    
    def test_should_not_block_trade_aligned(self, mock_filter):
        """Test pas de blocage si aligné."""
        context = FundamentalContext(
            symbol="EURUSD",
            timestamp=datetime.now(),
            has_critical_news=False,
            composite_score=60,  # Bullish
            macro_bias="BULLISH"
        )
        
        should_block, reason = mock_filter.should_block_trade(context, "BUY")
        assert should_block == False
    
    def test_position_size_multiplier_boost(self, mock_filter):
        """Test boost de position si confluence."""
        context = FundamentalContext(
            symbol="EURUSD",
            timestamp=datetime.now(),
            composite_score=70,  # Fort bullish
            macro_bias="BULLISH"
        )
        
        multiplier = mock_filter.get_position_size_multiplier(context, "BUY")
        assert multiplier > 1.0  # Boost
        assert multiplier <= 1.5  # Limité à 1.5
    
    def test_position_size_multiplier_reduce(self, mock_filter):
        """Test réduction de position si divergence."""
        context = FundamentalContext(
            symbol="EURUSD",
            timestamp=datetime.now(),
            composite_score=-50,  # Bearish modéré
            macro_bias="BEARISH"
        )
        
        multiplier = mock_filter.get_position_size_multiplier(context, "BUY")
        assert multiplier < 1.0  # Réduction
        assert multiplier >= 0.5  # Limité à 0.5
    
    def test_position_size_multiplier_neutral(self, mock_filter):
        """Test multiplicateur neutre si pas convaincu."""
        context = FundamentalContext(
            symbol="EURUSD",
            timestamp=datetime.now(),
            composite_score=15,  # Faible
            macro_bias="NEUTRAL"
        )
        
        multiplier = mock_filter.get_position_size_multiplier(context, "BUY")
        assert multiplier == 1.0  # Neutre
    
    def test_analyze_builds_reasoning(self, mock_filter):
        """Test que analyze() construit le raisonnement."""
        # Setup mocks
        mock_filter.news_fetcher.get_upcoming_news.return_value = []
        mock_filter.cot_analyzer.get_score.return_value = 60
        mock_filter.intermarket.get_score.return_value = 40
        mock_filter.intermarket.get_risk_sentiment.return_value = "RISK_ON"
        mock_filter.intermarket.get_dxy_bias.return_value = "BEARISH"
        
        context = mock_filter.analyze("EURUSD", direction="BUY")
        
        assert context is not None
        assert context.symbol == "EURUSD"
        assert context.cot_score == 60
        assert context.intermarket_score == 40
        assert len(context.reasoning) > 0  # Doit avoir du raisonnement
    
    def test_analyze_with_sell_direction(self, mock_filter):
        """Test que analyze() inverse les scores pour SELL."""
        # Setup mocks
        mock_filter.news_fetcher.get_upcoming_news.return_value = []
        mock_filter.cot_analyzer.get_score.return_value = 50
        mock_filter.intermarket.get_score.return_value = 30
        mock_filter.intermarket.get_risk_sentiment.return_value = "NEUTRAL"
        mock_filter.intermarket.get_dxy_bias.return_value = "NEUTRAL"
        
        context_buy = mock_filter.analyze("EURUSD", direction="BUY")
        context_sell = mock_filter.analyze("EURUSD", direction="SELL")
        
        # Les scores doivent être inversés
        assert context_buy.composite_score == pytest.approx(-context_sell.composite_score, abs=0.1)


class TestFundamentalContext:
    """Tests pour FundamentalContext dataclass."""
    
    def test_creation_with_defaults(self):
        """Test création avec valeurs par défaut."""
        context = FundamentalContext(
            symbol="EURUSD",
            timestamp=datetime.now()
        )
        
        assert context.symbol == "EURUSD"
        assert context.composite_score == 0.0
        assert context.macro_bias == "NEUTRAL"
        assert context.has_critical_news == False
        assert len(context.news_in_next_hours) == 0
        assert len(context.reasoning) == 0
    
    def test_creation_with_values(self):
        """Test création avec valeurs spécifiques."""
        context = FundamentalContext(
            symbol="XAUUSD",
            timestamp=datetime.now(),
            composite_score=75.5,
            macro_bias="BULLISH",
            has_critical_news=True
        )
        
        assert context.composite_score == 75.5
        assert context.macro_bias == "BULLISH"
        assert context.has_critical_news == True


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
