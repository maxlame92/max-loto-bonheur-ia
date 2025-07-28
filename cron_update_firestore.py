# -*- coding: utf-8 -*-
# Ce fichier est une bibliothèque de fonctions conçue pour mettre à jour Firestore.

import firebase_admin
from firebase_admin import credentials, firestore
import requests
from datetime import datetime
import re
import os
import json

# --- On importe nos secrets (si le fichier existe) ---
try:
    import settings
    SECRETS_DISPONIBLES = True
except ImportError:
    SECRETS_DISPONIBLES = False

# --- VARIABLE GLOBALE POUR LA DB (initialisée à None) ---
db = None

def init_firestore():
    """Initialise la connexion à Firestore si elle n'est pas déjà faite."""
    global db
    if db is None and not firebase_admin._apps:
        print("Tentative d'initialisation de Firebase...")
        try:
            if SECRETS_DISPONIBLES and hasattr(settings, 'FIREBASE_SERVICE_ACCOUNT_DICT'):
                cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_DICT)
                firebase_admin.initialize_app(cred)
                db = firestore.client()
                print("✅ Connexion à Firebase réussie via settings.py.")
                return True
            else:
                creds_json_str = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
                if creds_json_str:
                    cred_dict = json.loads(creds_json_str)
                    cred = credentials.Certificate(cred_dict)
                    firebase_admin.initialize_app(cred)
                    db = firestore.client()
                    print("✅ Connexion à Firebase réussie via l'environnement.")
                    return True
                else:
                    raise ValueError("Aucune clé de service Firebase trouvée (ni settings.py, ni variable d'env).")
        except Exception as e:
            print(f"❌ ERREUR CRITIQUE : Impossible d'initialiser Firebase. {e}")
            return False
    elif db is None and firebase_admin._apps:
        db = firestore.client()
    return True

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
    for heure, noms in MAPPINGS_HORAIRES.items():
        if nom_tirage in noms: return heure.replace('H', ':00')
    for heure, noms in MAPPINGS_HORAIRES.items():
        for nom_base in noms:
            if nom_base in nom_tirage: return heure.replace('H', ':00')
    return "00:00"

def get_latest_data_from_api():
    print("-> Appel de l'API Loto Bonheur...")
    try:
        response = requests.get(API_URL, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"-> Erreur API : {e}"); return None

def parse_draw_data(draw, date_str, current_year):
    if not isinstance(draw, dict) or not draw.get('winningNumbers') or '.' in draw.get('winningNumbers'): return None
    draw_name = draw.get('drawName', '').strip()
    if "Réveil numérique" in draw_name: draw_name = draw_name.replace("Réveil numérique", "Digital Reveil")
    if "Milieu de semaine" in draw_name: draw_name = "Midweek"
    hour = deviner_heure_precise(draw_name)
    day_part, month_part = date_str.split('/')
    try:
        date_obj = datetime.strptime(f"{day_part}/{month_part}/{current_year} {hour}", '%d/%m/%Y %H:%M')
        doc_id = date_obj.strftime('%Y%m%d%H%M') + "_" + re.sub(r'[^a-zA-Z0-9]', '', draw_name)
        return {"doc_id": doc_id, "data": {'date_obj': date_obj, 'nom_du_tirage': draw_name, 'gagnants': [int(n.strip()) for n in draw.get('winningNumbers', '').replace(' - ', ',').split(',') if n.strip().isdigit()], 'machine': [int(n.strip()) for n in draw.get('machineNumbers', '').replace(' - ', ',').split(',') if n.strip().isdigit()]}}
    except ValueError: return None

def parse_and_transform(api_data):
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
    print(f"-> {len(all_draws)} tirages valides extraits de l'API.")
    return all_draws

def lancer_collecte_vers_firestore():
    """Fonction principale optimisée pour respecter les quotas de Firestore."""
    if not init_firestore():
        return "Erreur : La connexion à Firestore n'a pas pu être établie."

    print("\n--- Lancement de la collecte vers Firestore (Optimisée) ---")
    
    api_data = get_latest_data_from_api()
    nouveaux_tirages = parse_and_transform(api_data)

    if not nouveaux_tirages:
        message = "Aucun nouveau tirage valide trouvé dans l'API."
        print(message); return message

    collection_ref = db.collection('tirages')
    batch = db.batch()
    nouveaux_ajouts = 0
    
    # --- OPTIMISATION MAJEURE ICI ---
    # 1. On récupère les IDs des 300 derniers tirages stockés
    print("-> Récupération des IDs récents depuis Firestore...")
    try:
        # .select([]) est une astuce pour ne récupérer que les IDs, ce qui est très rapide et peu coûteux
        query = collection_ref.order_by('date_obj', direction='DESCENDING').limit(300).select([])
        docs = query.stream()
        ids_existants = set(doc.id for doc in docs)
        print(f"-> {len(ids_existants)} IDs récents chargés pour vérification.")
    except Exception as e:
        print(f"❌ Erreur lors de la récupération des IDs existants : {e}")
        return "Erreur lors de la vérification des données existantes."
    # --- FIN DE L'OPTIMISATION ---
    
    operations_count = 0
    for tirage in nouveaux_tirages:
        # On vérifie si l'ID du nouveau tirage est déjà dans notre liste d'IDs récents
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
    lancer_collecte_vers_firestore()