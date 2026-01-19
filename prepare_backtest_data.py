"""
Préparation des données GBPUSD pour backtest (Version Corrigée v2)
Convertit les données tick (Tab-separated) en M15
"""

import pandas as pd
from pathlib import Path
from datetime import datetime

def prepare_gbpusd_data():
    """Prépare les données GBPUSDm pour le backtest"""
    
    data_dir = Path("data")
    
    print("\n" + "="*70)
    print("PREPARATION DONNEES BACKTEST - GBPUSDm")
    print("="*70 + "\n")
    
    # Vérifier le fichier tick
    tick_file = data_dir / "GBPUSDm_202501012205_202512300507.csv"
    
    if not tick_file.exists():
        print(f"ERROR: Fichier tick non trouvé: {tick_file}")
        return None
    
    print(f"Fichier tick trouvé: {tick_file.name}")
    print(f"Taille: {tick_file.stat().st_size / 1024 / 1024:.1f} MB")
    
    print("\nChargement des données tick (format Tab-separated)...")
    
    try:
        # Charger avec chunk pour économiser mémoire
        chunks = []
        chunk_size = 1000000
        
        # On spécifie le séparateur tabulation car le fichier est exporté depuis MT5 avec des tabs
        for i, chunk in enumerate(pd.read_csv(tick_file, sep='\t', chunksize=chunk_size)):
            # Nettoyer les noms de colonnes (retirer < >)
            chunk.columns = [c.replace('<', '').replace('>', '') for c in chunk.columns]
            
            # Créer une colonne datetime à partir de DATE et TIME
            if 'DATE' in chunk.columns and 'TIME' in chunk.columns:
                chunk['datetime'] = pd.to_datetime(chunk['DATE'] + ' ' + chunk['TIME'])
                # Supprimer les colonnes originales pour gagner de la place
                chunk = chunk.drop(['DATE', 'TIME'], axis=1)
            
            chunks.append(chunk)
            if (i + 1) % 5 == 0:
                print(f"  Chargé {(i+1)*chunk_size:,} lignes...")
            
            # Limiter à 15 millions de lignes pour être sûr de ne pas saturer la RAM
            if i >= 15:
                print(f"  Limité à {len(chunks)*chunk_size:,} lignes pour performance")
                break
        
        df_tick = pd.concat(chunks, ignore_index=True)
        print(f"\nLignes chargées: {len(df_tick):,}")
        
    except Exception as e:
        print(f"ERROR lors du chargement: {e}")
        return None
    
    # Convertir en M15
    print("\nConversion en bougies M15...")
    
    # Colonne prix (BID est standard)
    price_col = 'BID' if 'BID' in df_tick.columns else df_tick.select_dtypes(include=['float64', 'int64']).columns[0]
    print(f"Colonne prix utilisée: {price_col}")
    
    # Grouper par 15 min
    df_tick.set_index('datetime', inplace=True)
    
    # Agrégation OHLCV
    # Note: On utilise une liste de fonctions simples et on renomme après
    df_m15 = df_tick[price_col].resample('15T').agg(['first', 'max', 'min', 'last', 'count']).reset_index()
    df_m15.columns = ['time', 'open', 'high', 'low', 'close', 'volume']
    
    # Filtrer NaN (les périodes sans ticks)
    df_m15 = df_m15.dropna()
    
    print(f"Bougies M15 créées: {len(df_m15):,}")
    print(f"Période: {df_m15['time'].min()} -> {df_m15['time'].max()}")
    
    # Sauvegarder
    output_file = data_dir / "GBPUSDm_M15_backtest.csv"
    df_m15.to_csv(output_file, index=False)
    
    print(f"\nFichier sauvegardé: {output_file}")
    print(f"Taille: {output_file.stat().st_size / 1024:.1f} KB")
    
    return output_file

if __name__ == "__main__":
    result = prepare_gbpusd_data()
    if result:
        print(f"\nSUCCESS! Données prêtes pour le backtest.")
    else:
        print(f"\nERROR: Échec de la préparation.")
