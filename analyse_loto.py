# -*- coding: utf-8 -*-
# Ce fichier est une bibliothèque de fonctions qui lit depuis Firestore.

import firebase_admin
from firebase_admin import credentials, firestore
from collections import defaultdict, Counter
import time
import json
import os
from datetime import datetime, timedelta
import re
import pandas as pd

# --- Imports pour la visualisation et l'IA ---
try:
    import matplotlib
    matplotlib.use('Agg') # Mode non-interactif, crucial pour les serveurs
    import matplotlib.pyplot as plt
    import seaborn as sns
    VISUALISATION_DISPONIBLE = True
except ImportError:
    VISUALISATION_DISPONIBLE = False

try:
    import google.generativeai as genai
    IA_DISPONIBLE = True
except ImportError:
    IA_DISPONIBLE = False

# On importe les fonctions du collecteur
try:
    from cron_update_firestore import get_latest_data_from_api, parse_and_transform, deviner_heure_precise
    MODULES_COLLECTE_DISPONIBLES = True
except ImportError:
    MODULES_COLLECTE_DISPONIBLES = False

# --- On importe les secrets ---
try:
    import settings
    SECRETS_DISPONIBLES = True
except ImportError:
    SECRETS_DISPONIBLES = False

# --- VARIABLE GLOBALE POUR LA DB ---
db = None

# (Les fonctions init_firestore, lire_tirages, etc., ne changent pas et sont incluses ci-dessous)
def init_firestore():
    """Initialise la connexion à Firestore si elle n'est pas déjà faite."""
    global db
    if db is None and not firebase_admin._apps:
        try:
            if SECRETS_DISPONIBLES and hasattr(settings, 'FIREBASE_SERVICE_ACCOUNT_DICT'):
                cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_DICT)
                firebase_admin.initialize_app(cred)
                db = firestore.client()
                return True
            else:
                raise ValueError("Fichier settings.py ou secrets non trouvés.")
        except Exception as e:
            print(f"❌ ERREUR CRITIQUE : Impossible d'initialiser Firebase. {e}")
            return False
    elif db is None and firebase_admin._apps:
        db = firestore.client()
    return True

# --- CONFIGURATIONS ---
FENETRE_RGNTC = 3
FENETRE_FORME_ECART = 50
NOMBRE_CANDIDATS_A_ANALYSER = 15
TOP_N_HEATMAP = 25

# --- FONCTIONS ---
def detecter_prochain_tirage_et_contexte():
    if not MODULES_COLLECTE_DISPONIBLES: return None, "Module de collecte manquant"
    api_data = get_latest_data_from_api()
    tirages_recents = parse_and_transform(api_data) 
    if not tirages_recents: return None, "Impossible de déterminer le contexte (API inaccessible)"
    tirages_recents.sort(key=lambda x: x['data']['date_obj'], reverse=True)
    dernier_tirage_api = tirages_recents[0]
    heure_dernier_tirage_str = dernier_tirage_api['data']['date_obj'].strftime('%H:%M')
    heures_ordonnees = ["07:00", "08:00", "10:00", "13:00", "16:00", "19:00", "21:00", "22:00", "23:00"]
    cible = "Demain (07:00)"
    try:
        index_actuel = heures_ordonnees.index(heure_dernier_tirage_str)
        if index_actuel + 1 < len(heures_ordonnees):
            cible = f"Aujourd'hui ({heures_ordonnees[index_actuel + 1]})"
    except ValueError: pass
    return dernier_tirage_api, cible

def lire_tirages_depuis_firestore(db):
    if not db: return None
    try:
        tirages_ref = db.collection('tirages').order_by('date_obj', direction='DESCENDING').limit(5000)
        docs = tirages_ref.stream()
        tirages = []
        for doc in docs:
            data = doc.to_dict()
            gagnants, machine = data.get('gagnants', []), data.get('machine', [])
            numeros_sortis = set(gagnants + machine)
            date_obj = data.get('date_obj')
            if isinstance(date_obj, str): date_obj = datetime.fromisoformat(date_obj)
            tirages.append({"date_obj": date_obj, "nom_du_tirage": data.get("nom_du_tirage"), "gagnants": gagnants, "machine": machine, "numeros_sortis": list(numeros_sortis)})
        return sorted(tirages, key=lambda x: x['date_obj'])
    except Exception as e:
        print(f"❌ Erreur lecture tirages Firestore : {e}"); return None

