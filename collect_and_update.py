# -*- coding: utf-8 -*-

import requests
import pandas as pd
from datetime import datetime
import locale
import os
import re

# --- CONFIGURATION ---
API_URL = "https://lotobonheur.ci/api/results"
NOM_FICHIER_DONNEES = "resultats_loto_bonheur_COMPLET.csv"
COLONNES_FINALES = ["date_complete", "nom_du_tirage", "numeros_gagnants", "numeros_machine"]

# --- MAPPINGS HORAIRES COMPLETS (LA CLÉ DE LA CORRECTION) ---
MAPPINGS_HORAIRES = {
    "01H": ["Special Weekend 1h"],
    "03H": ["Special Weekend 3h"],
    "07H": ["Digital Reveil 7h"],
    "08H": ["Digital Reveil 8h"],
    "10H": ["Reveil", "La Matinale", "Premiere Heure", "Kado", "Cash", "Soutra", "Benediction"],
    "13H": ["Etoile", "Emergence", "Fortune", "Privilege", "Solution", "Diamant", "Prestige"],
    "16H": ["Akwaba", "Sika", "Baraka", "Monni", "Wari", "Moaye", "Awale"],
    "19H": ["Monday Special", "Lucky Tuesday", "Midweek", "Fortune Thursday", "Friday Bonanza", "National", "Espoir", "Spécial Lundi"],
    "21H": ["Digital 21h"],
    "22H": ["Digital 22h"],
    "23H": ["Digital 23h"]
}

def deviner_heure_precise(nom_tirage):
    """Devine l'heure d'un tirage en se basant sur son nom."""
    for heure, noms in MAPPINGS_HORAIRES.items():
        # Recherche exacte (plus fiable)
        if nom_tirage in noms:
            return heure.replace('H', ':00')
    # Recherche partielle si non trouvé (pour les variations de nom)
    for heure, noms in MAPPINGS_HORAIRES.items():
        for nom_base in noms:
            if nom_base in nom_tirage:
                return heure.replace('H', ':00')
    return "00:00" # Heure par défaut si inconnu

def get_latest_data_from_api():
    """Appelle l'API principale pour récupérer les données des dernières semaines."""
    print(f"\n⏳ Tentative de récupération des données depuis l'API principale...")
    try:
        response = requests.get(API_URL, timeout=30)
        response.raise_for_status()
        data = response.json()
        print(f"✅ Succès : Données reçues de l'API.")
        return data
    except requests.exceptions.RequestException as err:
        print(f"❌ Erreur lors de la requête API : {err}")
    return None

def parse_draw_data(draw, date_str, current_year):
    """Extrait les informations d'un seul tirage et assigne la bonne heure."""
    if not isinstance(draw, dict) or not draw.get('winningNumbers') or '.' in draw.get('winningNumbers'):
        return None

    draw_name = draw.get('drawName', '').strip()
    # Nettoyage des noms pour la cohérence
    if "Réveil numérique" in draw_name: draw_name = draw_name.replace("Réveil numérique", "Digital Reveil")
    if "Milieu de semaine" in draw_name: draw_name = "Midweek"
    
    hour = deviner_heure_precise(draw_name)
    
    day, month = date_str.split('/')
    date_complete_str = f"{day}/{month}/{current_year} {hour}"
    
    try:
        datetime.strptime(date_complete_str, '%d/%m/%Y %H:%M')
        return {
            "date_complete": date_complete_str,
            "nom_du_tirage": draw_name,
            "numeros_gagnants": draw.get('winningNumbers', '').replace(' - ', ','),
            "numeros_machine": draw.get('machineNumbers', '').replace(' - ', ',')
        }
    except ValueError:
        return None

def transform_api_data_to_dataframe(api_data):
    """Transforme la structure complexe de l'API en une table (DataFrame)."""
    if not api_data or not api_data.get('drawsResultsWeekly'):
        return pd.DataFrame()

    all_draws = []
    current_year = datetime.now().year

    for week in api_data['drawsResultsWeekly']:
        for day in week.get('drawResultsDaily', []):
            date_str = day.get('date', '').split(' ')[-1]
            if not date_str or not '/' in date_str: continue

            draw_results = day.get('drawResults', {})
            for draw_type in ['nightDraws', 'standardDraws']:
                for draw in draw_results.get(draw_type, []):
                    parsed = parse_draw_data(draw, date_str, current_year)
                    if parsed:
                        all_draws.append(parsed)
                        
    return pd.DataFrame(all_draws)

if __name__ == "__main__":
    print("--- Lancement du script de collecte et mise à jour (v4 - Final) ---")
    
    if os.path.exists(NOM_FICHIER_DONNEES):
        print(f"\n1. Lecture du fichier existant '{NOM_FICHIER_DONNEES}'...")
        df_existant = pd.read_csv(NOM_FICHIER_DONNEES)
        print(f"   -> {len(df_existant)} tirages chargés.")
    else:
        print(f"\n1. Fichier '{NOM_FICHIER_DONNEES}' non trouvé. Un nouveau fichier sera créé.")
        df_existant = pd.DataFrame(columns=COLONNES_FINALES)

    latest_api_data = get_latest_data_from_api()
    df_nouveau = transform_api_data_to_dataframe(latest_api_data)

    if df_nouveau.empty:
        print("\nAucune nouvelle donnée valide à ajouter. Le fichier reste inchangé.")
    else:
        print(f"\n2. {len(df_nouveau)} nouveaux tirages potentiels ont été récupérés et validés.")
        print("\n3. Fusion des données et suppression des doublons...")
        
        df_combine = pd.concat([df_existant, df_nouveau], ignore_index=True)
        # Créer une clé unique pour la déduplication (date + nom du tirage)
        df_combine.drop_duplicates(subset=['date_complete', 'nom_du_tirage'], keep='last', inplace=True)
        
        nouveaux_ajouts = len(df_combine) - len(df_existant)
        
        if nouveaux_ajouts > 0:
             print(f"   -> {nouveaux_ajouts} tirage(s) unique(s) a(ont) été ajouté(s).")
        else:
            print("   -> Aucune nouvelle donnée à ajouter. Votre fichier est déjà à jour.")

        print("\n4. Tri et sauvegarde du fichier final...")
        
        df_combine['date_obj'] = pd.to_datetime(df_combine['date_complete'], format='mixed', dayfirst=True)
        df_final = df_combine.sort_values(by='date_obj', ascending=True).drop(columns=['date_obj'])
        
        df_final = df_final[COLONNES_FINALES]

        df_final.to_csv(NOM_FICHIER_DONNEES, index=False)
        print(f"✅ Fichier '{NOM_FICHIER_DONNEES}' mis à jour avec succès.")
        print(f"   -> Le fichier contient maintenant {len(df_final)} tirages au total.")

    print("\n--- Script de collecte terminé ---")