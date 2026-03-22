"""
TechTV Server — API REST com SQLite persistente
"""
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import json, os, hashlib, secrets, sqlite3, tempfile

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
        CREATE TABLE IF NOT EXISTS config (
            chave TEXT PRIMARY KEY,
            dados TEXT NOT NULL
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





# ── Auth ───────────────────────────────────────────────────────────────────────
init_db()

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


class NovaOSWeb(BaseModel):
    cliente: dict
    tv: dict
    defeito: Optional[str] = ""
    checklist: Optional[dict] = {}
    servicos: Optional[List[dict]] = []
    total: Optional[float] = 0
    tecnico: Optional[str] = ""
    prazo: Optional[str] = ""
    status: Optional[str] = "Aberta"

@app.post("/os/nova")
def criar_os_web(os_data: NovaOSWeb, usuario=Depends(verificar_token)):
    conn = get_db()
    cur = conn.execute("SELECT MAX(num) as mx FROM ordens").fetchone()
    prox_num = (cur["mx"] or 1000) + 1
    conn.close()
    o = os_data.dict()
    o["num"] = prox_num
    o["data_entrada"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    o["status"] = "Aberta"
    o["historico"] = []
    _save_ordem(o)
    return {"ok": True, "num": prox_num}


# ── Geração de PDF ─────────────────────────────────────────────────────────────
def _config_empresa():
    """Retorna configuração da empresa salva."""
    conn = get_db()
    try:
        row = conn.execute("SELECT dados FROM config WHERE chave='empresa'").fetchone()
        return json.loads(row["dados"]) if row else {}
    except Exception:
        return {}
    finally:
        conn.close()

def _gerar_pdf_os_simples(o):
    """Gera PDF da OS usando reportlab."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="os_")
        tmp.close()
        cfg = _config_empresa()
        W = 170*mm

        doc = SimpleDocTemplate(tmp.name, pagesize=A4,
              leftMargin=20*mm, rightMargin=20*mm, topMargin=15*mm, bottomMargin=15*mm)

        def ps(name, **kw): return ParagraphStyle(name, **kw)
        E = {
            'emp':   ps('e', fontSize=16, fontName='Helvetica-Bold', alignment=TA_CENTER),
            'sub':   ps('s', fontSize=9,  fontName='Helvetica', alignment=TA_CENTER, textColor=colors.grey),
            'tit':   ps('t', fontSize=12, fontName='Helvetica-Bold'),
            'val':   ps('v', fontSize=9,  fontName='Helvetica'),
            'lbl':   ps('l', fontSize=7,  fontName='Helvetica-Bold', textColor=colors.grey),
            'sec':   ps('sc', fontSize=9, fontName='Helvetica-Bold', textColor=colors.white),
            'tot':   ps('tt', fontSize=11, fontName='Helvetica-Bold', alignment=TA_RIGHT),
            'obs':   ps('o', fontSize=8,  fontName='Helvetica', textColor=colors.grey, alignment=TA_RIGHT),
            'rod':   ps('r', fontSize=7,  fontName='Helvetica', textColor=colors.grey, alignment=TA_CENTER),
            'ass':   ps('a', fontSize=7,  fontName='Helvetica', textColor=colors.grey, alignment=TA_CENTER),
        }

        story = []
        empresa = cfg.get("empresa", "Assistência Técnica")
        cnpj = cfg.get("cnpj",""); tel = cfg.get("telefone","")
        end = cfg.get("endereco",""); email_e = cfg.get("email_empresa","")

        # Cabeçalho azul
        from reportlab.platypus import Table as PT
        emp_s = ParagraphStyle('es', fontSize=17, fontName='Helvetica-Bold', textColor=colors.white, alignment=TA_CENTER)
        sub_s = ParagraphStyle('ss', fontSize=8,  fontName='Helvetica', textColor=colors.HexColor('#d0e8ff'), alignment=TA_CENTER)
        cab = [Paragraph(empresa, emp_s)]
        info = []
        if cnpj: info.append("CNPJ: "+cnpj)
        if tel:  info.append("Tel: "+tel)
        if email_e: info.append(email_e)
        if info: cab.append(Paragraph("  |  ".join(info), sub_s))
        if end:  cab.append(Paragraph(end, sub_s))

        t_cab = PT([[cab]], colWidths=[W])
        t_cab.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#1e3a5f')),
            ('PADDING',(0,0),(-1,-1),12),
        ]))
        story.append(t_cab)
        story.append(Spacer(1,6))

        # Título doc
        cli = o.get("cliente",{}); tv = o.get("tv",{})
        num = o.get("num",""); data = o.get("data_entrada","")
        tit_s = ParagraphStyle('ts', fontSize=13, fontName='Helvetica-Bold', textColor=colors.HexColor('#1e3a5f'))
        num_s = ParagraphStyle('ns', fontSize=9, fontName='Helvetica', textColor=colors.grey, alignment=TA_RIGHT)
        t_tit = PT([[Paragraph("ORDEM DE SERVIÇO", tit_s), Paragraph(f"#{num}\n{data}", num_s)]], colWidths=[W*0.65, W*0.35])
        t_tit.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LINEBELOW',(0,0),(-1,-1),1.5,colors.HexColor('#1e3a5f')),('PADDING',(0,0),(-1,-1),5)]))
        story.append(t_tit); story.append(Spacer(1,6))

        def sec_bar(txt):
            t = PT([[Paragraph(txt, E['sec'])]], colWidths=[W])
            t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#1e3a5f')),('PADDING',(0,0),(-1,-1),5)]))
            return t

        def grid(rows, cols):
            t = PT(rows, colWidths=cols)
            t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.3,colors.lightgrey),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#f8f8f8')),('BACKGROUND',(2,0),(2,-1),colors.HexColor('#f8f8f8')),('PADDING',(0,0),(-1,-1),5)]))
            return t

        story.append(sec_bar("  DADOS DO CLIENTE"))
        story.append(grid([
            [Paragraph("Nome",E['lbl']),Paragraph(cli.get("nome",""),E['val']),Paragraph("Telefone",E['lbl']),Paragraph(cli.get("tel",""),E['val'])],
            [Paragraph("CPF/CNPJ",E['lbl']),Paragraph(cli.get("doc",""),E['val']),Paragraph("E-mail",E['lbl']),Paragraph(cli.get("email",""),E['val'])],
        ],[W*.14,W*.36,W*.14,W*.36]))

        story.append(sec_bar("  DADOS DO APARELHO"))
        story.append(grid([
            [Paragraph("Marca",E['lbl']),Paragraph(tv.get("marca",""),E['val']),Paragraph("Modelo",E['lbl']),Paragraph(tv.get("modelo",""),E['val'])],
            [Paragraph("Tipo",E['lbl']),Paragraph(tv.get("tipo",""),E['val']),Paragraph("Nº Série",E['lbl']),Paragraph(tv.get("serie",""),E['val'])],
        ],[W*.14,W*.36,W*.14,W*.36]))
        story.append(Spacer(1,3))
        story.append(Paragraph("Defeito: "+o.get("defeito","—"), E['val']))

        # Checklist
        story.append(sec_bar("  CHECKLIST DE ENTRADA"))
        chk = o.get("checklist",{})
        CKITEMS = ['Controle remoto','Suporte','Pedestal','Cabo de força','Cabo HDMI','Cabo de antena','Tampa traseira','Parafusos','Manual','Caixa original','Pilhas no controle','Entradas sem dano','Tela sem trincas']
        rows_ch = [CKITEMS[i:i+4] for i in range(0,len(CKITEMS),4)]
        ch_data = []
        for linha in rows_ch:
            row = []
            for item in linha:
                ok = chk.get(item,False)
                cor = colors.HexColor('#b91c1c') if ok else colors.HexColor('#888888')
                p = ParagraphStyle('ci',fontSize=8,fontName='Helvetica',textColor=cor)
                row.append(Paragraph(('✕ ' if ok else '☐ ')+item, p))
            while len(row)<4: row.append(Paragraph("",E['val']))
            ch_data.append(row)
        t_ch = PT(ch_data, colWidths=[W/4]*4)
        t_ch.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.3,colors.lightgrey),('PADDING',(0,0),(-1,-1),5)]))
        story.append(t_ch)

        # Serviços
        story.append(sec_bar("  SERVIÇOS / PEÇAS"))
        srvs = o.get("servicos",[])
        srv_rows = [[Paragraph(h,E['lbl']) for h in ["Descrição","Qtd","Valor unit.","Subtotal"]]]
        for s in srvs:
            sub = s.get("qtd",1)*s.get("val",0)
            srv_rows.append([Paragraph(s.get("desc",""),E['val']),Paragraph(str(s.get("qtd",1)),E['val']),Paragraph(f"R$ {s.get('val',0):.2f}",E['val']),Paragraph(f"R$ {sub:.2f}",E['val'])])
        if not srvs: srv_rows.append([Paragraph("—",E['val'])]+[Paragraph("",E['val'])]*3)
        total = sum(s.get("qtd",1)*s.get("val",0) for s in srvs)
        srv_rows.append(["","",Paragraph("TOTAL:",E['tot']),Paragraph(f"R$ {total:.2f}",E['tot'])])
        t_srv = PT(srv_rows, colWidths=[W*.55,W*.1,W*.175,W*.175])
        t_srv.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eeeeee')),('GRID',(0,0),(-1,-2),0.3,colors.lightgrey),('LINEABOVE',(0,-1),(-1,-1),1,colors.black),('PADDING',(0,0),(-1,-1),5)]))
        story.append(t_srv)

        story.append(Spacer(1,4))
        story.append(Paragraph(f"Técnico: {o.get('tecnico','—')}  |  Prazo: {o.get('prazo','—')}  |  Status: {o.get('status','Aberta')}", E['obs']))

        # Assinaturas
        story.append(Spacer(1,14))
        ass_s = ParagraphStyle('as', fontSize=8, fontName='Helvetica', textColor=colors.grey, alignment=TA_CENTER)
        t_ass = PT([[HRFlowable(width=W*0.42,thickness=0.8,color=colors.black),"",HRFlowable(width=W*0.42,thickness=0.8,color=colors.black)],[Paragraph("Assinatura do cliente",ass_s),"",Paragraph("Assinatura do técnico",ass_s)]],colWidths=[W*0.42,W*0.16,W*0.42])
        t_ass.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'BOTTOM')]))
        story.append(t_ass)

        story.append(Spacer(1,8))
        story.append(Paragraph(f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} — {empresa}", E['rod']))

        doc.build(story)
        return tmp.name
    except ImportError:
        return None

@app.get("/pdf/os/{numero}")
def pdf_os(numero: int, usuario=Depends(verificar_token)):
    o = _get_ordem(numero)
    if not o: raise HTTPException(404, "OS não encontrada")
    cam = _gerar_pdf_os_simples(o)
    if not cam:
        raise HTTPException(500, "Instale reportlab no servidor: pip install reportlab")
    from fastapi.responses import FileResponse
    return FileResponse(cam, media_type="application/pdf",
                        filename=f"OS_{numero}.pdf",
                        headers={"Content-Disposition": f"inline; filename=OS_{numero}.pdf"})

@app.get("/pdf/laudo/{numero}")
def pdf_laudo(numero: int, usuario=Depends(verificar_token)):
    o = _get_ordem(numero)
    if not o: raise HTTPException(404, "OS não encontrada")
    # Gera laudo simples
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="laudo_")
        tmp.close()
        cfg = _config_empresa()
        W = 170*mm
        doc = SimpleDocTemplate(tmp.name, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=15*mm, bottomMargin=15*mm)
        story = []
        empresa = cfg.get("empresa","Assistência Técnica")

        emp_s = ParagraphStyle('es',fontSize=17,fontName='Helvetica-Bold',textColor=colors.white,alignment=TA_CENTER)
        sub_s = ParagraphStyle('ss',fontSize=8,fontName='Helvetica',textColor=colors.HexColor('#d0e8ff'),alignment=TA_CENTER)
        info = []
        if cfg.get("cnpj"): info.append("CNPJ: "+cfg["cnpj"])
        if cfg.get("telefone"): info.append("Tel: "+cfg["telefone"])
        cab_cont = [Paragraph(empresa, emp_s)]
        if info: cab_cont.append(Paragraph("  |  ".join(info), sub_s))
        t_cab = Table([[cab_cont]], colWidths=[W])
        t_cab.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#1e3a5f')),('PADDING',(0,0),(-1,-1),12)]))
        story.append(t_cab); story.append(Spacer(1,6))

        tit_s = ParagraphStyle('ts',fontSize=13,fontName='Helvetica-Bold',textColor=colors.HexColor('#1e3a5f'))
        num_s = ParagraphStyle('ns',fontSize=9,fontName='Helvetica',textColor=colors.grey,alignment=TA_RIGHT)
        t_tit = Table([[Paragraph("LAUDO TÉCNICO",tit_s),Paragraph(f"OS #{o.get('num','')}\n{o.get('data_entrada','')}",num_s)]],colWidths=[W*0.65,W*0.35])
        t_tit.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LINEBELOW',(0,0),(-1,-1),1.5,colors.HexColor('#1e3a5f')),('PADDING',(0,0),(-1,-1),5)]))
        story.append(t_tit); story.append(Spacer(1,8))

        val_s = ParagraphStyle('v',fontSize=9,fontName='Helvetica',leading=14)
        lbl_s = ParagraphStyle('l',fontSize=9,fontName='Helvetica-Bold',spaceBefore=8,spaceAfter=2)
        cli = o.get("cliente",{}); tv = o.get("tv",{})

        for lbl,val in [("Cliente:",cli.get("nome","")),("Telefone:",cli.get("tel","")),("Aparelho:",tv.get("marca","")+" "+tv.get("modelo","")),("Defeito relatado:",o.get("defeito",""))]:
            story.append(Paragraph(lbl,lbl_s)); story.append(Paragraph(val or "—",val_s))

        story.append(Paragraph("Diagnóstico Técnico:",lbl_s))
        story.append(Paragraph(o.get("laudo_diagnostico","") or "","" and val_s or val_s))
        story.append(Spacer(1,30 if not o.get("laudo_diagnostico") else 4))

        story.append(Paragraph("Serviços Realizados:",lbl_s))
        story.append(Paragraph(o.get("laudo_servicos_realizados","") or "",val_s))
        story.append(Spacer(1,30 if not o.get("laudo_servicos_realizados") else 4))

        story.append(Paragraph("Garantia:",lbl_s))
        story.append(Paragraph(o.get("laudo_garantia","Garantia de 90 dias.") or "Garantia de 90 dias.",val_s))

        story.append(Spacer(1,20))
        ass_s2 = ParagraphStyle('as',fontSize=8,fontName='Helvetica',textColor=colors.grey,alignment=TA_CENTER)
        t_ass = Table([[HRFlowable(width=W*0.42,thickness=0.8,color=colors.black),"",HRFlowable(width=W*0.42,thickness=0.8,color=colors.black)],[Paragraph("Assinatura do cliente",ass_s2),"",Paragraph("Assinatura do técnico",ass_s2)]],colWidths=[W*0.42,W*0.16,W*0.42])
        t_ass.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'BOTTOM')]))
        story.append(t_ass)
        doc.build(story)
        from fastapi.responses import FileResponse
        return FileResponse(tmp.name, media_type="application/pdf",
                            filename=f"Laudo_{numero}.pdf",
                            headers={"Content-Disposition": f"inline; filename=Laudo_{numero}.pdf"})
    except ImportError:
        raise HTTPException(500, "Instale reportlab: pip install reportlab")

@app.get("/pdf/nf/{numero}")
def pdf_nf(numero: int, usuario=Depends(verificar_token)):
    o = _get_ordem(numero)
    if not o: raise HTTPException(404, "OS não encontrada")
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="nf_")
        tmp.close()
        cfg = _config_empresa()
        W = 170*mm
        doc = SimpleDocTemplate(tmp.name, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=15*mm, bottomMargin=15*mm)
        story = []
        empresa = cfg.get("empresa","Assistência Técnica")

        emp_s = ParagraphStyle('es',fontSize=17,fontName='Helvetica-Bold',textColor=colors.white,alignment=TA_CENTER)
        sub_s = ParagraphStyle('ss',fontSize=8,fontName='Helvetica',textColor=colors.HexColor('#d0e8ff'),alignment=TA_CENTER)
        info = []
        if cfg.get("cnpj"): info.append("CNPJ: "+cfg["cnpj"])
        if cfg.get("telefone"): info.append("Tel: "+cfg["telefone"])
        if cfg.get("email_empresa"): info.append(cfg["email_empresa"])
        cab_cont = [Paragraph(empresa, emp_s)]
        if info: cab_cont.append(Paragraph("  |  ".join(info), sub_s))
        if cfg.get("endereco"): cab_cont.append(Paragraph(cfg["endereco"], sub_s))
        t_cab = Table([[cab_cont]], colWidths=[W])
        t_cab.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#1e3a5f')),('PADDING',(0,0),(-1,-1),12)]))
        story.append(t_cab); story.append(Spacer(1,6))

        av_s = ParagraphStyle('av',fontSize=8,fontName='Helvetica',textColor=colors.HexColor('#854F0B'),alignment=TA_CENTER,backColor=colors.HexColor('#FAEEDA'),borderPad=4)
        story.append(Paragraph("⚠ DOCUMENTO INTERNO — Não possui validade fiscal perante a Receita Federal", av_s))
        story.append(Spacer(1,8))

        tit_s = ParagraphStyle('ts',fontSize=13,fontName='Helvetica-Bold',textColor=colors.HexColor('#1e3a5f'))
        num_s2 = ParagraphStyle('ns',fontSize=9,fontName='Helvetica',textColor=colors.grey,alignment=TA_RIGHT)
        t_tit = Table([[Paragraph("RECIBO / NOTA FISCAL INTERNA",tit_s),Paragraph(f"OS #{o.get('num','')}\n{o.get('data_entrada','')}",num_s2)]],colWidths=[W*0.65,W*0.35])
        t_tit.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LINEBELOW',(0,0),(-1,-1),1.5,colors.HexColor('#1e3a5f')),('PADDING',(0,0),(-1,-1),5)]))
        story.append(t_tit); story.append(Spacer(1,8))

        lbl_s = ParagraphStyle('l',fontSize=7,fontName='Helvetica-Bold',textColor=colors.grey)
        val_s = ParagraphStyle('v',fontSize=9,fontName='Helvetica')
        cli = o.get("cliente",{})
        def gs(r,c):
            t=Table(r,colWidths=c)
            t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.3,colors.lightgrey),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#f8f8f8')),('BACKGROUND',(2,0),(2,-1),colors.HexColor('#f8f8f8')),('PADDING',(0,0),(-1,-1),5)]))
            return t
        story.append(Paragraph("CLIENTE", ParagraphStyle('sec',fontSize=9,fontName='Helvetica-Bold',textColor=colors.white,spaceBefore=4,spaceAfter=2)))
        t_cli = Table([[Paragraph("CLIENTE",ParagraphStyle('sc',fontSize=9,fontName='Helvetica-Bold',textColor=colors.white))]], colWidths=[W])
        t_cli.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#1e3a5f')),('PADDING',(0,0),(-1,-1),5)]))
        story.append(t_cli)
        story.append(gs([[Paragraph("Nome",lbl_s),Paragraph(cli.get("nome",""),val_s),Paragraph("Telefone",lbl_s),Paragraph(cli.get("tel",""),val_s)],[Paragraph("CPF/CNPJ",lbl_s),Paragraph(cli.get("doc",""),val_s),Paragraph("E-mail",lbl_s),Paragraph(cli.get("email",""),val_s)]],[W*.14,W*.36,W*.14,W*.36]))

        tot_s = ParagraphStyle('tt',fontSize=11,fontName='Helvetica-Bold',alignment=TA_RIGHT)
        srvs = o.get("servicos",[])
        srv_rows = [[Paragraph(h,lbl_s) for h in ["Descrição","Qtd","Valor unit.","Subtotal"]]]
        for s in srvs:
            sub = s.get("qtd",1)*s.get("val",0)
            srv_rows.append([Paragraph(s.get("desc",""),val_s),Paragraph(str(s.get("qtd",1)),val_s),Paragraph(f"R$ {s.get('val',0):.2f}",val_s),Paragraph(f"R$ {sub:.2f}",val_s)])
        total = sum(s.get("qtd",1)*s.get("val",0) for s in srvs)
        srv_rows.append(["","",Paragraph("TOTAL:",tot_s),Paragraph(f"R$ {total:.2f}",tot_s)])

        t_srv2 = Table([[Paragraph("SERVIÇOS / PEÇAS", ParagraphStyle('sc2',fontSize=9,fontName='Helvetica-Bold',textColor=colors.white))]], colWidths=[W])
        t_srv2.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#1e3a5f')),('PADDING',(0,0),(-1,-1),5)]))
        story.append(t_srv2)
        t_srv3 = Table(srv_rows, colWidths=[W*.55,W*.1,W*.175,W*.175])
        t_srv3.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eeeeee')),('GRID',(0,0),(-1,-2),0.3,colors.lightgrey),('LINEABOVE',(0,-1),(-1,-1),1.5,colors.black),('PADDING',(0,0),(-1,-1),5)]))
        story.append(t_srv3)

        story.append(Spacer(1,20))
        ass_s3 = ParagraphStyle('as3',fontSize=8,fontName='Helvetica',textColor=colors.grey,alignment=TA_CENTER)
        t_ass2 = Table([[HRFlowable(width=W*0.42,thickness=0.8,color=colors.black),"",HRFlowable(width=W*0.42,thickness=0.8,color=colors.black)],[Paragraph("Assinatura do responsável",ass_s3),"",Paragraph("Assinatura do cliente",ass_s3)]],colWidths=[W*0.42,W*0.16,W*0.42])
        t_ass2.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'BOTTOM')]))
        story.append(t_ass2)
        doc.build(story)
        from fastapi.responses import FileResponse
        return FileResponse(tmp.name, media_type="application/pdf",
                            filename=f"NF_{numero}.pdf",
                            headers={"Content-Disposition": f"inline; filename=NF_{numero}.pdf"})
    except ImportError:
        raise HTTPException(500, "Instale reportlab: pip install reportlab")

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
    import urllib.parse
    wpp_link = ""
    cli = o.get("cliente", {})
    tel = cli.get("tel", "").replace(" ","").replace("-","").replace("(","").replace(")","")
    if tel:
        if tel.startswith("0"): tel = "55" + tel[1:]
        elif not tel.startswith("55"): tel = "55" + tel
        nome = cli.get("nome", "cliente")
        tv   = o.get("tv", {})
        aparelho = (tv.get("marca","") + " " + tv.get("modelo","")).strip()
        servicos = o.get("servicos", [])
        total    = o.get("total", 0)
        palavras_mo = ["mao de obra","mão de obra","servico","serviço","diagnostico","diagnóstico","visita","reparo","conserto","instalacao","instalação"]

        if req.status == "Orcamento":
            mao_obra  = [s for s in servicos if any(p in s.get("desc","").lower() for p in palavras_mo)]
            materiais = [s for s in servicos if not any(p in s.get("desc","").lower() for p in palavras_mo)]
            linhas = ["Ola " + nome + "! Segue orcamento para sua TV " + aparelho + " OS #" + str(o["num"]) + ":"]
            if mao_obra:
                linhas.append("*Mao de obra:*")
                for s in mao_obra:
                    linhas.append("  - " + s.get("desc","") + " R$ " + f"{s.get('qtd',1)*s.get('val',0):.2f}")
            if materiais:
                linhas.append("*Materiais/Pecas:*")
                for s in materiais:
                    linhas.append("  - " + s.get("desc","") + " x" + str(s.get("qtd",1)) + " R$ " + f"{s.get('qtd',1)*s.get('val',0):.2f}")
            linhas.append("*Total: R$ " + f"{total:.2f}" + "*")
            linhas.append("Aguardamos sua aprovacao para prosseguir.")
            msg = "%0A".join(linhas)
            wpp_link = "https://wa.me/" + tel + "?text=" + urllib.parse.quote("\n".join(linhas))

        elif req.status == "Pronto":
            msg = "Ola " + nome + "! Sua TV " + aparelho + " OS #" + str(o["num"]) + " esta pronta para retirada! Entre em contato. 😊"
            wpp_link = "https://wa.me/" + tel + "?text=" + urllib.parse.quote(msg)

    return {"ok": True, "total": o["total"], "status": o.get("status"), "wpp_link": wpp_link}

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

class SyncPayload(BaseModel):
    ordens: List[dict]
    config: Optional[dict] = None

@app.post("/sync/upload")
def sync_upload(payload: SyncPayload, x_api_secret: str = Header(None)):
    if (x_api_secret or "").strip() != API_SECRET.strip():
        raise HTTPException(403, "Chave de sincronização inválida")
    for o in payload.ordens:
        _save_ordem(o)
    # Salvar config da empresa se enviada
    if payload.config:
        conn = get_db()
        conn.execute("INSERT INTO config (chave, dados) VALUES (?, ?) ON CONFLICT(chave) DO UPDATE SET dados=excluded.dados",
                     ("empresa", json.dumps(payload.config, ensure_ascii=False)))
        conn.commit()
        conn.close()
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
