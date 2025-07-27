import os
import json

print("Génération du fichier settings.py à partir des variables d'environnement...")

# Récupérer les secrets depuis l'environnement de Render
google_api_key = os.environ.get("GOOGLE_API_KEY", "")
firebase_creds_json_str = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON", "{}")

# Préparer le contenu du fichier Python
# Cette structure garantit que le fichier sera syntaxiquement correct
settings_content = f"""