"""
TechTV Server — API REST
Hospede gratuitamente no Railway, Render ou Fly.io
"""
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import json, os, hashlib, secrets

app = FastAPI(title="TechTV API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_FILE  = os.environ.get("DATA_FILE", "dados_server.json")
API_SECRET = os.environ.get("API_SECRET", "techtv_secret_troque_isso")  # troque em produção

# ── Persistência ───────────────────────────────────────────────────────────────
def _load():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"ordens": [], "usuarios": [
        {"id": 1, "nome": "Admin", "email": "admin@techtv.com",
         "senha_hash": _hash("admin123"), "perfil": "admin"}
    ]}

def _save(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _hash(senha: str) -> str:
    return hashlib.sha256(senha.encode()).hexdigest()

# ── Auth ───────────────────────────────────────────────────────────────────────
def verificar_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Token necessário")
    token = authorization[7:]
    data = _load()
    for u in data.get("usuarios", []):
        if u.get("token") == token:
            return u
    raise HTTPException(401, "Token inválido")

def verificar_admin(usuario=Depends(verificar_token)):
    if usuario.get("perfil") != "admin":
        raise HTTPException(403, "Acesso restrito")
    return usuario

# ── Modelos ────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    senha: str

class StatusUpdate(BaseModel):
    status: str
    observacao: Optional[str] = ""

class OrdemImport(BaseModel):
    ordens: List[dict]

class ItemServico(BaseModel):
    desc: str
    qtd: float = 1
    val: float = 0

class EdicaoOS(BaseModel):
    servicos: List[ItemServico]
    status: Optional[str] = None
    observacao: Optional[str] = ''


# ── Rotas públicas ─────────────────────────────────────────────────────────────
# Serve arquivos estáticos se a pasta existir
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
def root():
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h2>TechTV API online</h2><p>Coloque index.html na pasta static/</p>")

@app.post("/auth/login")
def login(req: LoginRequest):
    data = _load()
    for u in data.get("usuarios", []):
        if u["email"].lower() == req.email.lower() and u["senha_hash"] == _hash(req.senha):
            token = secrets.token_hex(32)
            u["token"] = token
            u["ultimo_acesso"] = datetime.now().strftime("%d/%m/%Y %H:%M")
            _save(data)
            return {"token": token, "nome": u["nome"], "perfil": u["perfil"]}
    raise HTTPException(401, "E-mail ou senha incorretos")

# Consulta pública por número de OS (para o cliente)
@app.get("/os/consulta/{numero}")
def consulta_publica(numero: int):
    data = _load()
    for o in data["ordens"]:
        if o.get("num") == numero:
            cli = o.get("cliente", {})
            tv  = o.get("tv", {})
            return {
                "num":          o["num"],
                "status":       o.get("status", ""),
                "data_entrada": o.get("data_entrada", ""),
                "prazo":        o.get("prazo", ""),
                "data_entrega": o.get("data_entrega", ""),
                "cliente_nome": cli.get("nome", ""),
                "aparelho":     f"{tv.get('marca','')} {tv.get('modelo','')}".strip(),
                "defeito":      o.get("defeito", ""),
                "tecnico":      o.get("tecnico", ""),
                "historico":    o.get("historico", []),
            }
    raise HTTPException(404, "OS não encontrada")


@app.get("/os/consulta-nome/{nome}")
def consulta_por_nome(nome: str):
    data = _load()
    resultado = []
    busca = nome.lower().strip()
    for o in data["ordens"]:
        cli = o.get("cliente", {})
        if busca in cli.get("nome", "").lower():
            tv = o.get("tv", {})
            resultado.append({
                "num":          o["num"],
                "status":       o.get("status", ""),
                "data_entrada": o.get("data_entrada", ""),
                "prazo":        o.get("prazo", ""),
                "data_entrega": o.get("data_entrega", ""),
                "cliente_nome": cli.get("nome", ""),
                "aparelho":     (tv.get("marca","") + " " + tv.get("modelo","")).strip(),
                "defeito":      o.get("defeito", ""),
                "tecnico":      o.get("tecnico", ""),
                "historico":    o.get("historico", []),
                "servicos":     o.get("servicos", []),
                "total":        o.get("total", 0),
            })
    return resultado


class AprovacaoOrcamento(BaseModel):
    aprovado: bool
    obs: Optional[str] = ""

@app.patch("/os/{numero}/orcamento")
def aprovar_orcamento(numero: int, req: AprovacaoOrcamento):
    """Rota pública — cliente aprova ou rejeita o orçamento."""
    data = _load()
    for o in data["ordens"]:
        if o.get("num") == numero:
            o["orcamento_status"] = "aprovado" if req.aprovado else "rejeitado"
            o["orcamento_obs"]    = req.obs or ""
            o["orcamento_em"]     = datetime.now().strftime("%d/%m/%Y %H:%M")
            o.setdefault("historico", []).append({
                "de": o.get("status",""),
                "para": o.get("status",""),
                "por": "Cliente",
                "em": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "obs": "Orçamento " + ("APROVADO" if req.aprovado else "REJEITADO") +
                       (" — " + req.obs if req.obs else "")
            })
            _save(data)
            return {"ok": True, "orcamento_status": o["orcamento_status"]}
    raise HTTPException(404, "OS não encontrada")

# ── Rotas autenticadas ─────────────────────────────────────────────────────────
@app.get("/os")
def listar_ordens(
    status: Optional[str] = None,
    busca:  Optional[str] = None,
    usuario=Depends(verificar_token)
):
    data = _load()
    ordens = data["ordens"]
    if status and status != "Todos":
        ordens = [o for o in ordens if o.get("status") == status]
    if busca:
        b = busca.lower()
        ordens = [o for o in ordens if
                  b in o.get("cliente", {}).get("nome", "").lower() or
                  b in str(o.get("num", "")) or
                  b in o.get("tv", {}).get("modelo", "").lower()]
    # Retorna resumo
    return [{"num": o["num"],
             "data_entrada": o.get("data_entrada",""),
             "cliente": o.get("cliente",{}).get("nome",""),
             "aparelho": f"{o.get('tv',{}).get('marca','')} {o.get('tv',{}).get('modelo','')}".strip(),
             "status": o.get("status",""),
             "total": o.get("total", 0),
             "tecnico": o.get("tecnico",""),
             "prazo": o.get("prazo","")} for o in ordens]

@app.get("/os/{numero}")
def detalhe_ordem(numero: int, usuario=Depends(verificar_token)):
    data = _load()
    for o in data["ordens"]:
        if o.get("num") == numero:
            return o
    raise HTTPException(404, "OS não encontrada")

@app.patch("/os/{numero}/status")
def atualizar_status(numero: int, req: StatusUpdate, usuario=Depends(verificar_token)):
    data = _load()
    for o in data["ordens"]:
        if o.get("num") == numero:
            status_anterior = o.get("status", "")
            o["status"] = req.status
            if req.status == "Entregue":
                o["data_entrega"] = datetime.now().strftime("%d/%m/%Y %H:%M")
            # Histórico de mudanças
            o.setdefault("historico", []).append({
                "de": status_anterior,
                "para": req.status,
                "por": usuario["nome"],
                "em": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "obs": req.observacao or ""
            })
            _save(data)
            return {"ok": True, "status": req.status}
    raise HTTPException(404, "OS não encontrada")

@app.get("/dashboard")
def dashboard(usuario=Depends(verificar_token)):
    data = _load()
    ordens = data["ordens"]
    return {
        "total":      len(ordens),
        "abertas":    sum(1 for o in ordens if o.get("status") == "Aberta"),
        "andamento":  sum(1 for o in ordens if o.get("status") == "Em andamento"),
        "prontas":    sum(1 for o in ordens if o.get("status") == "Pronto"),
        "entregues":  sum(1 for o in ordens if o.get("status") == "Entregue"),
        "faturamento":sum(o.get("total", 0) for o in ordens),
        "ultimas":    [{"num": o["num"],
                        "cliente": o.get("cliente",{}).get("nome",""),
                        "status": o.get("status","")} for o in ordens[:8]],
    }

# Sincronização do desktop → servidor
@app.post("/sync/upload")
def sync_upload(payload: OrdemImport, x_api_secret: str = Header(None)):
    if x_api_secret != API_SECRET:
        raise HTTPException(403, "Chave de sincronização inválida")
    data = _load()
    # Merge: atualiza existentes, adiciona novas
    existentes = {o["num"]: i for i, o in enumerate(data["ordens"])}
    for nova in payload.ordens:
        num = nova.get("num")
        if num in existentes:
            # Preserva histórico do servidor
            historico = data["ordens"][existentes[num]].get("historico", [])
            data["ordens"][existentes[num]] = nova
            data["ordens"][existentes[num]]["historico"] = historico
        else:
            data["ordens"].insert(0, nova)
    _save(data)
    return {"ok": True, "sincronizadas": len(payload.ordens)}

@app.get("/sync/download")
def sync_download(x_api_secret: str = Header(None)):
    if x_api_secret != API_SECRET:
        raise HTTPException(403, "Chave de sincronização inválida")
    data = _load()
    return {"ordens": data["ordens"]}

# Gerenciar usuários (admin)
@app.get("/usuarios")
def listar_usuarios(admin=Depends(verificar_admin)):
    data = _load()
    return [{"id": u["id"], "nome": u["nome"], "email": u["email"], "perfil": u["perfil"]}
            for u in data.get("usuarios", [])]

class NovoUsuario(BaseModel):
    nome: str
    email: str
    senha: str
    perfil: str = "tecnico"

@app.post("/usuarios")
def criar_usuario(req: NovoUsuario, admin=Depends(verificar_admin)):
    data = _load()
    ids = [u["id"] for u in data.get("usuarios", [])]
    novo = {"id": max(ids)+1 if ids else 1, "nome": req.nome,
            "email": req.email, "senha_hash": _hash(req.senha),
            "perfil": req.perfil}
    data.setdefault("usuarios", []).append(novo)
    _save(data)
    return {"ok": True, "id": novo["id"]}
