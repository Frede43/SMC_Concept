
from typing import Dict, Any, Optional

class SmartCoach:
    """
    Module pédagogique qui traduit les décisions techniques du bot
    en explications éducatives pour l'utilisateur.
    """
    
    @staticmethod
    def explain_trade_decision(symbol: str, signal: str, reason: str, analysis: Dict[str, Any], decision_data: Dict[str, Any]) -> str:
        """Génère une explication pédagogique structurée."""
        
        # 1. Analyser le contexte
        trend_ltf = analysis.get('trend', 'NEUTRAL')
        trend_htf = analysis.get('htf_trend', 'NEUTRAL')
        if hasattr(trend_htf, 'name'): trend_htf = trend_htf.name
        
        zone = analysis.get('premium_discount', 'equilibrium')
        pd_percent = analysis.get('premium_discount_percent', 50)
        
        score = decision_data.get('score', 0)
        veto = decision_data.get('htf_veto', False)
        macro_bias = decision_data.get('macro_bias', 'NEUTRAL')
        
        # 2. Construire le message
        emoji_signal = "🟢" if signal == "BUY" else "🔴" if signal == "SELL" else "⚪"
        action = "J'AI PRIS CE TRADE" if "EXECUTED" in reason else "J'AI REFUSÉ CE TRADE"
        
        msg = [
            f"🎓 **ANALYSE PÉDAGOGIQUE DU BOT ({symbol})**",
            f"--------------------------------------------------",
            f"{emoji_signal} **Décision : {action}**",
            f"",
            "**1. LE CONTEXTE (La Météo) :**",
        ]
        
        # Explication Macro/HTF
        if macro_bias != 'NEUTRAL':
            msg.append(f"   • 🌍 **Macro:** Le biais fondamental est {macro_bias}. {'✅ Ça aide !' if macro_bias in [signal, 'BULLISH' if signal=='BUY' else 'BEARISH'] else '⚠️ Vent de face !'}")
        
        htf_align = "Aligné ✅" if trend_htf in [signal, 'BULLISH' if signal=='BUY' else 'BEARISH'] else "Conflit ⚠️"
        msg.append(f"   • 🌊 **Tendance de Fond (Daily):** {trend_htf} ({htf_align})")
        
        # Explication Zone P/D
        is_good_zone = (signal == "BUY" and zone == "discount") or (signal == "SELL" and zone == "premium")
        zone_icon = "✅" if is_good_zone else "❌"
        zone_desc = "Pas cher (Soldes)" if zone == "discount" else "Cher (Premium)" if zone == "premium" else "Neutre"
        msg.append(f"   • 🏷️ **Prix Actuel:** {zone} ({pd_percent:.1f}%). {zone_icon} Pour {signal}, c'est {zone_desc}.")
        
        # 3. Le Setup SMC
        msg.append("") # Ligne vide
        msg.append("**2. LA TECHNIQUE (Ce que j'ai vu) :**")
        
        fvg = analysis.get('fvg_data', {})
        sweep = analysis.get('sweep_data', {})
        
        # Détails Sweep
        if sweep:
            sweep_level = sweep.get('level', 0)
            sweep_type = sweep.get('type', 'Unknown')
            msg.append(f"   • 🧹 **Liquidity Sweep:** Chasse aux stops confirmée sur le niveau **{sweep_level:.5f}** ({sweep_type}).")
            msg.append(f"     _(Les stops des traders impatients ont été pris ici)_")
        else:
            msg.append(f"   • 🧹 **Pas de Sweep Majeur:** (Entrée plus risquée sans prise de liquidité préalable).")
            
        # Détails FVG
        if fvg:
            top = fvg.get('top', 0)
            bottom = fvg.get('bottom', 0)
            fvg_type = "Haussier (Support)" if signal == "BUY" else "Baissier (Résistance)"
            msg.append(f"   • 🕳️ **FVG:** Gap {fvg_type} détecté entre **{bottom:.5f}** et **{top:.5f}**.")
            msg.append(f"     _(Le prix est revenu combler ce vide avant de repartir)_")
        
        # Détails Order Block
        bull_obs = analysis.get('bullish_obs', [])
        bear_obs = analysis.get('bearish_obs', [])
        relevant_obs = bull_obs if signal == "BUY" else bear_obs
        
        if relevant_obs and len(relevant_obs) > 0:
            # Prendre le plus proche du prix actuel
            # (On suppose que c'est le dernier de la liste ou le premier, simplifions en prenant le dernier détecté)
            ob = relevant_obs[-1] 
            if isinstance(ob, dict):
                ob_top = ob.get('top', 0)
                ob_bottom = ob.get('bottom', 0)
            else:
                ob_top = getattr(ob, 'top', 0)
                ob_bottom = getattr(ob, 'bottom', 0)
            
            if ob_top > 0:
                msg.append(f"   • 🧱 **Order Block:** Appui sur bloc institutionnel à **{ob_bottom:.5f} - {ob_top:.5f}**.")
            
        # 4. Le Verdict (Pourquoi ?)
        msg.append("") # Ligne vide
        msg.append("**3. LE VERDICT (La Leçon) :**")
        
        if veto:
            msg.append(f"   🚫 **VETO:** La technique était là, mais le contexte (HTF/Macro) était trop dangereux. On ne nage pas contre le courant.")
        elif score < 70 and "EXECUTED" not in reason:
             msg.append(f"   ⚪ **Hésitation:** Le score ({score}/100) est trop bas. Il manque une confirmation (peut-être la zone ou la tendance).")
        elif "EXECUTED" in reason:
            msg.append(f"   🚀 **Go !** Tous les feux sont verts (ou presque). Le setup est valide et le risque est mesuré.")
            
        # Conseil Personnalisé
        msg.append("") # Ligne vide
        msg.append("**💡 CONSEIL POUR TOI :**")
        if not is_good_zone:
            wait_dir = "baisse" if signal == "BUY" else "monte"
            msg.append(f"   Attends que le prix {wait_dir} encore un peu pour avoir un meilleur prix d'entrée (Zone {('Discount' if signal=='BUY' else 'Premium')}).")
        elif veto:
            msg.append(f"   Ne force pas. Regarde le graphique Daily. Vois-tu la résistance/support majeur ? C'est lui qui bloque.")
        else:
            msg.append(f"   Observe comment le prix réagit sur ce niveau. Note ce setup dans ton journal.")
            
        return "\n".join(msg)

