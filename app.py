from flask import Flask, render_template, redirect, url_for, flash
import os

# On importe nos nouvelles fonctions "bibliothèque"
from analyse_loto import lancer_analyse_complete
from collect_and_update import lancer_collecte

app = Flask(__name__)
# Une clé secrète est nécessaire pour afficher des messages
app.secret_key = os.urandom(24)

@app.route('/')
def index():
    """Affiche la page d'accueil."""
    return render_template('index.html')

@app.route('/analyser', methods=['POST'])
def analyser():
    """Appelle la logique d'analyse et affiche les résultats."""
    print("Demande d'analyse reçue...")
    resultats = lancer_analyse_complete()
    return render_template('resultat.html', resultats=resultats)

@app.route('/mettre_a_jour', methods=['POST'])
def mettre_a_jour():
    """Appelle le script de collecte de données."""
    print("Demande de mise à jour reçue...")
    message = lancer_collecte()
    flash(message) # Prépare un message à afficher
    return redirect(url_for('index')) # Redirige vers la page d'accueil

if __name__ == '__main__':
    app.run()