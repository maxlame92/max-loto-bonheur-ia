from flask import Flask, render_template, request, redirect, url_for, session, flash
import firebase_admin
from firebase_admin import credentials, auth, firestore
import os
import json

# --- On importe nos bibliothèques personnelles ---
from analyse_loto import lancer_analyse_complete
from cron_update_firestore import lancer_collecte_vers_firestore

# --- On importe les secrets ---
try:
    import settings
    SECRETS_DISPONIBLES = True
except ImportError:
    SECRETS_DISPONIBLES = False

# --- INITIALISATION DE L'APPLICATION FLASK ---
app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- INITIALISATION DE FIREBASE (une seule fois, au démarrage de l'app) ---
db = None
try:
    if SECRETS_DISPONIBLES:
        cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_DICT)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ [APP] Connexion à Firebase réussie au démarrage.")
    else:
        raise ValueError("Fichier settings.py manquant ou invalide.")
except Exception as e:
    print(f"❌ [APP] ERREUR CRITIQUE AU DÉMARRAGE : Impossible d'initialiser Firebase. {e}")


# --- ROUTES DE L'APPLICATION ---
@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user_uid' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        if not db:
            flash("Erreur serveur : la base de données n'est pas connectée.", "error")
            return render_template('login.html')
        email = request.form['email']
        try:
            user = auth.get_user_by_email(email)
            session['user_uid'] = user.uid
            session['user_email'] = user.email
            
            # --- DÉBUT DU BLOC DE DIAGNOSTIC ---
            print("\n--- DIAGNOSTIC DU RÔLE UTILISATEUR ---")
            print(f"Email de l'utilisateur qui se connecte : {user.email}")
            print(f"UID de l'utilisateur authentifié : {user.uid}")
            
            user_role_doc_ref = db.collection('users').document(user.uid)
            print(f"Recherche du document dans Firestore à l'adresse : users/{user.uid}")
            user_role_doc = user_role_doc_ref.get()

            if user_role_doc.exists:
                print(">>> DOCUMENT TROUVÉ DANS FIRESTORE.")
                doc_data = user_role_doc.to_dict()
                print(f"    Contenu du document : {doc_data}")
                user_role = doc_data.get('role')
                print(f"    Valeur du champ 'role' lue : '{user_role}' (Type: {type(user_role)})")
                
                if user_role == 'admin':
                    session['is_admin'] = True
                    print(">>> SUCCÈS : Le rôle est 'admin'. Session admin activée.")
                else:
                    session['is_admin'] = False
                    print(">>> ÉCHEC : Le rôle trouvé n'est pas 'admin'.")
            else:
                print(">>> ÉCHEC : AUCUN document trouvé dans Firestore avec cet UID.")
                session['is_admin'] = False
            print("--- FIN DU DIAGNOSTIC ---\n")
            # --- FIN DU BLOC DE DIAGNOSTIC ---

            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f"Erreur de connexion : {e}", "error")
            print(f"ERREUR EXCEPTION PENDANT LE LOGIN : {e}")

    return render_template('login.html')

# (Les autres routes restent les mêmes)
@app.route('/dashboard')
def dashboard():
    if 'user_uid' not in session: return redirect(url_for('login'))
    return render_template('dashboard.html', user_email=session.get('user_email'), is_admin=session.get('is_admin', False))

@app.route('/analyser', methods=['POST'])
def analyser():
    if 'user_uid' not in session: return redirect(url_for('login'))
    resultats = lancer_analyse_complete(db)
    if session.get('is_admin'):
        return render_template('resultat_admin.html', resultats=resultats)
    else:
        return render_template('resultat_user.html', resultats=resultats)

@app.route('/mettre_a_jour', methods=['POST'])
def mettre_a_jour():
    if not session.get('is_admin'):
        flash("Accès non autorisé.", "error"); return redirect(url_for('dashboard'))
    message = lancer_collecte_vers_firestore()
    flash(message); return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))