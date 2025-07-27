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

# --- FONCTION GARANTISSANT LA CONNEXION À FIREBASE ---
def get_db():
    """
    Initialise Firebase si ce n'est pas déjà fait et retourne le client de la base de données.
    C'est la méthode la plus robuste.
    """
    if not firebase_admin._apps:
        print("Tentative d'initialisation de Firebase...")
        try:
            if SECRETS_DISPONIBLES and hasattr(settings, 'FIREBASE_SERVICE_ACCOUNT_DICT'):
                cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_DICT)
                firebase_admin.initialize_app(cred)
                print("✅ Connexion à Firebase réussie via settings.py.")
            else:
                raise ValueError("Fichier settings.py ou secrets non trouvés.")
        except Exception as e:
            print(f"❌ ERREUR CRITIQUE : Impossible d'initialiser Firebase. {e}")
            return None # Retourne None si l'initialisation échoue
    
    return firestore.client()

# --- ROUTES DE L'APPLICATION ---
@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user_uid' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        db = get_db() # On s'assure que la connexion est active
        if not db:
            flash("Erreur serveur : la base de données n'est pas disponible.", "error")
            return render_template('login.html')

        email = request.form['email']
        password = request.form['password']
        try:
            user = auth.get_user_by_email(email)
            session['user_uid'] = user.uid
            session['user_email'] = user.email
            
            user_role_doc = db.collection('users').document(user.uid).get()
            session['is_admin'] = user_role_doc.exists and user_role_doc.to_dict().get('role') == 'admin'

            return redirect(url_for('dashboard'))
        except auth.UserNotFoundError:
            flash("Utilisateur non trouvé. Veuillez vérifier votre email.", "error")
        except Exception as e:
            flash(f"Une erreur est survenue lors de la connexion : {e}", "error")
            
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_uid' not in session: return redirect(url_for('login'))
    return render_template('dashboard.html', user_email=session.get('user_email'), is_admin=session.get('is_admin', False))

@app.route('/analyser', methods=['POST'])
def analyser():
    if 'user_uid' not in session: return redirect(url_for('login'))
    resultats = lancer_analyse_complete()
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

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5001)