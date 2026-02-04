# OneInBox — By One4all

OneInBox es un programa de inbox unificado multiplataforma (estilo WhatsApp/Instagram/Facebook).
Incluye una UI simple y una API JSON para ver/enviar mensajes, además de respuestas automáticas básicas.

## Descripción del flujo
El usuario envía un mensaje desde la interfaz. Ese mensaje llega al backend,
donde se procesa el contenido y se determina la intención, con esto se genera una respuesta automática.
La respuesta se envía al frontend y se muestra al usuario nuevamente.

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
