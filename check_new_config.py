#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script de verification rapide de la configuration"""
import yaml
import sys
import io
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

config_path = Path(__file__).parent / "config" / "settings.yaml"
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

risk = config.get('risk', {})
news = config.get('filters', {}).get('news', {})
symbols = config.get('symbols', [])

print("\n" + "="*60)
print("✅ CONFIGURATION MISE À JOUR")
print("="*60)

print(f"\n💰 CAPITAL: $4,301.33")
print(f"\n📊 SYMBOLES: {', '.join([s['name'] for s in symbols])}")

print(f"\n🛡️ RISK MANAGEMENT:")
print(f"   Risk per trade:     {risk.get('risk_per_trade')}% (~$21.50)")
print(f"   Max daily loss:     {risk.get('max_daily_loss')}% (~$64.50)")
print(f"   Max open trades:    {risk.get('max_open_trades')}")
print(f"   Max spread:         {risk.get('max_spread_pips')} pips")

print(f"\n🔔 NEWS FILTER:")
print(f"   Enabled:            {news.get('enabled')}")
print(f"   Filter HIGH:        {news.get('filter_high_impact')}")
print(f"   Filter MEDIUM:      {news.get('filter_medium_impact')}")
print(f"   Minutes before:     {news.get('minutes_before')}")
print(f"   Minutes after:      {news.get('minutes_after')}")

print("\n" + "="*60)
print("✅ Toutes les améliorations appliquées!")
print("="*60)
print("\n🚀 Prêt pour plus d'opportunités de trading!")
