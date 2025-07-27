# -*- coding: utf-8 -*-
# Ce fichier est une bibliothèque de fonctions qui lit depuis Firestore.

import firebase_admin
from firebase_admin import credentials, firestore
from collections import defaultdict, Counter
import time
import json
import os
from datetime import datetime
import re

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
        print("Tentative d'initialisation de Firebase pour l'analyse...")
        try:
            if SECRETS_DISPONIBLES:
                cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_DICT)
                firebase_admin.initialize_app(cred)
                db = firestore.client()
                print("✅ Connexion à Firebase réussie via settings.py.")
                return True
            else:
                print("Fichier settings.py non trouvé, tentative avec les variables d'environnement...")
                firebase_admin.initialize_app()
                db = firestore.client()
                print("✅ Connexion à Firebase réussie via l'environnement.")
                return True
        except Exception as e:
            print(f"❌ ERREUR CRITIQUE : Impossible d'initialiser Firebase. {e}")
            return False
    elif db is None and firebase_admin._apps:
        db = firestore.client()
    return True

# --- Imports IA ---
try:
    import google.generativeai as genai
    IA_DISPONIBLE = True
except ImportError:
    IA_DISPONIBLE = False

# --- CONFIGURATIONS ---
FENETRE_RGNTC = 3
FENETRE_FORME_ECART = 50
NOMBRE_CANDIDATS_A_ANALYSER = 15

# --- FONCTIONS ---
def lire_tirages_depuis_firestore():
    if not db: return None
    print("-> Lecture des tirages depuis Firestore...")
    try:
        tirages_ref = db.collection('tirages').order_by('date_obj', direction=firestore.Query.DESCENDING).limit(5000)
        docs = tirages_ref.stream()
        tirages = []
        for doc in docs:
            data = doc.to_dict()
            gagnants, machine = data.get('gagnants', []), data.get('machine', [])
            numeros_sortis = set(gagnants + machine)
            date_obj = data.get('date_obj')
            if isinstance(date_obj, str): date_obj = datetime.fromisoformat(date_obj)
            tirages.append({
                "date_obj": date_obj, "nom_du_tirage": data.get("nom_du_tirage"),
                "gagnants": gagnants, "machine": machine, "numeros_sortis": list(numeros_sortis)
            })
        print(f"-> {len(tirages)} tirages chargés depuis Firestore.")
        return sorted(tirages, key=lambda x: x['date_obj'])
    except Exception as e:
        print(f"❌ Erreur lecture tirages Firestore : {e}"); return None

def lire_base_connaissance_depuis_firestore():
    if not db: return None
    print("-> Lecture de la base de connaissance depuis Firestore...")
    try:
        docs = db.collection('connaissance').stream()
        base_connaissance = {int(doc.id): set(doc.to_dict().get('accompagnateurs', [])) for doc in docs}
        print(f"-> {len(base_connaissance)} règles de connaissance chargées.")
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

def generer_prompt_final_pour_ia(dernier_tirage, rapport_rgntc, forme_ecart_data, base_connaissance, affinites_temporelles):
    nums_dernier_tirage = dernier_tirage['numeros_sortis']
    scores_candidats = Counter()
    for numero in nums_dernier_tirage:
        if numero in rapport_rgntc:
            for suiveur, score in rapport_rgntc[numero]['suiveurs']:
                if suiveur not in nums_dernier_tirage:
                    scores_candidats[suiveur] += score
    top_candidats = scores_candidats.most_common(NOMBRE_CANDIDATS_A_ANALYSER)
    prompt = f"Tu es un expert en analyse de loterie. Fais une prédiction de 2 numéros en combinant toutes les informations.\n\n" \
             f"CONTEXTE:\n- Derniers numéros sortis: {nums_dernier_tirage}\n\n" \
             f"1. ANALYSE DYNAMIQUE (Candidats et leur état récent):\n"
    for candidat, score in top_candidats:
        if candidat in forme_ecart_data:
            forme = forme_ecart_data[candidat]['forme']; ecart = forme_ecart_data[candidat]['ecart']
            prompt += f"- Candidat {candidat}: (Score Suiveur: {score}) | Forme: {forme}x/{FENETRE_FORME_ECART} | Écart: {ecart} tirages\n"
    prompt += f"\n2. ANALYSE STATIQUE (Base de connaissance):\n"
    confirmations_trouvees = False
    if base_connaissance:
        for candidat, score in top_candidats:
            for numero_sorti in nums_dernier_tirage:
                if numero_sorti in base_connaissance and candidat in base_connaissance[numero_sorti]:
                    prompt += f"- CONFIRMATION: Le candidat {candidat} est un 'accompagnateur' connu du numéro {numero_sorti}.\n"
                    confirmations_trouvees = True
    if not confirmations_trouvees: prompt += "- Aucune confirmation directe trouvée.\n"
    prompt += f"\n3. ANALYSE TEMPORELLE (basée sur la date du jour):\n"
    fav_jour, fav_mois = affinites_temporelles
    prompt += f"- Numéros favoris pour ce jour du mois : " + ", ".join([f"{n}({f}x)" for n, f in fav_jour] or ["Aucun"]) + "\n"
    prompt += f"- Numéros favoris pour ce mois : " + ", ".join([f"{n}({f}x)" for n, f in fav_mois] or ["Aucun"]) + "\n"
    prompt += "\n\nTA MISSION FINALE:\n1. Synthétise toutes les convergences.\n2. Choisis les 2 numéros les plus logiques.\n3. Justifie ta prédiction finale."
    return prompt