def lire_base_connaissance_depuis_firestore(db):
    if not db: return None
    try:
        docs = db.collection('connaissance').stream()
        base_connaissance = {int(doc.id): set(doc.to_dict().get('accompagnateurs', [])) for doc in docs}
        return base_connaissance
    except Exception as e:
        print(f"❌ Erreur lecture connaissance Firestore : {e}"); return None

def analyser_affinites_temporelles(tous_les_tirages, date_cible):
    jour_cible, mois_cible = date_cible.day, date_cible.month
    frequence_jour, frequence_mois = Counter(), Counter()
    for tirage in tous_les_tirages:
        if tirage['date_obj'].date() < date_cible:
            if tirage['date_obj'].day == jour_cible: frequence_jour.update(tirage['numeros_sortis'])
            if tirage['date_obj'].month == mois_cible: frequence_mois.update(tirage['numeros_sortis'])
    return frequence_jour.most_common(5), frequence_mois.most_common(5)

def analyser_relations_rgntc(tous_les_tirages, fenetre=FENETRE_RGNTC):
    rapport = defaultdict(lambda: {k: Counter() for k in ["precurseurs", "compagnons", "suiveurs"]})
    total = len(tous_les_tirages)
    for i, t in enumerate(tous_les_tirages):
        nums = set(t['numeros_sortis'])
        for n1 in nums: rapport[n1]['compagnons'].update(list(nums - {n1}))
        for j in range(max(0, i - fenetre), i):
            for n_actuel in nums: rapport[n_actuel]['precurseurs'].update(tous_les_tirages[j]['numeros_sortis'])
        for j in range(i + 1, min(total, i + 1 + fenetre)):
            for n_actuel in nums: rapport[n_actuel]['suiveurs'].update(tous_les_tirages[j]['numeros_sortis'])
    return {num: {k: v.most_common(50) for k, v in rel.items()} for num, rel in rapport.items()}

def calculer_forme_et_ecart(tous_les_tirages, fenetre=FENETRE_FORME_ECART):
    forme_ecart_data, derniers_tirages_sets = {}, [set(t['numeros_sortis']) for t in tous_les_tirages[-fenetre:]]
    for numero in range(1, 91):
        forme = sum(1 for ts in derniers_tirages_sets if numero in ts)
        ecart = 0
        for ts in reversed(derniers_tirages_sets):
            if numero in ts: break
            ecart += 1
        if ecart == len(derniers_tirages_sets) and forme == 0: ecart = fenetre
        forme_ecart_data[numero] = {"forme": forme, "ecart": ecart}
    return forme_ecart_data

def generer_et_sauvegarder_heatmaps(rapport_rgntc, tous_les_tirages):
    if not VISUALISATION_DISPONIBLE:
        print("-> Bibliothèques de visualisation non installées. Heatmaps ignorées.")
        return None
    print("-> Génération des heatmaps...")
    static_folder = 'static'
    if not os.path.exists(static_folder):
        os.makedirs(static_folder)
    freq_globale = Counter(num for t in tous_les_tirages for num in t['numeros_sortis'])
    freqs_triees = freq_globale.most_common()
    top_nums = [n for n, f in freqs_triees[:TOP_N_HEATMAP]]
    chemins_images = {}
    for type_relation in ['compagnons', 'suiveurs', 'precurseurs']:
        matrice = pd.DataFrame(0, index=top_nums, columns=top_nums, dtype=int)
        for num1 in top_nums:
            if num1 in rapport_rgntc:
                for num2, freq in rapport_rgntc[num1][type_relation]:
                    if num2 in top_nums:
                        if type_relation == 'compagnons':
                            matrice.loc[num1, num2] = freq
                            matrice.loc[num2, num1] = freq
                        else:
                            matrice.loc[num1, num2] = freq
        plt.figure(figsize=(18, 15))
        sns.heatmap(matrice, annot=True, cmap="viridis", fmt="d", linewidths=.5)
        titre = f"Heatmap des {type_relation.capitalize()} des {TOP_N_HEATMAP} Numéros les plus Fréquents"
        plt.title(titre, fontsize=16)
        nom_fichier = f'heatmap_{type_relation}.png'
        chemin_fichier = os.path.join(static_folder, nom_fichier)
        plt.savefig(chemin_fichier)
        plt.close()
        chemins_images[type_relation] = nom_fichier
    print("-> Heatmaps sauvegardées avec succès.")
    return chemins_images

