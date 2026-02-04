from flask import Flask, jsonify, request, render_template
from dataclasses import dataclass, field
from datetime import datetime
import os, random, re, unicodedata, json, sqlite3
from typing import Dict, List, Optional, Tuple, Any

app = Flask(__name__)

# =========================
# CONFIG 
# =========================
PLATFORMS = ["whatsapp", "instagram", "facebook"]
AUTO_USER = "Atención"
MSG_CAP = 400  # limite de caracteres 

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "oneinbox.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "oneinbox_schema.sql")

def _utc_iso() -> str:
    # ISO 8601 in UTC-like format; SQLite stores TEXT
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def ensure_products() -> None:
    """Create + seed a tiny demo catalog so the bot can answer 'mochilas', 'remeras', etc.
    Idempotent: safe to call on every startup."""
    products = [
        {"name": "Mochila urbana",      "category": "mochilas", "price": 150000, "currency": "PYG", "stock": 12, "keywords": ["mochila", "urbana", "mochilas"]},
        {"name": "Mochila escolar",     "category": "mochilas", "price": 120000, "currency": "PYG", "stock": 20, "keywords": ["mochila", "escolar", "mochilas"]},
        {"name": "Remera básica",       "category": "remeras",  "price":  60000, "currency": "PYG", "stock": 30, "keywords": ["remera", "basica", "básica", "remeras"]},
        {"name": "Remera estampada",    "category": "remeras",  "price":  80000, "currency": "PYG", "stock": 15, "keywords": ["remera", "estampada", "remeras"]},
        {"name": "Calzado deportivo",   "category": "calzado",  "price": 250000, "currency": "PYG", "stock":  8, "keywords": ["calzado", "deportivo", "zapatilla", "zapatillas"]},
        {"name": "Zapatillas running",  "category": "calzado",  "price": 300000, "currency": "PYG", "stock":  5, "keywords": ["zapatillas", "running", "calzado"]},
    ]
    conn = db()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS products (
                   id            INTEGER PRIMARY KEY AUTOINCREMENT,
                   name          TEXT NOT NULL,
                   category      TEXT NOT NULL,
                   price         REAL NOT NULL,
                   currency      TEXT NOT NULL DEFAULT 'PYG',
                   stock         INTEGER NOT NULL DEFAULT 0,
                   keywords_json TEXT,
                   active        INTEGER NOT NULL DEFAULT 1,
                   created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                   updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                 );"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_products_category ON products(category);")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_products_active ON products(active);")

        row = conn.execute("SELECT COUNT(*) AS n FROM products;").fetchone()
        if int(row["n"]) == 0:
            for p in products:
                conn.execute(
                    "INSERT INTO products(name, category, price, currency, stock, keywords_json, active) VALUES (?,?,?,?,?,?,1)",
                    (p["name"], p["category"], p["price"], p["currency"], p["stock"], json.dumps(p["keywords"], ensure_ascii=False)),
                )
            conn.commit()
    finally:
        conn.close()


def init_db_if_needed() -> None:
    """Use bundled DB when present. If DB is missing, initialize from schema file.
    Also applies lightweight migrations for demo tables (e.g., products catalog)."""
    if not os.path.exists(DB_PATH):
        if not os.path.exists(SCHEMA_PATH):
            raise FileNotFoundError("Missing schema file: oneinbox_schema.sql")
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = f.read()
        conn = db()
        try:
            conn.executescript(schema)
            conn.commit()
        finally:
            conn.close()

    # Ensure optional demo tables exist (idempotent)
    ensure_products()


