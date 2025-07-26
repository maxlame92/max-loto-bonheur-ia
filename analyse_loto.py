# -*- coding: utf-8 -*-

import csv
from collections import defaultdict, Counter
import time
import json
import os
from datetime import datetime
import pandas as pd
import re

# --- Imports pour la visualisation et l'IA ---
try:
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

# --- CONFIGURATIONS ET PARAMÈTRES ---
NOM_FICHIER_DONNEES = "resultats_loto_bonheur_COMPLET.csv"
NOM_FICHIER_BASE_CONNAISSANCE = "base de numero et cest accompagne.txt"

# -----------------------------------------------------------------------------
# --- PARAMÈTRES OPTIMISÉS ---
# -----------------------------------------------------------------------------
MODE_BACKTEST = False 
NOMBRE_JOURS_BACKTEST = 30 
FENETRE_RGNTC = 3
FENETRE_FORME_ECART = 50
NOMBRE_CANDIDATS_A_ANALYSER = 15
# -----------------------------------------------------------------------------

TOP_N_HEATMAP = 25

# --- FONCTIONS DE TRAITEMENT ET D'ANALYSE ---
def nettoyer_numeros_str(numeros_str):
    if not isinstance(numeros_str, str): return []
    return [int(n.strip()) for n in numeros_str.split(',') if n.strip().isdigit()]

def lire_base_connaissance(nom_fichier):
    print(f"Lecture de la base de connaissance '{nom_fichier}'...")
    base_connaissance = {}
    try:
        with open(nom_fichier, mode='r', encoding='utf-8') as f:
            for ligne in f:
                if "numero:" in ligne and "accompagnateur:" in ligne:
                    try:
                        partie_numero, partie_acc = ligne.split("accompagnateur:")
                        base_connaissance[int(partie_numero.replace("numero:", "").strip())] = set(nettoyer_numeros_str(partie_acc))
                    except (ValueError, IndexError): continue
        print(f"-> {len(base_connaissance)} règles chargées.")
        return base_connaissance
    except FileNotFoundError:
        print(f"-> ❌ Fichier non trouvé.")
        return None

def lire_tirages_enrichis(nom_fichier):
    tirages, lignes_ignorees = [], 0
    print(f"Lecture de l'historique des tirages '{nom_fichier}'...")
    try:
        with open(nom_fichier, mode='r', encoding='utf-8-sig') as f:
            for ligne in csv.DictReader(f):
                date_str = ligne.get("date_complete")
                if not date_str: lignes_ignorees += 1; continue
                try:
                    date_obj = pd.to_datetime(date_str, format='mixed', dayfirst=True).to_pydatetime()
                except (ValueError, TypeError):
                    lignes_ignorees += 1; continue
                gagnants = nettoyer_numeros_str(ligne.get("numeros_gagnants"))
                machine = nettoyer_numeros_str(ligne.get("numeros_machine"))
                numeros_sortis = set(gagnants + machine)
                if not numeros_sortis:
                    lignes_ignorees += 1; continue
                tirages.append({
                    "date_obj": date_obj, "nom_du_tirage": ligne.get("nom_du_tirage"),
                    "gagnants": gagnants, "machine": machine, "numeros_sortis": list(numeros_sortis)
                })
        tirages.sort(key=lambda x: x['date_obj'])
        print(f"-> {len(tirages)} tirages valides chargés et triés.")
        if lignes_ignorees: print(f"   ({lignes_ignorees} lignes ignorées).")
        return tirages
    except FileNotFoundError: print(f"-> ❌ Fichier non trouvé."); return None
    except Exception as e: print(f"-> ❌ Erreur critique : {e}"); return None

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
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key: return "❌ ERREUR : Clé d'API non trouvée."
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"❌ Erreur API : {e}"

def extraire_predictions_de_reponse(texte_ia):
    try:
        match = re.search(r'(?:Prédiction Finale|sont|numéros\s*:\s*)\s*(\d{1,2})\s*(?:et|,|puis)\s*(\d{1,2})', texte_ia, re.IGNORECASE)
        if match: return [int(match.group(1)), int(match.group(2))]
        numeros_gras = re.findall(r'\*\*(\d{1,2})\*\*', texte_ia)
        if len(numeros_gras) >= 2: return [int(n) for n in numeros_gras[:2]]
        numeros = re.findall(r'\b(\d{1,2})\b', texte_ia)
        if len(numeros) >= 2: return [int(n) for n in numeros[-2:]]
    except Exception: pass
    return []

