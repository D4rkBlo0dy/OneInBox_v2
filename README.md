# OneInBox — By One4all

OneInBox es un programa de inbox unificado multiplataforma (estilo WhatsApp/Instagram/Facebook). Incluye una UI simple y una API JSON para ver/enviar mensajes, además de respuestas automáticas básicas.

## Funcionalidades
- Interfaz de inbox unificado 
- API REST de mensajes (`/api/messages`, `/api/send`)
- Base de datos en SQLite

## Stack
- Python + Flask
- SQLite
- HTML/CSS/JavaScript 

## Ejecutar en local
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install -r requirements.txt
python app.py