def appeler_ia_gemini(prompt):
    if not (IA_DISPONIBLE and SECRETS_DISPONIBLES):
        return "ERREUR: Module IA ou fichier de secrets non disponible."
    try:
        api_key = settings.GOOGLE_API_KEY
        if not api_key: return "ERREUR : Clé GOOGLE_API_KEY non trouvée dans settings.py"
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt, request_options={'timeout': 100})
        return response.text
    except Exception as e:
        return f"Erreur API Gemini: {e}"

def extraire_prediction_finale(texte_ia):
    try:
        lignes = texte_ia.splitlines()
        for i, ligne in enumerate(lignes):
            if "prédiction finale" in ligne.lower() or "sont :" in ligne.lower():
                prediction_text = ligne
                numeros = re.findall(r'\b\d{1,2}\b', prediction_text)
                if len(numeros) >= 2: return f"Les numéros prédits sont : {numeros[0]} et {numeros[1]}"
        numeros_gras = re.findall(r'\*\*(\d{1,2})\*\*', texte_ia)
        if len(numeros_gras) >= 2: return f"Les numéros prédits sont : {numeros_gras[0]} et {numeros_gras[1]}"
        return "Prédiction non trouvée. Veuillez consulter l'analyse complète."
    except Exception:
        return "Erreur lors de l'extraction de la prédiction."

def lancer_analyse_complete():
    """Exécute tout le pipeline en utilisant Firestore et retourne les résultats."""
    if not init_firestore():
        return {"erreur": "La connexion à la base de données Firestore a échoué."}
    
    print("--- Lancement de l'analyse complète (version Firestore) ---")
    base_connaissance = lire_base_connaissance_depuis_firestore()
    tous_les_tirages = lire_tirages_depuis_firestore()
    
    if not tous_les_tirages: return {"erreur": "Le chargement des tirages depuis Firestore a échoué."}
    if not base_connaissance: return {"erreur": "Le chargement de la base de connaissance depuis Firestore a échoué."}

    rapport_rgntc = analyser_relations_rgntc(tous_les_tirages)
    forme_ecart_data = calculer_forme_et_ecart(tous_les_tirages)
    affinites_temporelles = analyser_affinites_temporelles(tous_les_tirages, datetime.now().date())
    
    dernier_tirage = tous_les_tirages[-1]
    gagnants_str = ",".join(map(str, dernier_tirage.get('gagnants', [])))
    machine_str = ",".join(map(str, dernier_tirage.get('machine', [])))
    contexte_str = f"{dernier_tirage['date_obj'].strftime('%d/%m/%Y %H:%M')},{dernier_tirage['nom_du_tirage']},\"{gagnants_str}\",\"{machine_str}\""

    reponse_ia = appeler_ia_gemini(generer_prompt_final_pour_ia(dernier_tirage, rapport_rgntc, forme_ecart_data, base_connaissance, affinites_temporelles))
    prediction_simple = extraire_prediction_finale(reponse_ia)

    return {
        "contexte": contexte_str, "reponse_ia": reponse_ia,
        "prediction_simple": prediction_simple, "erreur": None
    }