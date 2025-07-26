from flask import Flask, render_template
import os

# Importez vos propres fonctions d'analyse
# (Nous les ajouterons plus tard. Pour l'instant, on veut juste que ça marche.)

app = Flask(__name__)

@app.route('/')
def index():
    """Affiche la page d'accueil."""
    # Pour l'instant, on affiche une page simple.
    return "<h1>Bonjour, mon application Loto est en ligne !</h1>"

if __name__ == '__main__':
    # Le port est défini par Render, pas besoin de le spécifier ici.
    app.run()