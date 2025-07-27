from flask import Flask, render_template, request, redirect, url_for, session, flash
import os

# --- On importe nos bibliothèques personnelles ---
# On importe aussi la fonction d'initialisation de l'un des modules
from analyse_loto import lancer_analyse_complete, init_firestore as init_analyse
from cron_update_firestore import lancer_collecte_vers_firestore

# --- INITIALISATION DE L'APPLICATION FLASK ---
app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- ROUTES DE L'APPLICATION ---
@app.route('/', methods=['GET', 'POST'])
def login():
    """Gère la connexion des utilisateurs."""
    if 'user_uid' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        # --- CORRECTION APPLIQUÉE ICI ---
        # On s'assure que Firebase est initialisé AVANT d'utiliser 'auth'
        if not init_analyse():
            flash("Erreur critique du serveur : Impossible d'initialiser Firebase.", "error")
            return render_template('login.html')
        # --- FIN DE LA CORRECTION ---
        
        from firebase_admin import auth, firestore
        db = firestore.client()

        email = request.form['email']
        password = request.form['password']

        try:
            user = auth.get_user_by_email(email)
            # Pour notre cas, on fait confiance à l'email pour la connexion.
            
            session['user_uid'] = user.uid
            session['user_email'] = user.email
            
            user_role_doc = db.collection('users').document(user.uid).get()
            session['is_admin'] = user_role_doc.exists and user_role_doc.to_dict().get('role') == 'admin'

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
    if 'user_uid' not in session: return redirect(url_for('login'))
    resultats = lancer_analyse_complete()
    if session.get('is_admin'):
        return render_template('resultat_admin.html', resultats=resultats)
    else:
        return render_template('resultat_user.html', resultats=resultats)

@app.route('/mettre_a_jour', methods=['POST'])
def mettre_a_jour():
    """Lance la collecte manuelle (accessible uniquement par l'admin)."""
    if not session.get('is_admin'):
        flash("Accès non autorisé.", "error"); return redirect(url_for('dashboard'))
    message = lancer_collecte_vers_firestore()
    flash(message); return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    """Gère la déconnexion."""
    session.clear(); return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5001)