def lancer_backtest(tous_les_tirages, base_connaissance, nombre_jours):
    # ... (code du backtest, inchangé)
    print("\n" + "="*60); print(f"--- 🚀 LANCEMENT DU BACKTESTING SUR {nombre_jours} JOURS 🚀 ---"); print("="*60)
    
    dates_uniques = sorted(list(set(t['date_obj'].date() for t in tous_les_tirages)))
    if len(dates_uniques) <= nombre_jours:
        print("❌ Erreur : Pas assez de jours de données pour effectuer le backtest."); return

    succes_total, jours_testes = 0, 0
    start_index = len(dates_uniques) - nombre_jours - 1
    
    for i in range(start_index, len(dates_uniques) - 1):
        jours_testes += 1
        date_veille, date_cible = dates_uniques[i], dates_uniques[i+1]
        
        print(f"\n--- JOUR DE TEST {jours_testes}/{nombre_jours} | Prédiction pour le : {date_cible.strftime('%d/%m/%Y')} ---")

        donnees_historiques = [t for t in tous_les_tirages if t['date_obj'].date() <= date_veille]
        if not donnees_historiques: continue
        dernier_tirage = donnees_historiques[-1]

        rapport_rgntc = analyser_relations_rgntc(donnees_historiques)
        forme_ecart_data = calculer_forme_et_ecart(donnees_historiques)
        affinites_temporelles = analyser_affinites_temporelles(donnees_historiques, date_cible)
        
        print("   - Génération du prompt et appel de l'IA...")
        prompt = generer_prompt_final_pour_ia(dernier_tirage, rapport_rgntc, forme_ecart_data, base_connaissance, affinites_temporelles)
        reponse_ia = appeler_ia_gemini(prompt)
        numeros_predits = extraire_predictions_de_reponse(reponse_ia)
        
        if not numeros_predits:
            print("   - ⚠️ Impossible d'extraire la prédiction de la réponse de l'IA."); continue

        tirages_du_jour_cible = [t['numeros_sortis'] for t in tous_les_tirages if t['date_obj'].date() == date_cible]
        numeros_gagnants_du_jour = set(num for tirage in tirages_du_jour_cible for num in tirage)

        print(f"   - Prédiction IA : {numeros_predits} | Vrais numéros du jour : {sorted(list(numeros_gagnants_du_jour))}")

        succes = any(num_predit in numeros_gagnants_du_jour for num_predit in numeros_predits)
        
        if succes:
            succes_total += 1
            print("   - ✅ RÉSULTAT : SUCCÈS !")
        else:
            print("   - ❌ RÉSULTAT : ÉCHEC")
        time.sleep(2)

    print("\n" + "="*60); print("--- 📊 RAPPORT FINAL DU BACKTESTING 📊 ---"); print(f"Période de test : {jours_testes} jours")
    print(f"Nombre de succès (au moins 1 bon numéro) : {succes_total}")
    if jours_testes > 0:
        print(f"Taux de réussite : {(succes_total / jours_testes) * 100:.2f}%")
    print("="*60)

# --- FONCTION DE VISUALISATION CORRIGÉE ---
def visualiser_heatmap(rapport_rgntc, freqs_triees, type_relation):
    if not VISUALISATION_DISPONIBLE: return
    print(f"-> Génération de la Heatmap pour les '{type_relation.capitalize()}'...")
    top_nums = [n for n, f in freqs_triees[:TOP_N_HEATMAP]]
    matrice = pd.DataFrame(0, index=top_nums, columns=top_nums, dtype=int)
    for n1 in top_nums: # La boucle extérieure définit n1
        if n1 in rapport_rgntc:
            for n2, freq in rapport_rgntc[n1][type_relation]:
                if n2 in top_nums:
                    if type_relation == 'compagnons':
                        matrice.loc[n1, n2] = freq
                        matrice.loc[n2, n1] = freq
                    else:
                        # --- CORRECTION ICI ---
                        # On utilise bien n1 (défini par la boucle) et n2
                        matrice.loc[n1, n2] = freq
                        # --- FIN DE LA CORRECTION ---
    plt.figure(figsize=(18, 15))
    sns.heatmap(matrice, annot=True, cmap="viridis", fmt="d", linewidths=.5)
    plt.title(f"Heatmap des {type_relation.capitalize()} des {TOP_N_HEATMAP} Numéros", fontsize=16)
    plt.show(block=False)


