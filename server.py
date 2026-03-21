"""
TechTV Server — API REST com SQLite persistente
"""
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import json, os, hashlib, secrets, sqlite3

app = FastAPI(title="TechTV API", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

API_SECRET = os.environ.get("API_SECRET", "techtv2025")

# Banco de dados SQLite persistente
_vol = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "")
_dir = _vol if _vol else os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(_dir, "techtv.db")
print(f"[TechTV] Banco em: {DB_FILE}", flush=True)

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def _hash(s): return hashlib.sha256(s.encode()).hexdigest()

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ordens (
            num INTEGER PRIMARY KEY,
            dados TEXT NOT NULL,
            atualizado TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT, email TEXT UNIQUE,
            senha_hash TEXT, perfil TEXT, token TEXT,
            ultimo_acesso TEXT
        )
    """)
    # Admin padrão
    cur = conn.execute("SELECT id FROM usuarios WHERE email='admin@techtv.com'")
    if not cur.fetchone():
        conn.execute("""
            INSERT INTO usuarios (nome, email, senha_hash, perfil)
            VALUES (?, ?, ?, ?)
        """, ("Admin", "admin@techtv.com", _hash("admin123"), "admin"))
    conn.commit()
    conn.close()




@app.get("/reset-admin")
def reset_admin():
    """Reseta a senha do admin para admin123. Remova após usar."""
    conn = get_db()
    # Deletar e recriar admin
    conn.execute("DELETE FROM usuarios WHERE email='admin@techtv.com'")
    conn.execute(
        "INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES (?,?,?,?)",
        ("Admin", "admin@techtv.com", _hash("admin123"), "admin")
    )
    conn.commit()
    conn.close()
    return {"ok": True, "msg": "Admin resetado. Email: admin@techtv.com | Senha: admin123"}

# ── Auth ───────────────────────────────────────────────────────────────────────
def verificar_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Token necessário")
    token = authorization[7:]
    conn = get_db()
    row = conn.execute("SELECT * FROM usuarios WHERE token=?", (token,)).fetchone()
    conn.close()
    if not row: raise HTTPException(401, "Token inválido")
    return dict(row)

def verificar_admin(usuario=Depends(verificar_token)):
    if usuario.get("perfil") != "admin": raise HTTPException(403, "Acesso restrito")
    return usuario

# ── Modelos ────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    senha: str

class StatusUpdate(BaseModel):
    status: str
    observacao: Optional[str] = ""

class ItemServico(BaseModel):
    desc: str
    qtd: float = 1
    val: float = 0

class EdicaoOS(BaseModel):
    servicos: List[ItemServico]
    status: Optional[str] = None
    observacao: Optional[str] = ""

class OrdemImport(BaseModel):
    ordens: List[dict]

class AprovacaoOrcamento(BaseModel):
    aprovado: bool
    obs: Optional[str] = ""

# ── Helpers ────────────────────────────────────────────────────────────────────
def _get_ordens(filtro_status=None, busca=None):
    conn = get_db()
    rows = conn.execute("SELECT dados FROM ordens ORDER BY num DESC").fetchall()
    conn.close()
    ordens = [json.loads(r["dados"]) for r in rows]
    if filtro_status and filtro_status != "Todos":
        ordens = [o for o in ordens if o.get("status") == filtro_status]
    if busca:
        b = busca.lower()
        ordens = [o for o in ordens if
                  b in o.get("cliente",{}).get("nome","").lower() or
                  b in str(o.get("num","")) or
                  b in o.get("tv",{}).get("modelo","").lower()]
    return ordens

def _get_ordem(num):
    conn = get_db()
    row = conn.execute("SELECT dados FROM ordens WHERE num=?", (num,)).fetchone()
    conn.close()
    return json.loads(row["dados"]) if row else None

def _save_ordem(o):
    conn = get_db()
    dados = json.dumps(o, ensure_ascii=False)
    conn.execute("""
        INSERT INTO ordens (num, dados, atualizado) VALUES (?,?,?)
        ON CONFLICT(num) DO UPDATE SET dados=excluded.dados, atualizado=excluded.atualizado
    """, (o["num"], dados, datetime.now().strftime("%d/%m/%Y %H:%M")))
    conn.commit()
    conn.close()

# ── Rotas públicas ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def root():
    html = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(html):
        return HTMLResponse(open(html, encoding="utf-8").read())
    return HTMLResponse("<h2>TechTV API online</h2>")

@app.post("/auth/login")
def login(req: LoginRequest):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM usuarios WHERE email=? AND senha_hash=?",
        (req.email.lower(), _hash(req.senha))
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(401, "E-mail ou senha incorretos")
    token = secrets.token_hex(32)
    conn.execute("UPDATE usuarios SET token=?, ultimo_acesso=? WHERE id=?",
                 (token, datetime.now().strftime("%d/%m/%Y %H:%M"), row["id"]))
    conn.commit()
    conn.close()
    return {"token": token, "nome": row["nome"], "perfil": row["perfil"]}

@app.get("/os/consulta/{numero}")
def consulta_publica(numero: int):
    o = _get_ordem(numero)
    if not o: raise HTTPException(404, "OS não encontrada")
    cli = o.get("cliente", {}); tv = o.get("tv", {})
    return {
        "num":              o["num"],
        "status":           o.get("status", ""),
        "data_entrada":     o.get("data_entrada", ""),
        "prazo":            o.get("prazo", ""),
        "data_entrega":     o.get("data_entrega", ""),
        "cliente_nome":     cli.get("nome", ""),
        "aparelho":         f"{tv.get('marca','')} {tv.get('modelo','')}".strip(),
        "defeito":          o.get("defeito", ""),
        "tecnico":          o.get("tecnico", ""),
        "historico":        o.get("historico", []),
        "servicos":         o.get("servicos", []),
        "total":            o.get("total", 0),
        "orcamento_status": o.get("orcamento_status", ""),
        "orcamento_obs":    o.get("orcamento_obs", ""),
        "orcamento_em":     o.get("orcamento_em", ""),
    }

@app.get("/os/consulta-nome/{nome}")
def consulta_por_nome(nome: str):
    busca = nome.lower().strip()
    ordens = _get_ordens()
    resultado = []
    for o in ordens:
        cli = o.get("cliente", {})
        if busca in cli.get("nome", "").lower():
            tv = o.get("tv", {})
            resultado.append({
                "num":          o["num"],
                "status":       o.get("status", ""),
                "data_entrada": o.get("data_entrada", ""),
                "cliente_nome": cli.get("nome", ""),
                "aparelho":     f"{tv.get('marca','')} {tv.get('modelo','')}".strip(),
                "total":        o.get("total", 0),
            })
    return resultado

@app.patch("/os/{numero}/orcamento")
def aprovar_orcamento(numero: int, req: AprovacaoOrcamento):
    o = _get_ordem(numero)
    if not o: raise HTTPException(404, "OS não encontrada")
    o["orcamento_status"] = "aprovado" if req.aprovado else "rejeitado"
    o["orcamento_obs"]    = req.obs or ""
    o["orcamento_em"]     = datetime.now().strftime("%d/%m/%Y %H:%M")
    o.setdefault("historico", []).append({
        "de": o.get("status",""), "para": o.get("status",""),
        "por": "Cliente",
        "em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "obs": "Orçamento " + ("APROVADO" if req.aprovado else "REJEITADO") +
               (" — " + req.obs if req.obs else "")
    })
    _save_ordem(o)
    return {"ok": True, "orcamento_status": o["orcamento_status"]}

# ── Rotas autenticadas ─────────────────────────────────────────────────────────
@app.get("/os")
def listar_ordens(status: Optional[str] = None, busca: Optional[str] = None,
                  usuario=Depends(verificar_token)):
    ordens = _get_ordens(status, busca)
    return [{"num": o["num"],
             "data_entrada": o.get("data_entrada",""),
             "cliente": o.get("cliente",{}).get("nome",""),
             "aparelho": f"{o.get('tv',{}).get('marca','')} {o.get('tv',{}).get('modelo','')}".strip(),
             "status": o.get("status",""),
             "total": o.get("total",0),
             "tecnico": o.get("tecnico","")} for o in ordens]

@app.get("/os/{numero}")
def detalhe_ordem(numero: int, usuario=Depends(verificar_token)):
    o = _get_ordem(numero)
    if not o: raise HTTPException(404, "OS não encontrada")
    return o

@app.patch("/os/{numero}/status")
def atualizar_status(numero: int, req: StatusUpdate, usuario=Depends(verificar_token)):
    o = _get_ordem(numero)
    if not o: raise HTTPException(404, "OS não encontrada")
    status_ant = o.get("status","")
    o["status"] = req.status
    if req.status == "Entregue":
        o["data_entrega"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    o.setdefault("historico",[]).append({
        "de": status_ant, "para": req.status,
        "por": usuario["nome"],
        "em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "obs": req.observacao or ""
    })
    _save_ordem(o)
    return {"ok": True, "status": req.status}

@app.patch("/os/{numero}/editar")
def editar_os(numero: int, req: EdicaoOS, usuario=Depends(verificar_token)):
    o = _get_ordem(numero)
    if not o: raise HTTPException(404, "OS não encontrada — sincronize o desktop primeiro")
    o["servicos"] = [s.dict() for s in req.servicos]
    o["total"] = sum(s.qtd * s.val for s in req.servicos)
    if req.status and req.status != o.get("status"):
        status_ant = o.get("status","")
        o["status"] = req.status
        if req.status == "Entregue":
            o["data_entrega"] = datetime.now().strftime("%d/%m/%Y %H:%M")
        o.setdefault("historico",[]).append({
            "de": status_ant, "para": req.status,
            "por": usuario["nome"],
            "em": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "obs": req.observacao or "Editado pelo app mobile"
        })
    _save_ordem(o)
    return {"ok": True, "total": o["total"], "status": o.get("status")}

@app.get("/dashboard")
def dashboard(usuario=Depends(verificar_token)):
    ordens = _get_ordens()
    return {
        "total":      len(ordens),
        "abertas":    sum(1 for o in ordens if o.get("status")=="Aberta"),
        "andamento":  sum(1 for o in ordens if o.get("status")=="Em andamento"),
        "prontas":    sum(1 for o in ordens if o.get("status")=="Pronto"),
        "entregues":  sum(1 for o in ordens if o.get("status")=="Entregue"),
        "faturamento":sum(o.get("total",0) for o in ordens),
        "ultimas":    [{"num":o["num"],"cliente":o.get("cliente",{}).get("nome",""),
                        "status":o.get("status","")} for o in ordens[:8]],
    }

@app.post("/sync/upload")
def sync_upload(payload: OrdemImport, x_api_secret: str = Header(None)):
    if (x_api_secret or "").strip() != API_SECRET.strip():
        raise HTTPException(403, "Chave de sincronização inválida")
    for o in payload.ordens:
        _save_ordem(o)
    return {"ok": True, "sincronizadas": len(payload.ordens)}

@app.get("/sync/download")
def sync_download(x_api_secret: str = Header(None)):
    if (x_api_secret or "").strip() != API_SECRET.strip():
        raise HTTPException(403, "Chave de sincronização inválida")
    return {"ordens": _get_ordens()}

@app.get("/usuarios")
def listar_usuarios(admin=Depends(verificar_admin)):
    conn = get_db()
    rows = conn.execute("SELECT id,nome,email,perfil FROM usuarios").fetchall()
    conn.close()
    return [dict(r) for r in rows]

class NovoUsuario(BaseModel):
    nome: str; email: str; senha: str; perfil: str = "tecnico"

@app.post("/usuarios")
def criar_usuario(req: NovoUsuario, admin=Depends(verificar_admin)):
    conn = get_db()
    try:
        conn.execute("INSERT INTO usuarios (nome,email,senha_hash,perfil) VALUES (?,?,?,?)",
                     (req.nome, req.email, _hash(req.senha), req.perfil))
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(400, "E-mail já cadastrado")
    finally:
        conn.close()
    return {"ok": True}
