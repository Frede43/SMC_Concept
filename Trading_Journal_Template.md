# 📊 TRADING JOURNAL - Template Excel

## Instructions de Création

Créez un fichier Excel avec les onglets suivants :

---

## ONGLET 1 : "Trades Log" (Journal Principal)

### Colonnes :

| A | B | C | D | E | F | G | H | I | J | K | L | M | N | O | P |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Date | Heure | Paire | TF | Direction | Entry | SL | TP | RR | Taille (lots) | Résultat | P&L (€) | P&L (%) | Émotion Avant | Émotion Après | Respect Plan ? | Notes |

### Exemple de Lignes :

```
Date        | Heure | Paire  | TF | Direction | Entry   | SL      | TP      | RR  | Taille | Résultat | P&L   | P&L % | Émotion Avant | Émotion Après | Plan ? | Notes
29/01/2026  | 14:30 | GBPUSD | 4H | LONG      | 1.3766  | 1.3729  | 1.3877  | 3:1 | 0.01   | WIN      | +30€  | +3%   | Confiant      | Heureux       | ✅ OUI | Signal parfait, tous filtres OK
30/01/2026  | 09:15 | GBPUSD | 1H | SHORT     | 1.3820  | 1.3850  | 1.3730  | 3:1 | 0.01   | LOSS     | -10€  | -1%   | FOMO          | Frustré       | ❌ NON | Pris sans sweep confirmé
```

### Formules Excel à Ajouter :

**Colonne J (Résultat)** : Saisie manuelle (WIN/LOSS/BE)

**Colonne K (P&L €)** : 
```excel
=SI(J2="WIN"; (G2-F2)*I2*100000; SI(J2="LOSS"; (F2-G2)*I2*100000; 0))
```

**Colonne L (P&L %)** : 
```excel
=K2/1000*100
```
(Supposant capital de 1000€)

**Colonne P (Respect Plan ?)** : Saisie manuelle (✅ OUI / ❌ NON)

---

## ONGLET 2 : "Statistiques Hebdomadaires"

### Colonnes :

| A | B | C | D | E | F | G | H | I |
|---|---|---|---|---|---|---|---|---|
| Semaine | Trades Total | Trades Conformes | % Discipline | Wins | Losses | Winrate | P&L Total (€) | Drawdown Max |

### Exemple :

```
Semaine | Trades | Conformes | % Discipline | Wins | Losses | Winrate | P&L    | Drawdown
S1      | 2      | 2         | 100%         | 2    | 0      | 100%    | +60€   | -0.5%
S2      | 3      | 2         | 67%          | 1    | 2      | 33%     | -20€   | -2.1%
S3      | 1      | 1         | 100%         | 1    | 0      | 100%    | +30€   | -1.8%
S4      | 2      | 2         | 100%         | 2    | 0      | 100%    | +60€   | +0.5%
```

### Formules :

**Colonne D (% Discipline)** :
```excel
=C2/B2*100
```

**Colonne G (Winrate)** :
```excel
=E2/(E2+F2)*100
```

**Colonne H (P&L Total)** :
```excel
=SOMME.SI('Trades Log'!A:A; "Semaine "&A2; 'Trades Log'!K:K)
```

---

## ONGLET 3 : "Analyse Émotionnelle"

### Colonnes :

| A | B | C | D | E |
|---|---|---|---|---|
| Émotion | Nombre de Trades | Wins | Losses | Winrate |

### Exemple :

```
Émotion   | Trades | Wins | Losses | Winrate
Neutre    | 15     | 11   | 4      | 73%
Confiant  | 8      | 6    | 2      | 75%
FOMO      | 5      | 1    | 4      | 20%    ← PROBLÈME !
Peur      | 3      | 1    | 2      | 33%
Vengeance | 2      | 0    | 2      | 0%     ← DANGER !
```

### Formules :

**Colonne B (Nombre de Trades)** :
```excel
=NB.SI('Trades Log'!N:N; A2)
```

**Colonne C (Wins)** :
```excel
=NB.SI.ENS('Trades Log'!N:N; A2; 'Trades Log'!J:J; "WIN")
```

**Colonne E (Winrate)** :
```excel
=C2/(C2+D2)*100
```

---

## ONGLET 4 : "Dashboard" (Tableau de Bord)

### Métriques Clés :

```
═══════════════════════════════════════════════════════════
                    TRADING DASHBOARD
═══════════════════════════════════════════════════════════

📊 PERFORMANCE GLOBALE
─────────────────────────────────────────────────────────
Capital Initial       : 1000€
Capital Actuel        : [Formule]
P&L Total             : [Formule]
P&L %                 : [Formule]
Max Drawdown          : [Formule]

📈 STATISTIQUES
─────────────────────────────────────────────────────────
Trades Total          : [Formule]
Wins                  : [Formule]
Losses                : [Formule]
Winrate               : [Formule]
Profit Factor         : [Formule]
Avg Win               : [Formule]
Avg Loss              : [Formule]
Best Trade            : [Formule]
Worst Trade           : [Formule]

🎯 DISCIPLINE
─────────────────────────────────────────────────────────
Trades Conformes      : [Formule]
% Discipline          : [Formule]
Violations du Plan    : [Formule]

⚠️ ALERTES
─────────────────────────────────────────────────────────
Drawdown Actuel       : [Formule] (Limite : -15%)
Trades Aujourd'hui    : [Formule] (Limite : 2)
Pertes Consécutives   : [Formule] (Limite : 2)

═══════════════════════════════════════════════════════════
```