# --- PROGRAMME PRINCIPAL ---
if __name__ == "__main__":
    
    if MODE_BACKTEST:
        # ... (code du mode backtest inchangé)
        print("\n" + "="*60); print("--- MODE BACKTESTING ACTIVÉ ---"); print("="*60)
        base_connaissance_statique = lire_base_connaissance(NOM_FICHIER_BASE_CONNAISSANCE)
        tous_les_tirages = lire_tirages_enrichis(NOM_FICHIER_DONNEES)
        if tous_les_tirages and IA_DISPONIBLE:
            lancer_backtest(tous_les_tirages, base_connaissance_statique, NOMBRE_JOURS_BACKTEST)
        elif not IA_DISPONIBLE:
            print("\n❌ ERREUR : Le mode Backtest nécessite le module IA.")
    else:
        print("\n" + "="*60); print("--- MODE PRÉDICTION UNIQUE ACTIVÉ ---"); print("="*60)
        print("\n--- ÉTAPE 1: CHARGEMENT DES DONNÉES ---")
        base_connaissance_statique = lire_base_connaissance(NOM_FICHIER_BASE_CONNAISSANCE)
        tous_les_tirages = lire_tirages_enrichis(NOM_FICHIER_DONNEES) 
        if tous_les_tirages:
            print("\n--- ÉTAPE 2: ANALYSE STATISTIQUE ---")
            rapport_rgntc = analyser_relations_rgntc(tous_les_tirages)
            forme_ecart_data = calculer_forme_et_ecart(tous_les_tirages)
            affinites_temporelles = analyser_affinites_temporelles(tous_les_tirages, datetime.now().date())
            print("-> Analyses terminées.")
            
            if rapport_rgntc:
                dernier_tirage = tous_les_tirages[-1]
                print("\n--- ÉTAPE 3: PRÉDICTION PAR IA ---")
                gagnants_str = ",".join(map(str, dernier_tirage.get('gagnants', []))); machine_str = ",".join(map(str, dernier_tirage.get('machine', [])))
                print(f"Analyse basée sur le dernier tirage connu :\n{dernier_tirage['date_obj'].strftime('%d/%m/%Y %H:%M')},{dernier_tirage['nom_du_tirage']},\"{gagnants_str}\",\"{machine_str}\"")

                if IA_DISPONIBLE:
                    start_time = time.time()
                    prompt = generer_prompt_final_pour_ia(dernier_tirage, rapport_rgntc, forme_ecart_data, base_connaissance_statique, affinites_temporelles)
                    reponse = appeler_ia_gemini(prompt)
                    end_time = time.time()
                    print(f"Connexion à l'API Google AI (Gemini)...")
                    print(f"-> Réponse reçue en {end_time - start_time:.2f} secondes.")
                    print("\n" + "-"*15 + " 🧠 ANALYSE DE L'IA 🧠 " + "-"*15); print(reponse); print("-" * 60)
                else:
                    print("\nModule IA non installé.")

                if VISUALISATION_DISPONIBLE:
                    print("\n--- ÉTAPE 4: VISUALISATIONS (HEATMAPS) ---")
                    freq_globale = Counter(num for t in tous_les_tirages for num in t['numeros_sortis'])
                    freqs_triees = freq_globale.most_common()
                    visualiser_heatmap(rapport_rgntc, freqs_triees, 'compagnons')
                    visualiser_heatmap(rapport_rgntc, freqs_triees, 'suiveurs')
                    visualiser_heatmap(rapport_rgntc, freqs_triees, 'precurseurs')
                    print("\n-> Fermez TOUTES les fenêtres de graphiques pour terminer."); plt.show()
        else:
            print("\nLe chargement des tirages a échoué.")