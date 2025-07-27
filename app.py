from flask import Flask, render_template, request, redirect, url_for, session, flash
import firebase_admin
from firebase_admin import credentials, auth, firestore
import os
import json

# (Le bloc d'initialisation reste le même)
# ...

app = Flask(__name__)
app.secret_key = os.urandom(24)

db = None # On le définit globalement

def init_db_if_needed():
    """Initialise la connexion si elle n'existe pas."""
    global db
    if db is None and not firebase_admin._apps:
        # ... (le même bloc d'initialisation que vous avez déjà)
        # ...
        db = firestore.client()

# --- ROUTES DE L'APPLICATION ---
@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user_uid' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        init_db_if_needed() # On s'assure que db est initialisé
        if not db:
            flash("Erreur serveur : la base de données n'est pas disponible.", "error")
            return render_template('login.html')

        email = request.form['email']
        try:
            user = auth.get_user_by_email(email)
            session['user_uid'] = user.uid
            session['user_email'] = user.email

            # --- DÉBUT DU BLOC DE DIAGNOSTIC ---
            print(f"--- DIAGNOSTIC LOGIN POUR {email} ---")
            print(f"UID de l'utilisateur authentifié : {user.uid}")
            
            user_role_doc_ref = db.collection('users').document(user.uid)
            user_role_doc = user_role_doc_ref.get()

            if user_role_doc.exists:
                print(f"Document trouvé dans Firestore pour cet UID.")
                doc_data = user_role_doc.to_dict()
                print(f"Contenu du document : {doc_data}")
                user_role = doc_data.get('role')
                print(f"Rôle trouvé dans le document : {user_role}")
                if user_role == 'admin':
                    session['is_admin'] = True
                    print("-> Rôle 'admin' confirmé. Session admin activée.")
                else:
                    session['is_admin'] = False
                    print("-> Rôle 'admin' NON trouvé. Session utilisateur normale.")
            else:
                print(f"AUCUN document trouvé dans Firestore avec l'ID : {user.uid}")
                session['is_admin'] = False
            print("--- FIN DU DIAGNOSTIC ---")
            # --- FIN DU BLOC DE DIAGNOSTIC ---
            
            return redirect(url_for('dashboard'))
        except auth.UserNotFoundError:
            flash("Utilisateur non trouvé.", "error")
        except Exception as e:
            flash(f"Une erreur est survenue : {e}", "error")
            
    return render_template('login.html')

# ... (le reste des routes : dashboard, analyser, etc. est inchangé)
# ...