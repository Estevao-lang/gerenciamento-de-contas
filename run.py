from app import app, inicializar_banco

if __name__ == '__main__':
    inicializar_banco()
    app.run(debug=True)