### Formules pour Dashboard :

**Capital Actuel** :
```excel
=1000 + SOMME('Trades Log'!K:K)
```

**P&L Total** :
```excel
=SOMME('Trades Log'!K:K)
```

**Winrate** :
```excel
=NB.SI('Trades Log'!J:J;"WIN")/NB('Trades Log'!J:J)*100
```

**Profit Factor** :
```excel
=SOMME.SI('Trades Log'!K:K;">0")/ABS(SOMME.SI('Trades Log'!K:K;"<0"))
```

**% Discipline** :
```excel
=NB.SI('Trades Log'!P:P;"✅ OUI")/NB('Trades Log'!P:P)*100
```

---

## ONGLET 5 : "Checklist Pré-Trade"

### À Imprimer et Coller sur l'Écran :

```
═══════════════════════════════════════════════════════════
           ✅ CHECKLIST PRÉ-TRADE (OBLIGATOIRE)
═══════════════════════════════════════════════════════════

AVANT DE CLIQUER SUR "BUY" OU "SELL" :

☐ 1. Signal vient de MA stratégie (pas YouTube/Twitter) ?
☐ 2. TOUS les filtres validés (BOS, OB/FVG, Daily, P/D, etc.) ?
☐ 3. SL et TP calculés AVANT l'entrée ?
☐ 4. Risque = 1% maximum ?
☐ 5. État émotionnel NEUTRE (pas FOMO/peur/vengeance) ?
☐ 6. Moins de 2 trades aujourd'hui ?
☐ 7. Moins de 2 pertes aujourd'hui ?
☐ 8. J'accepte de perdre X€ ? (dire à voix haute)
☐ 9. Trade noté dans le journal ?
☐ 10. Prêt à NE PAS regarder pendant 4H ?

═══════════════════════════════════════════════════════════
SI UNE SEULE RÉPONSE = NON → NE PRENEZ PAS LE TRADE
═══════════════════════════════════════════════════════════
```

---

## ONGLET 6 : "Review Hebdomadaire"

### Questions à Répondre Chaque Dimanche Soir :

```
═══════════════════════════════════════════════════════════
              📝 REVIEW HEBDOMADAIRE - Semaine [X]
═══════════════════════════════════════════════════════════

📊 STATISTIQUES
─────────────────────────────────────────────────────────
1. Combien de trades ai-je pris ?           : _____
2. Combien respectaient le plan ?           : _____
3. % de discipline ?                        : _____%
4. Winrate cette semaine ?                  : _____%
5. P&L cette semaine ?                      : _____€
6. Drawdown max cette semaine ?             : _____%

🧠 ANALYSE ÉMOTIONNELLE
─────────────────────────────────────────────────────────
7. Quelle émotion dominait ?                : _________
8. Ai-je fait du FOMO trading ?             : OUI / NON
9. Ai-je fait du revenge trading ?          : OUI / NON
10. Ai-je over-tradé (>2 trades/jour) ?     : OUI / NON

📈 PERFORMANCE
─────────────────────────────────────────────────────────
11. Résultats cohérents avec backtest ?     : OUI / NON
12. Meilleur trade de la semaine ?          : _________
13. Pire trade de la semaine ?              : _________
14. Leçon apprise ?                         : _________

🎯 OBJECTIFS
─────────────────────────────────────────────────────────
15. Objectif de la semaine prochaine ?      : _________
16. Règle à améliorer ?                     : _________
17. Récompense méritée ?                    : OUI / NON

═══════════════════════════════════════════════════════════
```

---

## 📌 INSTRUCTIONS D'UTILISATION

### Routine Quotidienne :

1. **Avant la session** : Lire la Checklist
2. **Après chaque trade** : Remplir "Trades Log" IMMÉDIATEMENT
3. **Fin de journée** : Vérifier Dashboard (alertes)

### Routine Hebdomadaire :

1. **Dimanche soir** : Remplir "Review Hebdomadaire"
2. **Calculer** : % Discipline, Winrate, P&L
3. **Analyser** : Émotions dominantes
4. **Ajuster** : Plan pour la semaine suivante

### Routine Mensuelle :

1. **Calculer** : Performance du mois
2. **Comparer** : Avec le backtest (±30% acceptable)
3. **Décider** : Continuer / Ajuster / Pause

═══════════════════════════════════════════════════════════
