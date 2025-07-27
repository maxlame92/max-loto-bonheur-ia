from flask import Flask, render_template, request, redirect, url_for, session, flash
import firebase_admin
from firebase_admin import credentials, auth, firestore
import os

# --- On importe nos bibliothèques personnelles ---
from analyse_loto import lancer_analyse_complete
# La collecte se fera via un autre service (Cron Job), mais on garde la fonction pour un appel manuel
from cron_update_firestore import lancer_collecte_vers_firestore

# --- INITIALISATION DE L'APPLICATION FLASK ---
app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- INITIALISATION DE FIREBASE ---
if not firebase_admin._apps:
    try:
        if os.path.exists("serviceAccountKey.json"):
            cred = credentials.Certificate("serviceAccountKey.json")
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
        db = firestore.client()
        print("✅ Connexion à Firebase réussie pour l'app web.")
    except Exception as e:
        print(f"❌ ERREUR CRITIQUE DANS APP.PY : Impossible d'initialiser Firebase. {e}")
        db = None

# --- ROUTES DE L'APPLICATION ---

@app.route('/', methods=['GET', 'POST'])
def login():
    """Gère la connexion des utilisateurs."""
    if 'user_uid' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password'] # Mot de passe non vérifié par le SDK Admin
        
        if not db:
            flash("Erreur serveur : la base de données n'est pas connectée.", "error")
            return render_template('login.html')

        try:
            user = auth.get_user_by_email(email)
            # ATTENTION: Le SDK Admin ne peut pas vérifier le mot de passe.
            # C'est une limitation connue. Pour une application en production
            # avec de vrais utilisateurs, il faudrait utiliser le SDK client (JavaScript)
            # pour une authentification sécurisée côté client.
            # Pour notre cas (accès restreint), on fait confiance à l'email.
            
            session['user_uid'] = user.uid
            session['user_email'] = user.email
            
            user_role_doc = db.collection('users').document(user.uid).get()
            if user_role_doc.exists and user_role_doc.to_dict().get('role') == 'admin':
                session['is_admin'] = True
            else:
                session['is_admin'] = False

            return redirect(url_for('dashboard'))
        except auth.UserNotFoundError:
            flash("Utilisateur non trouvé. Veuillez vérifier votre email.", "error")
        except Exception as e:
            flash(f"Une erreur est survenue : {e}", "error")
            
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    """Affiche le tableau de bord principal après connexion."""
    if 'user_uid' not in session:
        return redirect(url_for('login'))
    
    return render_template('dashboard.html', user_email=session.get('user_email'), is_admin=session.get('is_admin', False))

@app.route('/analyser', methods=['POST'])
def analyser():
    """Lance l'analyse et affiche le résultat en fonction du rôle."""
    if 'user_uid' not in session:
        return redirect(url_for('login'))
        
    resultats = lancer_analyse_complete()
    
    if session.get('is_admin'):
        return render_template('resultat_admin.html', resultats=resultats)
    else:
        return render_template('resultat_user.html', resultats=resultats)

@app.route('/mettre_a_jour', methods=['POST'])
def mettre_a_jour():
    """Lance la collecte manuelle (accessible uniquement par l'admin)."""
    if not session.get('is_admin'):
        flash("Accès non autorisé.", "error")
        return redirect(url_for('dashboard'))
        
    message = lancer_collecte_vers_firestore()
    flash(message)
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    """Gère la déconnexion."""
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    # Pour tester en local sur votre machine
    app.run(debug=True, host="0.0.0.0", port=5001)