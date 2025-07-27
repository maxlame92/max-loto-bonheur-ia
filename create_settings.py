import os
import json

print("Génération du fichier settings.py à partir des variables d'environnement...")

# Récupérer les secrets depuis l'environnement de Render
google_api_key = os.environ.get("GOOGLE_API_KEY", "")
firebase_creds_json_str = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON", "{}")

# Préparer le contenu du fichier Python
# Cette structure garantit que le fichier sera syntaxiquement correct
settings_content = f"""
# Fichier généré automatiquement au démarrage du serveur. NE PAS MODIFIER.

GOOGLE_API_KEY = "{google_api_key}"

FIREBASE_SERVICE_ACCOUNT_DICT = {firebase_creds_json_str}
""" # <-- LE GUILLEMET TRIPLE MANQUANT A ÉTÉ AJOUTÉ ICI

try:
    with open("settings.py", "w", encoding='utf-8') as f:
        f.write(settings_content)
    print("Fichier settings.py créé avec succès.")
except Exception as e:
    print(f"Erreur lors de la création de settings.py : {e}")