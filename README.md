# 🏦 SMC Fusion Ultra Strategy [Institutional Grade]

## 🌟 Présentation
Ce projet est une transformation complète d'un indicateur de Smart Money Concepts (SMC) en une **Stratégie de Trading Automatisée et Professionnelle** pour TradingView (Pine Script v5). Elle est conçue pour identifier les empreintes institutionnelles et exécuter des trades de haute précision avec une gestion de risque robuste.

---

## 🚀 Fonctionnalités Clés

### 1. Cœur Stratégique (SMC Pur)
* **Détection de Structure** : Identification automatique des BOS (Break of Structure) et CHoCH (Change of Character).
* **Zones de Supply & Demand** : Marquage des Order Blocks (OB) et Fair Value Gaps (FVG) avec mitigation logic.
* **Filtre Premium/Discount** : Algorithme interdisant les achats en zone Premium (trop cher) et les ventes en zone Discount (trop bas).
* **Alignement Multi-Timeframe** : Vérification automatique de la tendance journalière pour rester du côté des banques.
* **Liquidité (Sweeps)** : Confirmation obligatoire après un balayage de liquidité (Stop Hunt) pour éviter les pièges.

### 2. Gestion de Risque Avancée
* **Partial Take Profit (50%)** : Sécurisation automatique de la moitié des profits dès le ratio **1:1 RR**.
* **Break-Even Intelligent** : Déplacement automatique du Stop Loss à l'entrée dès qu'une cible est atteinte.
* **ATR Dynamic Padding** : Le Stop Loss s'adapte automatiquement à la volatilité de l'actif (indispensable pour l'Or et le Bitcoin).
* **Protection ADR** : Filtre d'épuisement du marché (seuil à 200%) pour éviter d'entrer en fin de mouvement.
* **Daily Loss Limit** : Arrêt automatique après 2 pertes consécutives dans la journée pour protéger le capital.

### 3. Interface & UX (Live Monitor)
* **Dashboard Interactif** : Un panneau de contrôle en direct affichant :
    * L'état du trade (Long/Short actif).
    * Le profit en temps réel (**RR** et **Pips**).
    * La validation du TP Partiel (✅).
    * Le biais du marché en attente de setup.
* **Large Visuals** : Labels géants sur le graphique pour un trading manuel sans effort.

---

## 🛠️ Configuration Optimale

| Paramètre | Recommandation |
| :--- | :--- |
| **Timeframe** | **15 Minutes** (Plus de clarté, moins de bruit) |
| **Actifs** | Gold (XAUUSD), Bitcoin (BTCUSD), Forex (EURUSD, GBPUSD) |
| **SL Padding** | 0.5 à 1.0 ATR (selon la volatilité) |
| **Risk:Reward** | 2.0 (Cible finale) |

---

## 📈 Résultats de l'Optimisation
Lors de nos sessions de tests intensifs :
* **EURUSD** : Profit Factor exceptionnel de **20.17** sur le 15m.
* **XAUUSD (Or)** : Déblocage des trades de tendance grâce à l'ajustement de l'ADR.
* **BTCUSD** : Performance positive de **+2.42%** avec une réduction drastique du drawdown grâce aux sorties partielles.

---

## 🤖 Automatisation (Alertes JSON)
La stratégie est prête pour les bots (3Commas, WunderTrading, etc.) avec un format JSON professionnel :
```json
{"pair": "BTCUSD", "action": "buy", "entry": 89500.5, "sl": 88400.0, "tp": 92000.0}
```

---

## 📜 Historique des Développements
1. **v1.0** : Conversion indicateur -> stratégie et ajout des commissions réelles.
2. **v2.0** : Intégration des filtres Premium/Discount et Liquidité.
3. **v3.0** : Ajout du Break-Even et de l'ATR Padding pour la volatilité.
4. **v4.0** : Implémentation du Partial TP (50%) à 1:1 RR.
5. **v5.0** : Création du Dashboard Dynamique Live et optimisation 15m.

---
*Développé avec précision pour le trading de Haute Qualité.* 🥂
