# -*- coding: utf-8 -*-
# Ce fichier est maintenant une bibliothèque de fonctions.

import requests
import pandas as pd
from datetime import datetime, timedelta
import locale
import os
import re

# --- CONFIGURATION ---
API_URL = "https://lotobonheur.ci/api/results"
NOM_FICHIER_DONNEES = "resultats_loto_bonheur_COMPLET.csv"
COLONNES_FINALES = ["date_complete", "nom_du_tirage", "numeros_gagnants", "numeros_machine"]

# --- MAPPINGS HORAIRES ---
MAPPINGS_HORAIRES = {
    "01H": ["Special Weekend 1h"], "03H": ["Special Weekend 3h"], "07H": ["Digital Reveil 7h"],
    "08H": ["Digital Reveil 8h"],
    "10H": ["Reveil", "La Matinale", "Premiere Heure", "Kado", "Cash", "Soutra", "Benediction"],
    "13H": ["Etoile", "Emergence", "Fortune", "Privilege", "Solution", "Diamant", "Prestige"],
    "16H": ["Akwaba", "Sika", "Baraka", "Monni", "Wari", "Moaye", "Awale"],
    "19H": ["Monday Special", "Lucky Tuesday", "Midweek", "Fortune Thursday", "Friday Bonanza", "National", "Espoir", "Spécial Lundi"],
    "21H": ["Digital 21h"], "22H": ["Digital 22h"], "23H": ["Digital 23h"]
}

def deviner_heure_precise(nom_tirage):
    for heure, noms in MAPPINGS_HORAIRES.items():
        if nom_tirage in noms: return heure.replace('H', ':00')
    for heure, noms in MAPPINGS_HORAIRES.items():
        for nom_base in noms:
            if nom_base in nom_tirage: return heure.replace('H', ':00')
    return "00:00"

def get_latest_data_from_api():
    try:
        response = requests.get(API_URL, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None

def parse_draw_data(draw, date_str, current_year):
    if not isinstance(draw, dict) or not draw.get('winningNumbers') or '.' in draw.get('winningNumbers'):
        return None
    draw_name = draw.get('drawName', '').strip()
    if "Réveil numérique" in draw_name: draw_name = draw_name.replace("Réveil numérique", "Digital Reveil")
    if "Milieu de semaine" in draw_name: draw_name = "Midweek"
    hour = deviner_heure_precise(draw_name)
    day, month = date_str.split('/')
    date_complete_str = f"{day}/{month}/{current_year} {hour}"
    try:
        datetime.strptime(date_complete_str, '%d/%m/%Y %H:%M')
        return {
            "date_complete": date_complete_str, "nom_du_tirage": draw_name,
            "numeros_gagnants": draw.get('winningNumbers', '').replace(' - ', ','),
            "numeros_machine": draw.get('machineNumbers', '').replace(' - ', ',')
        }
    except ValueError:
        return None

def transform_api_data_to_dataframe(api_data):
    if not api_data or not api_data.get('drawsResultsWeekly'):
        return pd.DataFrame()
    all_draws, current_year = [], datetime.now().year
    for week in api_data['drawsResultsWeekly']:
        for day in week.get('drawResultsDaily', []):
            date_str = day.get('date', '').split(' ')[-1]
            if not date_str or '/' not in date_str: continue
            draw_results = day.get('drawResults', {})
            for draw_type in ['nightDraws', 'standardDraws']:
                for draw in draw_results.get(draw_type, []):
                    parsed = parse_draw_data(draw, date_str, current_year)
                    if parsed: all_draws.append(parsed)
    return pd.DataFrame(all_draws)

# --- LA FONCTION PRINCIPALE QUE L'ON VA IMPORTER ---
def lancer_collecte():
    """Exécute tout le pipeline de collecte et retourne un message de statut."""
    print("--- Lancement de la collecte (version web) ---")
    
    if os.path.exists(NOM_FICHIER_DONNEES):
        df_existant = pd.read_csv(NOM_FICHIER_DONNEES)
    else:
        df_existant = pd.DataFrame(columns=COLONNES_FINALES)
    
    taille_avant = len(df_existant)

    latest_api_data = get_latest_data_from_api()
    df_nouveau = transform_api_data_to_dataframe(latest_api_data)

    if df_nouveau.empty:
        return "Aucune nouvelle donnée valide à ajouter. Le fichier est déjà à jour."
    
    df_combine = pd.concat([df_existant, df_nouveau], ignore_index=True)
    df_combine.drop_duplicates(subset=['date_complete', 'nom_du_tirage'], keep='last', inplace=True)
    
    df_combine['date_obj'] = pd.to_datetime(df_combine['date_complete'], format='mixed', dayfirst=True)
    df_final = df_combine.sort_values(by='date_obj', ascending=True).drop(columns=['date_obj'])
    df_final = df_final[COLONNES_FINALES]
    
    df_final.to_csv(NOM_FICHIER_DONNEES, index=False)
    
    nouveaux_ajouts = len(df_final) - taille_avant
    if nouveaux_ajouts > 0:
        return f"Mise à jour réussie ! {nouveaux_ajouts} tirage(s) ajouté(s)."
    else:
        return "Aucune nouvelle donnée à ajouter. Le fichier est déjà à jour."