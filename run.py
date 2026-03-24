from app import app, inicializar_banco
import os

if __name__ == '__main__':
    inicializar_banco()
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug)