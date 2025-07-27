# -*- coding: utf-8 -*-
# Ce script est destiné à être exécuté dans un environnement cloud pour mettre à jour Firestore.

import firebase_admin
from firebase_admin import credentials, firestore
import requests
from datetime import datetime
import re
import os

# --- INITIALISATION DE FIREBASE ---
# Gère à la fois l'exécution locale (avec le fichier) et l'exécution cloud (avec les variables d'env)
if not firebase_admin._apps:
    try:
        # Si on est en local et que le fichier de clé existe
        if os.path.exists("serviceAccountKey.json"):
            cred = credentials.Certificate("serviceAccountKey.json")
            firebase_admin.initialize_app(cred)
            print("Initialisation Firebase avec la clé de service locale.")
        else:
            # Sur Render/Cloud, les identifiants sont trouvés automatiquement
            firebase_admin.initialize_app()
            print("Initialisation Firebase avec les identifiants de l'environnement.")
        db = firestore.client()
        print("✅ Connexion à Firebase réussie.")
    except Exception as e:
        print(f"❌ ERREUR CRITIQUE : Impossible d'initialiser Firebase. {e}")
        db = None
else:
    db = firestore.client()

# --- CONFIGURATION ET MAPPINGS ---
API_URL = "https://lotobonheur.ci/api/results"
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
    """Devine l'heure d'un tirage en se basant sur son nom pour un tri correct."""
    for heure, noms in MAPPINGS_HORAIRES.items():
        if nom_tirage in noms: return heure.replace('H', ':00')
    for heure, noms in MAPPINGS_HORAIRES.items():
        for nom_base in noms:
            if nom_base in nom_tirage: return heure.replace('H', ':00')
    return "00:00"

def get_latest_data_from_api():
    """Appelle l'API principale de Loto Bonheur pour récupérer les données récentes."""
    print("-> Appel de l'API Loto Bonheur...")
    try:
        response = requests.get(API_URL, timeout=30)
        response.raise_for_status()
        print("-> Données reçues de l'API.")
        return response.json()
    except Exception as e:
        print(f"-> Erreur API : {e}")
        return None

def parse_draw_data(draw, date_str, current_year):
    """Extrait et nettoie les informations d'un seul tirage."""
    if not isinstance(draw, dict) or not draw.get('winningNumbers') or '.' in draw.get('winningNumbers'):
        return None
    draw_name = draw.get('drawName', '').strip()
    # Nettoyage des noms pour la cohérence
    if "Réveil numérique" in draw_name: draw_name = draw_name.replace("Réveil numérique", "Digital Reveil")
    if "Milieu de semaine" in draw_name: draw_name = "Midweek"
    hour = deviner_heure_precise(draw_name)
    day_part, month_part = date_str.split('/')
    try:
        date_obj = datetime.strptime(f"{day_part}/{month_part}/{current_year} {hour}", '%d/%m/%Y %H:%M')
        # Créer un ID de document unique et propre
        doc_id = date_obj.strftime('%Y%m%d%H%M') + "_" + re.sub(r'[^a-zA-Z0-9]', '', draw_name)
        
        return {
            "doc_id": doc_id,
            "data": {
                'date_obj': date_obj, 'nom_du_tirage': draw_name,
                'gagnants': [int(n.strip()) for n in draw.get('winningNumbers', '').replace(' - ', ',').split(',') if n.strip().isdigit()],
                'machine': [int(n.strip()) for n in draw.get('machineNumbers', '').replace(' - ', ',').split(',') if n.strip().isdigit()]
            }
        }
    except ValueError:
        return None

def parse_and_transform(api_data):
    """Transforme la structure complexe de l'API en une liste de tirages prêts pour Firestore."""
    if not api_data or not api_data.get('drawsResultsWeekly'): return []
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
    print(f"-> {len(all_draws)} tirages valides extraits de la réponse API.")
    return all_draws

def lancer_collecte_vers_firestore():
    """Fonction principale pour collecter et mettre à jour Firestore."""
    if not db:
        return "Erreur : La connexion à Firestore n'a pas pu être établie."

    print("\n--- Lancement de la collecte vers Firestore ---")
    
    api_data = get_latest_data_from_api()
    nouveaux_tirages = parse_and_transform(api_data)

    if not nouveaux_tirages:
        message = "Aucun nouveau tirage valide trouvé dans l'API."
        print(message)
        return message

    collection_ref = db.collection('tirages')
    batch = db.batch()
    nouveaux_ajouts = 0
    
    ids_a_verifier = [t["doc_id"] for t in nouveaux_tirages]
    if not ids_a_verifier:
        message = "Aucun ID de tirage à vérifier dans les données de l'API."
        print(message)
        return message
        
    ids_existants = set()
    # On découpe la grosse liste en plusieurs petites listes de 30 pour respecter les limites de Firestore
    print("-> Vérification des tirages existants dans Firestore...")
    for i in range(0, len(ids_a_verifier), 30):
        chunk = ids_a_verifier[i:i + 30]
        docs_existants_chunk = collection_ref.where('__name__', "in", chunk).stream()
        for doc in docs_existants_chunk:
            ids_existants.add(doc.id)
    
    operations_count = 0
    for tirage in nouveaux_tirages:
        if tirage["doc_id"] not in ids_existants:
            doc_ref = collection_ref.document(tirage["doc_id"])
            batch.set(doc_ref, tirage["data"])
            nouveaux_ajouts += 1
            operations_count += 1
            if operations_count >= 499:
                print(f"   -> Envoi d'un lot de {operations_count} documents...")
                batch.commit()
                batch = db.batch()
                operations_count = 0

    if operations_count > 0:
        print(f"   -> Envoi du dernier lot de {operations_count} documents...")
        batch.commit()
    
    if nouveaux_ajouts > 0:
        message = f"Mise à jour réussie ! {nouveaux_ajouts} tirage(s) ajouté(s) à Firestore."
    else:
        message = "Base de données déjà à jour. Aucun ajout."
        
    print(message)
    return message

if __name__ == '__main__':
    # Cette partie permet de lancer le script directement depuis la console pour un test
    lancer_collecte_vers_firestore()