# Ensure DB exists at startup
init_db_if_needed()
def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def norm_text(s: str) -> str:
    s = strip_accents(s or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def thread_external_id(platform: str, user: str) -> str:
    return f"{platform}:{user.strip()}"

def ensure_customer_and_thread(platform: str, user_name: str) -> Tuple[int, int, str]:
    """Returns (customer_id, thread_db_id, thread_external_id)."""
    user_name = (user_name or "Usuario").strip() or "Usuario"
    ext_id = thread_external_id(platform, user_name)
    conn = db()
    try:
        # customer by display_name (MVP)
        row = conn.execute("SELECT id FROM customers WHERE display_name = ?", (user_name,)).fetchone()
        if row:
            customer_id = int(row["id"])
        else:
            cur = conn.execute("INSERT INTO customers(display_name, opt_in) VALUES (?, 1)", (user_name,))
            customer_id = int(cur.lastrowid)

        # identity (best-effort; avoid UNIQUE collisions by using user_name)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO customer_identities(customer_id, platform, platform_user_id, handle) VALUES (?,?,?,?)",
                (customer_id, platform, user_name, user_name),
            )
        except Exception:
            pass

        # thread by platform + external_thread_id (stable across restarts)
        trow = conn.execute(
            "SELECT id FROM threads WHERE platform = ? AND external_thread_id = ? ORDER BY last_activity_at DESC LIMIT 1",
            (platform, ext_id),
        ).fetchone()
        if trow:
            thread_id = int(trow["id"])
        else:
            cur = conn.execute(
                "INSERT INTO threads(platform, customer_id, external_thread_id, status, priority, tags) VALUES (?,?,?,?,?,?)",
                (platform, customer_id, ext_id, "open", "normal", None),
            )
            thread_id = int(cur.lastrowid)

        conn.commit()
        return customer_id, thread_id, ext_id
    finally:
        conn.close()

