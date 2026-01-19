"""
Chart Visualizer
Visualisation des analyses SMC sur graphique
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, List, Any, Optional
from pathlib import Path


class ChartVisualizer:
    """
    Visualisation des analyses SMC avec Plotly.
    
    Affiche:
    - Chandeliers OHLC
    - Order Blocks
    - Fair Value Gaps
    - Market Structure (BOS/CHoCH)
    - Premium/Discount zones
    - Liquidity levels
    """
    
    def __init__(self, theme: str = "dark"):
        self.theme = theme
        self.colors = {
            'bullish_ob': 'rgba(0, 255, 0, 0.3)',
            'bearish_ob': 'rgba(255, 0, 0, 0.3)',
            'bullish_fvg': 'rgba(144, 238, 144, 0.4)',
            'bearish_fvg': 'rgba(255, 182, 193, 0.4)',
            'premium': 'rgba(255, 215, 0, 0.2)',
            'discount': 'rgba(0, 206, 209, 0.2)',
            'bos_bullish': '#00FF00',
            'bos_bearish': '#FF0000',
            'choch': '#FF00FF',
            'liquidity': '#FFD700',
            'swing_high': '#00CED1',
            'swing_low': '#FF6347'
        }
        
    def create_chart(self, df: pd.DataFrame, analysis: Dict[str, Any],
                    symbol: str = "", title: str = None) -> go.Figure:
        """
        Crée un graphique complet avec les analyses SMC.
        """
        # Créer la figure
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.85, 0.15],
            subplot_titles=("", "Volume")
        )
        
        # Ajouter les chandeliers
        fig.add_trace(
            go.Candlestick(
                x=df.index,
                open=df['open'],
                high=df['high'],
                low=df['low'],
                close=df['close'],
                name='OHLC',
                increasing_line_color='#00FF00',
                decreasing_line_color='#FF0000'
            ),
            row=1, col=1
        )
        
        # Ajouter le volume
        if 'volume' in df.columns:
            colors = ['green' if c >= o else 'red' 
                     for c, o in zip(df['close'], df['open'])]
            fig.add_trace(
                go.Bar(x=df.index, y=df['volume'], name='Volume',
                      marker_color=colors, opacity=0.5),
                row=2, col=1
            )
        
        # Ajouter les Order Blocks
        self._add_order_blocks(fig, df, analysis.get('order_blocks', []))
        
        # Ajouter les FVG
        self._add_fvgs(fig, df, analysis.get('fvgs', []))
        
        # Ajouter Premium/Discount
        pd_zone = analysis.get('pd_zone')
        if pd_zone:
            self._add_premium_discount(fig, df, pd_zone)
        
        # Ajouter la structure de marché
        structure = analysis.get('structure', {})
        self._add_structure(fig, df, structure)
        
        # Ajouter la liquidité
        self._add_liquidity(fig, df, analysis.get('liquidity_zones', []))
        
        # Configuration du layout
        chart_title = title or f"{symbol} - SMC Analysis"
        fig.update_layout(
            title=chart_title,
            template='plotly_dark' if self.theme == 'dark' else 'plotly_white',
            xaxis_rangeslider_visible=False,
            height=800,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        
        return fig
    
    def _add_order_blocks(self, fig: go.Figure, df: pd.DataFrame, 
                         order_blocks: List) -> None:
        """Ajoute les Order Blocks au graphique (style Ultimate SMC)."""
        for ob in order_blocks:
            if not hasattr(ob, 'type'):
                continue
                
            ob_type = ob.type.value if hasattr(ob.type, 'value') else ob.type
            color = self.colors['bullish_ob'] if ob_type == 'bullish' else self.colors['bearish_ob']
            border_color = '#00FF00' if ob_type == 'bullish' else '#FF0000'
            
            # Rectangle pour l'OB
            x0 = df.index[ob.index] if ob.index < len(df) else df.index[-1]
            x1 = df.index[-1]
            
            fig.add_shape(
                type="rect",
                x0=x0, x1=x1,
                y0=ob.low, y1=ob.high,
                fillcolor=color,
                line=dict(color=border_color, width=1),
                row=1, col=1
            )
            
            # Label OB type
            fig.add_annotation(
                x=x0, y=ob.high,
                text=f"OB {ob_type.upper()}",
                showarrow=False,
                font=dict(size=10, color='white'),
                row=1, col=1
            )
            
            # Annotation Block High (comme dans Ultimate SMC)
            fig.add_annotation(
                x=x1, y=ob.high,
                text="Block High",
                showarrow=False,
                font=dict(size=8, color=border_color),
                xanchor="right",
                row=1, col=1
            )
            
            # Annotation Block Low (comme dans Ultimate SMC)
            fig.add_annotation(
                x=x1, y=ob.low,
                text="Block Low",
                showarrow=False,
                font=dict(size=8, color=border_color),
                xanchor="right",
                row=1, col=1
            )
    
    def _add_fvgs(self, fig: go.Figure, df: pd.DataFrame, fvgs: List) -> None:
        """Ajoute les Fair Value Gaps au graphique."""
        for fvg in fvgs:
            if not hasattr(fvg, 'type'):
                continue
                
            fvg_type = fvg.type.value if hasattr(fvg.type, 'value') else fvg.type
            color = self.colors['bullish_fvg'] if fvg_type == 'bullish' else self.colors['bearish_fvg']
            
            x0 = df.index[fvg.index] if fvg.index < len(df) else df.index[-1]
            x1 = df.index[-1]
            
            fig.add_shape(
                type="rect",
                x0=x0, x1=x1,
                y0=fvg.low, y1=fvg.high,
                fillcolor=color,
                line=dict(color="rgba(0,0,0,0)", width=0),
                row=1, col=1
            )
    
    def _add_premium_discount(self, fig: go.Figure, df: pd.DataFrame, 
                             pd_zone) -> None:
        """Ajoute les zones Premium/Discount."""
        x0 = df.index[0]
        x1 = df.index[-1]
        
        # Zone Premium
        fig.add_shape(
            type="rect",
            x0=x0, x1=x1,
            y0=pd_zone.equilibrium, y1=pd_zone.range_high,
            fillcolor=self.colors['premium'],
            line=dict(color="rgba(0,0,0,0)", width=0),
            row=1, col=1
        )
        
        # Zone Discount
        fig.add_shape(
            type="rect",
            x0=x0, x1=x1,
            y0=pd_zone.range_low, y1=pd_zone.equilibrium,
            fillcolor=self.colors['discount'],
            line=dict(color="rgba(0,0,0,0)", width=0),
            row=1, col=1
        )
        
        # Ligne d'équilibre
        fig.add_hline(
            y=pd_zone.equilibrium,
            line_dash="dash",
            line_color="white",
            annotation_text="EQ (50%)",
            row=1, col=1
        )
    
    def _add_structure(self, fig: go.Figure, df: pd.DataFrame, 
                      structure: Dict) -> None:
        """Ajoute la structure de marché (BOS, CHoCH)."""
        # Swing Highs
        for sh in structure.get('swing_highs', []):
            idx = sh.index if hasattr(sh, 'index') else sh.get('index', 0)
            price = sh.price if hasattr(sh, 'price') else sh.get('price', 0)
            
            if idx < len(df):
                fig.add_trace(go.Scatter(
                    x=[df.index[idx]],
                    y=[price],
                    mode='markers',
                    marker=dict(symbol='triangle-down', size=12, 
                               color=self.colors['swing_high']),
                    name='Swing High',
                    showlegend=False
                ), row=1, col=1)
        
        # Swing Lows
        for sl in structure.get('swing_lows', []):
            idx = sl.index if hasattr(sl, 'index') else sl.get('index', 0)
            price = sl.price if hasattr(sl, 'price') else sl.get('price', 0)
            
            if idx < len(df):
                fig.add_trace(go.Scatter(
                    x=[df.index[idx]],
                    y=[price],
                    mode='markers',
                    marker=dict(symbol='triangle-up', size=12,
                               color=self.colors['swing_low']),
                    name='Swing Low',
                    showlegend=False
                ), row=1, col=1)
        
        # Structure Breaks
        for sb in structure.get('structure_breaks', []):
            if not hasattr(sb, 'type'):
                continue
                
            sb_type = sb.type.value if hasattr(sb.type, 'value') else sb.type
            direction = sb.direction.value if hasattr(sb.direction, 'value') else sb.direction
            
            if sb.break_index >= len(df):
                continue
            
            if sb_type == 'bos':
                color = self.colors['bos_bullish'] if direction == 'bullish' else self.colors['bos_bearish']
                text = "BOS ▲" if direction == 'bullish' else "BOS ▼"
            else:
                color = self.colors['choch']
                text = "CHoCH"
            
            fig.add_annotation(
                x=df.index[sb.break_index],
                y=sb.break_price,
                text=text,
                showarrow=True,
                arrowhead=2,
                arrowcolor=color,
                font=dict(color=color, size=10),
                row=1, col=1
            )
    
    def _add_liquidity(self, fig: go.Figure, df: pd.DataFrame, 
                      liquidity_zones: List) -> None:
        """Ajoute les niveaux de liquidité comme dans Ultimate SMC."""
        for lz in liquidity_zones:
            if not hasattr(lz, 'level'):
                continue
            
            if not lz.is_valid():
                continue
            
            lz_type = lz.type.value if hasattr(lz.type, 'value') else lz.type
            
            # Couleur selon le type
            if lz_type == "buy_side":
                color = "rgba(255, 0, 0, 0.3)"  # Rouge pour buy-side (stop des shorts)
                text = "BSL (Buy Side Liq)"
            else:
                color = "rgba(0, 255, 0, 0.3)"  # Vert pour sell-side (stop des longs)
                text = "SSL (Sell Side Liq)"
            
            # Ligne de liquidité
            fig.add_hline(
                y=lz.level,
                line_dash="dot",
                line_color=self.colors['liquidity'],
                annotation_text=text,
                row=1, col=1
            )
            
            # Si c'est un equal high/low, ajouter annotation
            if hasattr(lz, 'is_equal_level') and lz.is_equal_level:
                idx = lz.index if lz.index < len(df) else len(df) - 1
                fig.add_annotation(
                    x=df.index[idx],
                    y=lz.level,
                    text="Range for Liquidity",
                    showarrow=True,
                    arrowhead=2,
                    font=dict(size=9, color="#FFD700"),
                    row=1, col=1
                )
    
    def save_chart(self, fig: go.Figure, filename: str, 
                  output_dir: str = "charts") -> str:
        """Sauvegarde le graphique en HTML."""
        path = Path(output_dir)
        path.mkdir(exist_ok=True)
        
        filepath = path / f"{filename}.html"
        fig.write_html(str(filepath))
        
        return str(filepath)
    
    def show_chart(self, fig: go.Figure) -> None:
        """Affiche le graphique dans le navigateur."""
        fig.show()
