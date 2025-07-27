from flask import Flask, render_template, request, redirect, url_for, session, flash
import firebase_admin
from firebase_admin import credentials, auth, firestore
import os
import json

# --- On importe les secrets ---
try:
    import settings
    SECRETS_DISPONIBLES = True
except ImportError:
    SECRETS_DISPONIBLES = False

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- INITIALISATION DE FIREBASE (tentative au démarrage de l'app) ---
db = None
try:
    if SECRETS_DISPONIBLES and hasattr(settings, 'FIREBASE_SERVICE_ACCOUNT_DICT'):
        cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_DICT)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ TEST FIREBASE APP.PY : Connexion à Firebase réussie au démarrage.")
    else:
        print("❌ TEST FIREBASE APP.PY : Fichier settings.py ou secrets non trouvés.")
        db = None # Force db à None si les secrets manquent
except Exception as e:
    print(f"❌ ERREUR CRITIQUE DANS APP.PY : Impossible d'initialiser Firebase. {e}")
    db = None


# --- ROUTES DE L'APPLICATION ---
@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user_uid' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        # Pas besoin d'initialiser ici, on a déjà fait la tentative au démarrage
        if not db: # Si db est toujours None, c'est que l'initialisation a échoué
            flash("Erreur serveur : La connexion à Firebase a échoué au démarrage. Contactez l'administrateur.", "error")
            return render_template('login.html')

        try:
            # Vérifie juste si l'utilisateur existe dans Authentication
            user = auth.get_user_by_email(email)
            
            # Ici, on ne s'occupe plus du rôle pour l'instant, juste de savoir si l'authentification marche
            session['user_uid'] = user.uid
            session['user_email'] = user.email
            session['is_admin'] = False # On met False par défaut pour l'instant

            return redirect(url_for('dashboard'))
        except auth.UserNotFoundError:
            flash("Utilisateur non trouvé. Vérifiez l'email.", "error")
        except Exception as e:
            flash(f"Une erreur est survenue lors de la connexion : {e}", "error")
            
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_uid' not in session: return redirect(url_for('login'))
    return render_template('dashboard.html', user_email=session.get('user_email'), is_admin=session.get('is_admin', False))

@app.route('/analyser', methods=['POST'])
def analyser():
    flash("L'analyse est désactivée pour le diagnostic.", "info")
    return redirect(url_for('dashboard')) # Désactive l'analyse pour le diagnostic

@app.route('/mettre_a_jour', methods=['POST'])
def mettre_a_jour():
    flash("La mise à jour est désactivée pour le diagnostic.", "info")
    return redirect(url_for('dashboard')) # Désactive la mise à jour

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5001)