from flask import Flask, render_template, request, redirect, url_for, session, flash
import firebase_admin
from firebase_admin import credentials, auth, firestore
import os
import json

# --- On importe nos bibliothèques personnelles ---
# On s'assure que les fichiers existent avant de les importer
try:
    from analyse_loto import lancer_analyse_complete
    from cron_update_firestore import lancer_collecte_vers_firestore
    MODULES_DISPONIBLES = True
except ImportError as e:
    print(f"Erreur d'importation des modules locaux : {e}")
    MODULES_DISPONIBLES = False

# --- On importe les secrets ---
try:
    import settings
    SECRETS_DISPONIBLES = True
except ImportError:
    SECRETS_DISPONIBLES = False
    print("Avertissement : Fichier settings.py non trouvé.")

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
        raise ValueError("Fichier settings.py manquant ou invalide. L'application ne peut pas démarrer.")
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
        password = request.form['password'] # Mot de passe non vérifié par le SDK Admin
        try:
            user = auth.get_user_by_email(email)
            session['user_uid'] = user.uid
            session['user_email'] = user.email
            user_role_doc = db.collection('users').document(user.uid).get()
            session['is_admin'] = user_role_doc.exists and user_role_doc.to_dict().get('role') == 'admin'
            return redirect(url_for('dashboard'))
        except auth.UserNotFoundError:
            flash("Utilisateur non trouvé.", "error")
        except Exception as e:
            flash(f"Erreur de connexion : {e}", "error")
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_uid' not in session: return redirect(url_for('login'))
    return render_template('dashboard.html', user_email=session.get('user_email'), is_admin=session.get('is_admin', False))

@app.route('/analyser', methods=['POST'])
def analyser():
    if 'user_uid' not in session: return redirect(url_for('login'))
    if not MODULES_DISPONIBLES:
        flash("Erreur serveur : module d'analyse manquant.", "error"); return redirect(url_for('dashboard'))
    # On passe la connexion 'db' qui a été initialisée au démarrage
    resultats = lancer_analyse_complete(db)
    if session.get('is_admin'):
        return render_template('resultat_admin.html', resultats=resultats)
    else:
        return render_template('resultat_user.html', resultats=resultats)

@app.route('/mettre_a_jour', methods=['POST'])
def mettre_a_jour():
    if not session.get('is_admin'):
        flash("Accès non autorisé.", "error"); return redirect(url_for('dashboard'))
    if not MODULES_DISPONIBLES:
        flash("Erreur serveur : module de collecte manquant.", "error"); return redirect(url_for('dashboard'))
    # La fonction de collecte gère sa propre connexion
    message = lancer_collecte_vers_firestore()
    flash(message); return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

if __name__ == '__main__':
    # Cette partie est pour tester sur votre ordinateur, pas sur Render
    app.run(debug=True, host="0.0.0.0", port=5001)