def generer_prompt_final_pour_ia(dernier_tirage, rapport_rgntc, forme_ecart_data, base_connaissance, affinites_temporelles):
    # ... (fonction inchangée)
    pass

def appeler_ia_gemini(prompt):
    # ... (fonction inchangée)
    pass

def extraire_prediction_finale(texte_ia):
    # ... (fonction inchangée)
    pass

def lancer_analyse_complete(db_client):
    """Exécute tout le pipeline, génère les heatmaps et retourne les résultats."""
    global db
    db = db_client
    if not db:
        return {"erreur": "La connexion à la base de données n'est pas disponible."}
    
    dernier_tirage_api, cible_tirage = detecter_prochain_tirage_et_contexte()
    if not dernier_tirage_api:
        return {"erreur": cible_tirage, "cible": "Inconnue"}

    date_jour = datetime.now().strftime('%Y-%m-%d')
    id_cache = f"{date_jour}_{cible_tirage.replace(' ', '').replace(':', 'h').replace('(', '').replace(')', '')}"
    cache_ref = db.collection('predictions_cache').document(id_cache)
    doc_cache = cache_ref.get()
    
    if doc_cache.exists:
        print(f"--- Analyse pour la cible '{cible_tirage}' trouvée dans le cache ! ---")
        return doc_cache.to_dict()
    
    print(f"--- Nouvelle analyse pour la cible '{cible_tirage}' ---")
    base_connaissance = lire_base_connaissance_depuis_firestore(db)
    tous_les_tirages = lire_tirages_depuis_firestore(db)
    if not tous_les_tirages or not base_connaissance:
        return {"erreur": "Le chargement des données depuis Firestore a échoué."}

    dernier_tirage_contexte = {
        'date_obj': dernier_tirage_api['data']['date_obj'],
        'nom_du_tirage': dernier_tirage_api['data']['nom_du_tirage'],
        'gagnants': dernier_tirage_api['data']['gagnants'],
        'machine': dernier_tirage_api['data']['machine'],
        'numeros_sortis': list(set(dernier_tirage_api['data']['gagnants'] + dernier_tirage_api['data']['machine']))
    }
    
    rapport_rgntc = analyser_relations_rgntc(tous_les_tirages)
    forme_ecart_data = calculer_forme_et_ecart(tous_les_tirages)
    affinites_temporelles = analyser_affinites_temporelles(tous_les_tirages, datetime.now().date())
    chemins_heatmaps = generer_et_sauvegarder_heatmaps(rapport_rgntc, tous_les_tirages) # Génération des images

    gagnants_str = ",".join(map(str, dernier_tirage_contexte.get('gagnants', [])))
    machine_str = ",".join(map(str, dernier_tirage_contexte.get('machine', [])))
    contexte_str = f"{dernier_tirage_contexte['date_obj'].strftime('%d/%m/%Y %H:%M')},{dernier_tirage_contexte['nom_du_tirage']},\"{gagnants_str}\",\"{machine_str}\""

    reponse_ia = appeler_ia_gemini(generer_prompt_final_pour_ia(dernier_tirage_contexte, rapport_rgntc, forme_ecart_data, base_connaissance, affinites_temporelles))
    prediction_simple = extraire_prediction_finale(reponse_ia)

    resultat_final = {
        "contexte": contexte_str, "reponse_ia": reponse_ia,
        "prediction_simple": prediction_simple, "cible": cible_tirage,
        "timestamp": datetime.now(), "erreur": None,
        "heatmaps": chemins_heatmaps # On ajoute les chemins des images
    }
    
    print(f"Sauvegarde de l'analyse dans le cache avec l'ID : {id_cache}")
    # On ne sauvegarde pas les images elles-mêmes, juste leurs noms
    cache_ref.set(resultat_final)
    
    return resultat_final