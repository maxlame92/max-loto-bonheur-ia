from flask import Flask, render_template, request, redirect, url_for, session, flash
import firebase_admin
from firebase_admin import credentials, auth, firestore
import os

# --- On importe nos bibliothèques personnelles ---
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

# --- INITIALISATION DE L'APPLICATION FLASK ---
app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- INITIALISATION DE FIREBASE (ne se fait qu'une fois) ---
db = None
if not firebase_admin._apps:
    try:
        # La connexion est gérée par les scripts importés au moment de leur appel
        print("L'initialisation de Firebase sera faite par les modules au besoin.")
    except Exception as e:
        print(f"Problème de configuration Firebase initial : {e}")

# --- ROUTES DE L'APPLICATION ---
@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user_uid' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password'] # Mot de passe non vérifié par le SDK Admin
        try:
            user = auth.get_user_by_email(email)
            session['user_uid'] = user.uid
            session['user_email'] = user.email
            
            if db is None: # S'assurer que db est initialisé
                from analyse_loto import init_firestore
                init_firestore()
            
            user_role_doc = db.collection('users').document(user.uid).get()
            session['is_admin'] = user_role_doc.exists and user_role_doc.to_dict().get('role') == 'admin'
            
            return redirect(url_for('dashboard'))
        except auth.UserNotFoundError:
            flash("Utilisateur non trouvé.", "error")
        except Exception as e:
            flash(f"Une erreur est survenue lors de la connexion : {e}", "error")
            
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_uid' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', user_email=session.get('user_email'), is_admin=session.get('is_admin', False))

@app.route('/analyser', methods=['POST'])
def analyser():
    if 'user_uid' not in session: return redirect(url_for('login'))
    if not MODULES_DISPONIBLES:
        flash("Erreur serveur : le module d'analyse est manquant.", "error"); return redirect(url_for('dashboard'))
    resultats = lancer_analyse_complete()
    if session.get('is_admin'):
        return render_template('resultat_admin.html', resultats=resultats)
    else:
        return render_template('resultat_user.html', resultats=resultats)

@app.route('/mettre_a_jour', methods=['POST'])
def mettre_a_jour():
    if not session.get('is_admin'):
        flash("Accès non autorisé.", "error"); return redirect(url_for('dashboard'))
    if not MODULES_DISPONIBLES:
        flash("Erreur serveur : le module de collecte est manquant.", "error"); return redirect(url_for('dashboard'))
    message = lancer_collecte_vers_firestore()
    flash(message); return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5001)