def load_thread_state(thread_id: int) -> Dict[str, Any]:
    """Persisted state for the rule-engine (stored inside threads.tags as JSON)."""
    conn = db()
    try:
        row = conn.execute("SELECT tags FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if not row or not row["tags"]:
            return {}
        try:
            blob = json.loads(row["tags"])
            if isinstance(blob, dict) and isinstance(blob.get("_state"), dict):
                return blob["_state"]
        except Exception:
            return {}
        return {}
    finally:
        conn.close()

def save_thread_state(thread_id: int, state: Dict[str, Any]) -> None:
    conn = db()
    try:
        row = conn.execute("SELECT tags FROM threads WHERE id = ?", (thread_id,)).fetchone()
        blob = {}
        if row and row["tags"]:
            try:
                blob = json.loads(row["tags"]) if row["tags"] else {}
                if not isinstance(blob, dict):
                    blob = {}
            except Exception:
                blob = {}
        blob["_state"] = state or {}
        conn.execute(
            "UPDATE threads SET tags = ?, updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ','now')) WHERE id = ?",
            (json.dumps(blob, ensure_ascii=False), thread_id),
        )
        conn.commit()
    finally:
        conn.close()

def log_event(thread_id: int, message_id: Optional[int], event_type: str, status: str = "ok", details: Optional[dict] = None) -> None:
    conn = db()
    try:
        conn.execute(
            "INSERT INTO automation_events(thread_id, message_id, event_type, status, details_json) VALUES (?,?,?,?,?)",
            (thread_id, message_id, event_type, status, json.dumps(details or {}, ensure_ascii=False) if details else None),
        )
        conn.commit()
    finally:
        conn.close()

def insert_message(thread_id: int, platform: str, role: str, user: str, text: str, reply_to: Optional[str] = None, intent: Optional[str] = None, confidence: Optional[float] = None, is_auto: bool = False) -> dict:
    """
    role: 'user' or 'system' (UI expects this)
    """
    sender_type = "user" if role == "user" else "system"
    sender_name = user if sender_type == "user" else AUTO_USER
    conn = db()
    try:
        cur = conn.execute(
            "INSERT INTO messages(thread_id, platform, sender_type, sender_name, content, intent, confidence, is_auto) VALUES (?,?,?,?,?,?,?,?)",
            (thread_id, platform, sender_type, sender_name, text, intent, confidence, 1 if is_auto else 0),
        )
        mid = int(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()

    # Provide the shape expected by the front-end (index.html normMsg)
    # Use thread external id in payload
    ext = conn  # placeholder for mypy; will re-open quickly
    _, _, ext_id = ensure_customer_and_thread(platform, user)  # safe: returns same ext_id
    return {
        "id": str(mid),
        "seq": mid,
        "thread_id": ext_id,
        "platform": platform,
        "role": role,
        "user": user,
        "text": text,
        "timestamp": _utc_iso(),
        "typing": False,
        "client_only": False,
        "reply_to": reply_to,
    }

# =========================
# Rule engine
# =========================

KW = {
  "catalog": ["catalogo","catálogo","productos","producto","que vendes","qué vendes","que venden","qué venden","vendes","venden","tenes","tenés","tienen",
              "mochila","mochilas","remera","remeras","calzado","zapatilla","zapatillas","zapatos","zapatito","remera","remeritas"],
  "price": ["precio","costo","vale","cuanto","cuánto","valor"],
  "hours": ["horario","horarios","abren","cierran","atienden","atencion","atención"],
  "shipping": ["envio","envío","delivery","envian","envían","envío a domicilio"],
  "refund": ["reembolso","devolucion","devolución","me cobraron","cobro","cobrar","cargo","duplicado"],
  "account": ["contraseña","contrasena","codigo","código","bloqueo","bloqueada","no puedo entrar","login","iniciar sesion","iniciar sesión"],
  "status": ["estado","novedades","tarda","proceso","tramite","trámite","seguimiento"]
}

SLOTS = {
  "catalog": ["categoria"],
  "shipping": ["direccion", "zona"],
  "refund": ["numero_orden", "monto"],
  "account": ["email_o_telefono"]
}

RESP = {
  "price": [
    "Nuestros precios varían según el producto. ¿Qué artículo te interesa?",
    "¡Claro! Decime qué producto estás buscando y te paso el precio.",
  ],
  "hours": [
    "Atendemos de lunes a viernes de 8:00 a 18:00. ¿En qué te ayudo?",
    "Nuestro horario es 8:00–18:00 (L–V). ¿Querés que te asesore con algo específico?",
  ],
  "shipping": [
    "Hacemos envíos. ¿Me pasás tu dirección y zona para cotizar tiempo de entrega?",
    "Sí, enviamos a domicilio. ¿Cuál es tu dirección y zona?",
  ],
  "refund": [
    "Entiendo. Para ayudarte con el reembolso necesito el número de orden y el monto.",
    "Vamos a resolverlo. Pasame número de orden y monto para verificar el cobro.",
  ],
  "account": [
    "Te ayudo con el acceso. ¿Me confirmás tu email o teléfono asociado a la cuenta?",
    "Entendido. Necesito tu email o teléfono para revisar el ingreso.",
  ],
  "status": [
    "Puedo revisar el estado. ¿Tenés un número de caso/orden para ubicarlo?",
    "Dale, ¿me pasás el número de caso/orden para ver el estado?",
  ],
  "fallback": [
    "Gracias por tu mensaje. Un agente te responderá pronto. ¿Podés darme un poco más de detalle?",
    "Recibido. ¿Me contás un poco más para ayudarte mejor?",
  ]
}

def classify(text: str) -> Tuple[str, float]:
    t = norm_text(text)
    for intent, kws in KW.items():
        for kw in kws:
            if norm_text(kw) in t:
                return intent, 0.85
    return "fallback", 0.35

def extract(text: str, intent: str) -> Dict[str, str]:
    # MVP: very light extraction; extend later
    t = (text or "").strip()
    out: Dict[str, str] = {}
    if intent == "catalog":
        tn = norm_text(t)
        # detect category from message (mochilas / remeras / calzado)
        if any(k in tn for k in ["mochila", "mochilas", "backpack"]):
            out["categoria"] = "mochilas"
        elif any(k in tn for k in ["remera", "remeras", "camiseta", "camisetas", "remerita", "remeritas"]):
            out["categoria"] = "remeras"
        elif any(k in tn for k in ["calzado", "zapatilla", "zapatillas", "zapato", "zapatos", "zapatito", "zapatitos"]):
            out["categoria"] = "calzado"
    if intent == "refund":
        m = re.search(r"(?:orden|order|pedido)\s*#?\s*([A-Za-z0-9\-]{4,})", t, re.I)
        if m: out["numero_orden"] = m.group(1)
        m2 = re.search(r"\$?\s*([0-9]+(?:\.[0-9]{1,2})?)", t)
        if m2: out["monto"] = m2.group(1)
    if intent == "shipping":
        if len(t) > 12:
            out["direccion"] = t[:80]
    if intent == "account":
        m = re.search(r"[\w\.\-+]+@[\w\.\-]+\.\w+", t)
        if m: out["email_o_telefono"] = m.group(0)
    return out

def detect_category(text: str) -> Optional[str]:
    t = norm_text(text)
    # Map many user words to canonical categories
    cat_map = [
        ("mochilas", ["mochila", "mochilas", "backpack"]),
        ("remeras", ["remera", "remeras", "camiseta", "camisetas", "remerita", "remeritas"]),
        ("calzado", ["calzado", "zapatilla", "zapatillas", "zapato", "zapatos", "zapatito", "zapatitos"]),
    ]
    for cat, kws in cat_map:
        for kw in kws:
            if norm_text(kw) in t:
                return cat
    return None

def format_price(value: float, currency: str) -> str:
    try:
        v = float(value)
    except Exception:
        return str(value)
    if (currency or "").upper() == "PYG":
        # No decimals for guaraní
        return f"{int(round(v)):,}".replace(",", ".") + " Gs"
    return f"{v:.2f} {currency}".strip()

def list_categories() -> List[str]:
    conn = db()
    try:
        rows = conn.execute("SELECT DISTINCT category FROM products WHERE active=1 ORDER BY category ASC").fetchall()
        return [str(r["category"]) for r in rows]
    finally:
        conn.close()

def fetch_products(category: Optional[str] = None, text: Optional[str] = None, limit: int = 6) -> List[sqlite3.Row]:
    conn = db()
    try:
        if category:
            return conn.execute(
                "SELECT id, name, category, price, currency, stock FROM products WHERE active=1 AND category=? ORDER BY stock DESC, id ASC LIMIT ?",
                (category, limit),
            ).fetchall()
        # If no category, do a soft search over keywords/name
        if text:
            t = norm_text(text)
            rows = conn.execute(
                "SELECT id, name, category, price, currency, stock, keywords_json FROM products WHERE active=1"
            ).fetchall()
            hits = []
            for r in rows:
                name_n = norm_text(r["name"])
                kws = []
                try:
                    kws = json.loads(r["keywords_json"] or "[]")
                except Exception:
                    kws = []
                if name_n and name_n in t:
                    hits.append(r); continue
                for kw in kws:
                    if norm_text(str(kw)) in t:
                        hits.append(r); break
            return hits[:limit]
        return []
    finally:
        conn.close()

def render_product_list(rows: List[sqlite3.Row], category: Optional[str]) -> str:
    if not rows:
        cats = list_categories()
        cats_txt = ", ".join(cats) if cats else "mochilas, remeras, calzado"
        return f"No encontré productos para esa búsqueda. ¿Te interesa alguna de estas categorías: {cats_txt}?"
    lines = []
    for r in rows:
        price_txt = format_price(r["price"], r["currency"])
        stock_txt = f" (stock: {r['stock']})" if r["stock"] is not None else ""
        lines.append(f"- {r['name']}: {price_txt}{stock_txt}")
    head = f"Tenemos {category} disponibles:" if category else "Encontré estos productos:"
    return head + "\n" + "\n".join(lines) + "\n\n¿Cuál te interesa?"

def next_missing(intent: str, state: Dict[str, Any]) -> Optional[str]:
    needed = SLOTS.get(intent, [])
    slots = state.get("slots", {}) if isinstance(state.get("slots"), dict) else {}
    for k in needed:
        if not slots.get(k):
            return k
    return None

def pick_response(intent: str) -> str:
    options = RESP.get(intent) or RESP["fallback"]
    return random.choice(options)

def respond(thread_db_id: int, platform: str, user: str, text: str) -> Tuple[str, str, float]:
    """
    Returns (response_text, intent, confidence)
    Persists state per thread in threads.tags._state
    """
    state = load_thread_state(thread_db_id) or {}
    intent, conf = classify(text)
    slots = state.get("slots", {}) if isinstance(state.get("slots"), dict) else {}

    # If previously in an intent flow, stick to it unless new intent strong
    prev_intent = state.get("intent")
    if prev_intent and prev_intent != "fallback" and conf < 0.8:
        intent = prev_intent

    # Extract slots and update state
    extracted = extract(text, intent)
    slots.update(extracted)
    state["intent"] = intent
    state["slots"] = slots

    # Special case: product catalog queries (mochilas / remeras / calzado)
    if intent == "catalog":
        cat = slots.get("categoria")
        if not cat:
            cats = list_categories()
            cats_txt = ", ".join(cats) if cats else "mochilas, remeras, calzado"
            out = f"¡Claro! Ahora mismo tenemos estas categorías: {cats_txt}. ¿Cuál te interesa?"
            save_thread_state(thread_db_id, state)
            return out, intent, conf

        # Fetch products for the selected category (or search within message)
        rows = fetch_products(category=cat, text=text, limit=8)
        out = render_product_list(rows, cat)
        save_thread_state(thread_db_id, state)
        return out, intent, conf

    missing = next_missing(intent, state)
    if missing:
        # Ask for missing info
        prompts = {
            "direccion": "¿Cuál es tu dirección exacta?",
            "zona": "¿En qué zona/barrio estás?",
            "numero_orden": "¿Me pasás el número de orden/pedido?",
            "monto": "¿Qué monto te cobraron?",
            "email_o_telefono": "¿Me confirmás tu email o teléfono asociado?",
            "categoria": "¿Qué categoría te interesa? (mochilas / remeras / calzado)",
        }
        out = prompts.get(missing, "¿Me pasás ese dato para ayudarte?")
        save_thread_state(thread_db_id, state)
        return out, intent, conf

    # Final response
    out = pick_response(intent)
    save_thread_state(thread_db_id, state)
    return out, intent, conf

# =========================
# Routes
# =========================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/messages")
def api_messages():
    # Return most recent messages (cap) in the format expected by the UI.
    conn = db()
    try:
        rows = conn.execute(
            "SELECT m.id, m.platform, m.sender_type, m.sender_name, m.content, m.intent, m.confidence, m.is_auto, m.created_at, t.external_thread_id "
            "FROM messages m JOIN threads t ON t.id = m.thread_id "
            "ORDER BY m.id DESC LIMIT ?",
            (MSG_CAP,),
        ).fetchall()
    finally:
        conn.close()

    msgs = []
    # Reverse to chronological order
    for r in reversed(rows):
        role = "user" if r["sender_type"] == "user" else "system"
        # For system/bot messages, UI uses AUTO_USER; keep sender_name for user
        user = r["sender_name"] if role == "user" else AUTO_USER
        msgs.append({
            "id": str(r["id"]),
            "seq": int(r["id"]),
            "thread_id": str(r["external_thread_id"] or ""),
            "platform": str(r["platform"]),
            "role": role,
            "user": user,
            "text": str(r["content"] or ""),
            "timestamp": str(r["created_at"] or _utc_iso()),
            "typing": False,
            "client_only": False,
        })

    return jsonify({"messages": msgs})

@app.route("/api/generate")
def api_generate():
    platform = random.choice(PLATFORMS)
    user = random.choice([
        "Sofía","Lucas","Valentina","Mateo","Camila","Diego","Ana","Bruno","María","Nico","Carla","Julián","Mica","Tomás","Paula","Fede","Mauri","Jime","Abi","Enzo","Gabi"
    ])
    seeds = [
        "Hola", "Buenas", "Buen día", "Quiero comprar algo",
        "¿Cuál es el precio?", "¿Horarios de atención?", "¿Tienen envío?",
        "Me cobraron dos veces", "No puedo entrar a mi cuenta", "¿Hay stock?"
    ]
    text = random.choice(seeds)

    _, thread_db_id, ext_id = ensure_customer_and_thread(platform, user)

    # inbound
    inbound = insert_message(thread_db_id, platform, "user", user, text, is_auto=False)
    log_event(thread_db_id, int(inbound["seq"]), "ingest", "ok", {"source": "auto_generate"})
    log_event(thread_db_id, int(inbound["seq"]), "normalize", "ok", {"text_norm": norm_text(text)})

    # respond
    out, intent, conf = respond(thread_db_id, platform, user, text)
    log_event(thread_db_id, int(inbound["seq"]), "classify", "ok", {"intent": intent, "confidence": conf})
    system = insert_message(thread_db_id, platform, "system", AUTO_USER, out, reply_to=inbound["id"], intent=intent, confidence=conf, is_auto=True)
    log_event(thread_db_id, int(system["seq"]), "respond", "ok", {"intent": intent})
    log_event(thread_db_id, int(system["seq"]), "persist", "ok", {})

    return jsonify({"generated": [inbound, system]})

@app.route("/api/send", methods=["POST"])
def api_send():
    d = request.get_json(silent=True) or {}
    raw = (d.get("platform") or d.get("app") or d.get("channel") or "whatsapp").lower()
    platform = raw if raw in PLATFORMS else "whatsapp"

    user = (d.get("user_name") or d.get("user") or d.get("sender") or "Usuario").strip() or "Usuario"
    text = (d.get("message") or d.get("text") or d.get("content") or "").strip()

    _, thread_db_id, _ = ensure_customer_and_thread(platform, user)

    inbound = insert_message(thread_db_id, platform, "user", user, text, is_auto=False)
    log_event(thread_db_id, int(inbound["seq"]), "ingest", "ok", {"source": "manual"})
    log_event(thread_db_id, int(inbound["seq"]), "normalize", "ok", {"text_norm": norm_text(text)})

    out, intent, conf = respond(thread_db_id, platform, user, text)
    log_event(thread_db_id, int(inbound["seq"]), "classify", "ok", {"intent": intent, "confidence": conf})

    system = insert_message(thread_db_id, platform, "system", AUTO_USER, out, reply_to=inbound["id"], intent=intent, confidence=conf, is_auto=True)
    log_event(thread_db_id, int(system["seq"]), "respond", "ok", {"intent": intent})
    log_event(thread_db_id, int(system["seq"]), "persist", "ok", {})

    return jsonify({"messages": [inbound, system]})

@app.route("/api/clear", methods=["POST"])
def api_clear():
    conn = db()
    try:
        # Clear in dependency-safe order
        conn.execute("DELETE FROM automation_events;")
        conn.execute("DELETE FROM messages;")
        conn.execute("DELETE FROM threads;")
        conn.execute("DELETE FROM customer_identities;")
        conn.execute("DELETE FROM customers;")
        conn.execute("DELETE FROM metrics_daily;")
        # Also clear FTS table if present
        try:
            conn.execute("DELETE FROM messages_fts;")
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(debug=True, port=5000)

