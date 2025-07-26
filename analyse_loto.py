# -*- coding: utf-8 -*-
# Ce fichier est maintenant une bibliothèque de fonctions.

import csv
from collections import defaultdict, Counter
import time
import json
import os
from datetime import datetime
import pandas as pd
import re

try:
    import google.generativeai as genai
    IA_DISPONIBLE = True
except ImportError:
    IA_DISPONIBLE = False

# --- CONFIGURATIONS ET PARAMÈTRES ---
NOM_FICHIER_DONNEES = "resultats_loto_bonheur_COMPLET.csv"
NOM_FICHIER_BASE_CONNAISSANCE = "base de numero et cest accompagne.txt"
FENETRE_RGNTC = 3
FENETRE_FORME_ECART = 50
NOMBRE_CANDIDATS_A_ANALYSER = 15

# --- FONCTIONS DE TRAITEMENT ET D'ANALYSE ---
def nettoyer_numeros_str(numeros_str):
    if not isinstance(numeros_str, str): return []
    return [int(n.strip()) for n in numeros_str.split(',') if n.strip().isdigit()]

def lire_base_connaissance(nom_fichier):
    base_connaissance = {}
    if not os.path.exists(nom_fichier):
        print(f"-> Fichier connaissance non trouvé: {nom_fichier}")
        return None
    try:
        with open(nom_fichier, mode='r', encoding='utf-8') as f:
            for ligne in f:
                if "numero:" in ligne and "accompagnateur:" in ligne:
                    partie_numero, partie_acc = ligne.split("accompagnateur:")
                    base_connaissance[int(partie_numero.replace("numero:", "").strip())] = set(nettoyer_numeros_str(partie_acc))
        return base_connaissance
    except Exception as e:
        print(f"-> Erreur lecture base connaissance: {e}")
        return None

def lire_tirages_enrichis(nom_fichier):
    tirages = []
    if not os.path.exists(nom_fichier):
        print(f"-> Fichier historique non trouvé: {nom_fichier}")
        return None
    try:
        with open(nom_fichier, mode='r', encoding='utf-8-sig') as f:
            for ligne in csv.DictReader(f):
                date_str = ligne.get("date_complete")
                if not date_str: continue
                try:
                    date_obj = pd.to_datetime(date_str, format='mixed', dayfirst=True).to_pydatetime()
                except (ValueError, TypeError): continue
                gagnants = nettoyer_numeros_str(ligne.get("numeros_gagnants"))
                machine = nettoyer_numeros_str(ligne.get("numeros_machine"))
                numeros_sortis = set(gagnants + machine)
                if not numeros_sortis: continue
                tirages.append({
                    "date_obj": date_obj, "nom_du_tirage": ligne.get("nom_du_tirage"),
                    "gagnants": gagnants, "machine": machine, "numeros_sortis": list(numeros_sortis)
                })
        tirages.sort(key=lambda x: x['date_obj'])
        return tirages
    except Exception as e:
        print(f"-> Erreur lecture historique: {e}")
        return None

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
    try:
        # Sur Render, les secrets sont dans les variables d'environnement
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            # Si la clé n'est pas dans l'environnement, essayer le fichier .env local
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.getenv("GOOGLE_API_KEY")

        if not api_key:
            return "ERREUR : Clé d'API GOOGLE_API_KEY non trouvée."
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Erreur API Gemini: {e}"

# --- LA FONCTION PRINCIPALE QUE L'ON VA IMPORTER ---
def lancer_analyse_complete():
    """Exécute tout le pipeline d'analyse et retourne les résultats."""
    print("--- Lancement de l'analyse complète (version web) ---")
    
    base_connaissance = lire_base_connaissance(NOM_FICHIER_BASE_CONNAISSANCE)
    tous_les_tirages = lire_tirages_enrichis(NOM_FICHIER_DONNEES)
    
    if not tous_les_tirages:
        return {"erreur": "Le chargement des tirages a échoué. Lancez une mise à jour des données."}

    rapport_rgntc = analyser_relations_rgntc(tous_les_tirages)
    forme_ecart_data = calculer_forme_et_ecart(tous_les_tirages)
    affinites_temporelles = analyser_affinites_temporelles(tous_les_tirages, datetime.now().date())
    
    dernier_tirage = tous_les_tirages[-1]
    gagnants_str = ",".join(map(str, dernier_tirage.get('gagnants', [])))
    machine_str = ",".join(map(str, dernier_tirage.get('machine', [])))
    contexte_str = f"{dernier_tirage['date_obj'].strftime('%d/%m/%Y %H:%M')},{dernier_tirage['nom_du_tirage']},\"{gagnants_str}\",\"{machine_str}\""

    if IA_DISPONIBLE:
        prompt = generer_prompt_final_pour_ia(dernier_tirage, rapport_rgntc, forme_ecart_data, base_connaissance, affinites_temporelles)
        reponse_ia = appeler_ia_gemini(prompt)
    else:
        reponse_ia = "Module IA (google-generativeai) non disponible ou clé d'API manquante."

    return {
        "contexte": contexte_str,
        "reponse_ia": reponse_ia,
        "erreur": None
    }