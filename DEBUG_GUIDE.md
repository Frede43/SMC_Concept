# 🔧 GUIDE DE DÉBOGAGE - SMC Ultra Pro
## Pourquoi 0 trades ?

Ce guide vous aide à diagnostiquer pourquoi le script ne génère aucun trade.

---

## ✅ CHECKLIST DE DÉBOGAGE

### 1. **Vérifier le Killzone Filter** ⏰
**Problème le plus fréquent : 90% des cas**

Le script trade **UNIQUEMENT** pendant les sessions ICT :
- **London KZ** : 02:00-05:00 NY Time (08:00-11:00 Paris)
- **NY AM KZ** : 08:30-11:00 NY Time (14:30-17:00 Paris)  
- **NY PM KZ** : 13:30-16:00 NY Time (19:30-22:00 Paris)
- **Asian KZ** : 00:00-06:00 NY Time (JPY/Crypto seulement)

**Solution** :
1. Vérifier l'heure actuelle sur votre graphique
2. Si HORS Killzone → Désactiver temporairement :
   - Settings → ICT Killzones → **Décocher "Require Killzone for Entries"**
3. Relancer le backtest

---

### 2. **Vérifier le BOS Strength** 📊

**Dashboard → BOS Strength**
- ✅ **> 0.4 ATR** : OK, marché en tendance
- ❌ **< 0.4 ATR** : Marché en range, pas de trades

**Solution** :
- Attendre un BOS/CHoCH valide
- OU réduire le seuil : Settings → BOS Strength Threshold → **0.3 ATR**

---

### 3. **Vérifier Weekly/Daily Alignment** 📈📉

**Dashboard → Trend (Weekly) + Trend (Daily)**

**Configurations valides** :
- ✅ Weekly BULLISH + Daily BULLISH → Trades LONG uniquement
- ✅ Weekly BEARISH + Daily BEARISH → Trades SHORT uniquement
- ❌ Weekly BULLISH + Daily BEARISH → **AUCUN TRADE**
- ❌ Weekly BEARISH + Daily BULLISH → **AUCUN TRADE**

**Solution si misalignment** :
- Désactiver temporairement : Settings → "Weekly Trend Filter" → **Décocher**
- **OU** attendre que Weekly et Daily s'alignent

---

### 4. **Vérifier Premium/Discount** 🎯

Le script achète en **Discount** (65% du range) et vend en **Premium** (35% du range).

**Dashboard → Pricing** :
- ✅ "Discount" = OK pour acheter
- ✅ "Premium" = OK pour vendre
- ❌ "Discount" mais Trend BEARISH = Pas de trade LONG
- ❌ "Premium" mais Trend BULLISH = Pas de trade SHORT

**Solution si bloqué** :
- Désactiver : Settings → "Premium/Discount (ULTRA)" → **Décocher**
- **OU** ajuster le seuil : Code line 1055 → `pd_limit_buy = 0.75` (75%)

---

### 5. **Vérifier le Volume** 📊

**Filtre Volume** : Volume actuel doit être **> 0.5x** la moyenne des 14 dernières bougies

**Solution si volume trop faible** :
- Désactiver : Settings → "Volume Filter" → **Décocher**
- **OU** réduire seuil : Settings → Volume Multiplier → **0.3x**

---

### 6. **Vérifier la Mitigation (OB/FVG)** 🎯

Le script attend que le prix touche :
- Un **Order Block** (Swing ou Internal)
- **OU** un **Fair Value Gap**

**Sur le graphique** :
- Cherchez les boîtes bleues (Bullish OB) ou rouges (Bearish OB)
- Cherchez les zones cyan (Bullish FVG) ou orange (Bearish FVG)

**Si aucune zone visible** :
- Settings → Order Blocks → Activer "Internal Order Blocks" ET "Swing Order Blocks"
- Settings → Fair Value Gaps → **Cocher "Fair Value Gaps"**

---

### 7. **Vérifier Daily Loss Protection** 🛡️

Si vous avez déjà eu **2 trades perdants aujourd'hui** ou **-3% de drawdown** :
- Le script **STOP** de trader jusqu'à demain

**Solution** :
- Attendre le lendemain
- **OU** augmenter : Settings → Max Daily Trades Lost → **5**
- **OU** augmenter : Settings → Max Daily Drawdown → **5%**

---

## 🚀 CONFIGURATION RAPIDE POUR TESTER (24/7)

Pour voir des trades **immédiatement** en backtest :

1. **Désactiver Killzone** : ❌ Require Killzone for Entries
2. **Désactiver Weekly** : ❌ Weekly Trend Filter
3. **Réduire BOS** : BOS Strength → **0.3 ATR**
4. **Réduire Volume** : Volume Multiplier → **0.3x**
5. **Élargir P/D** : Code → `pd_limit_buy = 0.80` (80%)

**⚠️ Attention** : Cette config est pour **TESTER**, pas pour **VIVRE**.  
Pour le live trading, gardez les 8 Core Filters actifs !

---

## 📊 ORDRE DE PRIORITÉ DE DÉBOGAGE

1. **Killzone** → 90% des cas
2. **Weekly/Daily Alignment** → 70% des cas
3. **BOS Strength** → 50% des cas
4. **Premium/Discount** → 30% des cas
5. **Volume** → 20% des cas
6. **Daily Loss Protection** → 10% des cas

---

## 💡 ASTUCE PRO

Ajoutez un **label de debug** pour voir quel filtre bloque :

Dans le code ligne ~1192, après `if is_buy_trend and buy_conf...` :
```pine
// DEBUG
if is_buy_trend and buy_conf
    debug_txt = "BUY BLOCKED: "
    debug_txt := debug_txt + (weekly_confirm ? "" : "❌ Weekly | ")
    debug_txt := debug_txt + (d_align ? "" : "❌ Daily | ")
    debug_txt := debug_txt + (pd_confirm ? "" : "❌ P/D | ")
    debug_txt := debug_txt + (bos_str >= bos_threshold ? "" : "❌ BOS | ")
    debug_txt := debug_txt + (high_vol ? "" : "❌ Vol | ")
    debug_txt := debug_txt + (kz_confirm ? "" : "❌ KZ | ")
    
    if debug_txt != "BUY BLOCKED: "
        label.new(bar_index, low, debug_txt, color=color.yellow, style=label.style_label_up, textcolor=color.black, size=size.small)
```

Cela affichera exactement **quel(s) filtre(s) bloque(nt)** les trades.

---

## 📞 SUPPORT

Si après tout ça, toujours 0 trades :
- Vérifiez la **période du backtest** (minimum 3-6 mois)
- Essayez sur **EURUSD** ou **GBPUSD** en **15M** ou **1H**
- Vérifiez que "Show Buy/Sell Signals" est **coché**
