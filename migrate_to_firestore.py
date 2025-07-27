import firebase_admin
from firebase_admin import credentials, firestore
import csv
import pandas as pd
import os

# --- CONFIGURATION ---
NOM_FICHIER_DONNEES_CSV = "resultats_loto_bonheur_COMPLET.csv"
NOM_FICHIER_BASE_CONNAISSANCE = "base de numero et cest accompagne.txt"
NOM_CLE_SERVICE = "serviceAccountKey.json"

# --- FONCTIONS UTILITAIRES ---
def nettoyer_numeros_str(numeros_str):
    if not isinstance(numeros_str, str): return []
    return [int(n.strip()) for n in numeros_str.split(',') if n.strip().isdigit()]

# --- INITIALISATION DE FIREBASE ---
try:
    cred = credentials.Certificate(NOM_CLE_SERVICE)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Connexion à Firebase réussie.")
except Exception as e:
    print(f"❌ ERREUR : Impossible de se connecter à Firebase. Vérifiez le fichier '{NOM_CLE_SERVICE}'. Erreur : {e}")
    exit()

def migrer_tirages():
    """Lit le fichier CSV et envoie chaque tirage vers Firestore par lots."""
    print(f"\n--- Démarrage de la migration des tirages ---")
    collection_ref = db.collection('tirages')
    batch = db.batch()
    compteur_total = 0
    compteur_lot = 0
    try:
        with open(NOM_FICHIER_DONNEES_CSV, mode='r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                try:
                    date_obj = pd.to_datetime(row['date_complete'], format='mixed', dayfirst=True).to_pydatetime()
                    doc_id = date_obj.strftime('%Y%m%d%H%M') + "_" + row['nom_du_tirage'].replace(' ', '')
                    doc_data = {
                        'date_obj': date_obj,
                        'nom_du_tirage': row['nom_du_tirage'],
                        'gagnants': nettoyer_numeros_str(row.get('numeros_gagnants')),
                        'machine': nettoyer_numeros_str(row.get('numeros_machine'))
                    }
                    doc_ref = collection_ref.document(doc_id)
                    batch.set(doc_ref, doc_data)
                    compteur_total += 1
                    compteur_lot += 1
                    if compteur_lot >= 499:
                        print(f"   -> Envoi d'un lot de {compteur_lot} documents...")
                        batch.commit()
                        batch = db.batch()
                        compteur_lot = 0
                except (ValueError, TypeError): continue
        if compteur_lot > 0:
            print(f"   -> Envoi du dernier lot de {compteur_lot} documents...")
            batch.commit()
        print(f"\n✅ Migration des tirages terminée. {compteur_total} documents ajoutés à 'tirages'.")
    except FileNotFoundError:
        print(f"❌ Erreur : Le fichier '{NOM_FICHIER_DONNEES_CSV}' n'a pas été trouvé.")
    except Exception as e:
        print(f"❌ Une erreur est survenue pendant la migration : {e}")

def migrer_base_connaissance():
    """Lit le fichier de connaissance et l'envoie vers Firestore."""
    print(f"\n--- Démarrage de la migration de la base de connaissance ---")
    collection_ref = db.collection('connaissance')
    compteur = 0
    try:
        with open(NOM_FICHIER_BASE_CONNAISSANCE, mode='r', encoding='utf-8') as f:
            for ligne in f:
                if "numero:" in ligne and "accompagnateur:" in ligne:
                    try:
                        partie_numero, partie_acc = ligne.split("accompagnateur:")
                        numero_cle = int(partie_numero.replace("numero:", "").strip())
                        accompagnateurs = nettoyer_numeros_str(partie_acc)
                        doc_ref = collection_ref.document(str(numero_cle))
                        doc_ref.set({"accompagnateurs": accompagnateurs})
                        compteur += 1
                    except (ValueError, IndexError): continue
        print(f"\n✅ Migration de la base de connaissance terminée. {compteur} documents ajoutés à 'connaissance'.")
    except FileNotFoundError:
        print(f"❌ Erreur : Le fichier '{NOM_FICHIER_BASE_CONNAISSANCE}' n'a pas été trouvé.")
    except Exception as e:
        print(f"❌ Une erreur est survenue : {e}")

if __name__ == "__main__":
    migrer_tirages()
    migrer_base_connaissance()