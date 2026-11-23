"""Busca os boards do Monday e gera data.json (rodado pelo GitHub Actions)."""
import json, os, sys, urllib.request, urllib.parse, datetime, base64, hashlib, csv, io
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

BOARDS = [{"id": 18438251081, "mes": "2026-11", "nome": "NOVEMBRO"}]  # adicione outros meses aqui
COL = dict(cliente="cliente_mkm7jajr", valor="numeric_mm761qra", fat="dropdown_mm76r38a",
           entrega="status_1_mkm4ymtz", empresa="color_mm8tmszb", comercial="multi_selectbj3iv6f7",
           negocio="status_1_mkm71z9h", data="date", arquivos="arquivos_mkn1qwy4")

def gql(token, q, v=None):
    r = urllib.request.Request("https://api.monday.com/v2", method="POST",
        data=json.dumps({"query": q, "variables": v or {}}).encode(),
        headers={"Authorization": token, "Content-Type": "application/json", "API-Version": "2024-10"})
    d = json.load(urllib.request.urlopen(r, timeout=60))
    if "errors" in d: raise SystemExit(d["errors"])
    return d["data"]

Q1 = """query($id:[ID!],$ids:[String!]){boards(ids:$id){items_page(limit:500){cursor items{id name column_values(ids:$ids){id text}}}}}"""
Q2 = """query($c:String!,$ids:[String!]){next_items_page(limit:500,cursor:$c){cursor items{id name column_values(ids:$ids){id text}}}}"""

def fetch_items(token, board):
    ids = list(COL.values())
    d = gql(token, Q1, {"id": [board], "ids": ids})["boards"][0]["items_page"]
    items, cur = d["items"], d["cursor"]
    while cur:
        d = gql(token, Q2, {"c": cur, "ids": ids})["next_items_page"]
        items += d["items"]; cur = d["cursor"]
    return [{"pedido": i["name"], **{k: next((c["text"] for c in i["column_values"] if c["id"] == v), None)
            for k, v in COL.items()}} for i in items]

def num(x):
    try: return float(str(x).replace(",", ".")) if x else 0.0
    except ValueError: return 0.0

def classify(i):
    """faturado | a_faturar (entregue, ainda sem NF) | proximo_mes (ainda nao expedido/entregue) | cancelado | outros"""
    ent = (i["entrega"] or "").upper()
    if ent == "CANCELADO": return "cancelado"
    f = (i["fat"] or "").upper()
    if f == "SIM": return "faturado"
    if f == "OUTROS": return "outros"
    return "a_faturar" if ent == "ENTREGUE" else "proximo_mes"

def load_sheet(text):
    """CSV da planilha 'Lancamentos' -> {pedido: (detalhe[[campo,valor]], financeiro)}; coluna I = pedido, AV = FINANCEIRO."""
    rows = list(csv.reader(io.StringIO(text)))
    H = rows[0]; ip = H.index("N° DO PEDIDO"); fi = H.index("FINANCEIRO")
    out = {}
    for r in rows[1:]:
        if len(r) <= ip or not r[ip].strip(): continue
        det = [[h, v.strip()] for i, (h, v) in enumerate(zip(H, r))
               if i != fi and h != "Endereço IP" and v.strip() not in ("", "0")]
        out[r[ip].strip()] = (det, r[fi].strip() if len(r) > fi else "")
    return out

def decrypt(box, senha):
    key = PBKDF2HMAC(hashes.SHA256(), 32, base64.b64decode(box["salt"]), 200000).derive(senha.encode())
    return json.loads(AESGCM(key).decrypt(base64.b64decode(box["iv"]), base64.b64decode(box["ct"]), None))

def nfs(txt):
    """PDFs da coluna Arquivos do Monday = NF."""
    out = []
    for u in [x.strip() for x in (txt or "").split(", ") if x.strip().startswith("http")]:
        if u.lower().split("?")[0].endswith(".pdf"):
            out.append({"n": urllib.parse.unquote(u.rsplit("/", 1)[-1]), "u": u})
    return out

def build(items_by_month, sheet=None, old_det=None):
    sheet, old_det = sheet or {}, old_det or {}
    meses = []
    for m, items in items_by_month:
        rows = [{"pedido": i["pedido"], "cliente": i["cliente"] or "", "valor": num(i["valor"]),
                 "entrega": i["entrega"] or "(sem status)", "empresa": i["empresa"] or "(sem empresa)",
                 "comercial": i["comercial"] or "(sem comercial)", "situacao": classify(i), "nf": nfs(i.get("arquivos")),
                 **dict(zip(("detalhe", "financeiro"), sheet.get(i["pedido"]) or old_det.get(i["pedido"]) or ([], "")))} for i in items]
        meses.append({**m, "pedidos": rows})
    return {"atualizado_em": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "meses": meses}

def encrypt(obj, senha, h):
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(hashes.SHA256(), 32, salt, 200000).derive(senha.encode())
    ct = AESGCM(key).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode(), None)
    b = lambda x: base64.b64encode(x).decode()
    return {"v": 1, "h": h, "t": obj["atualizado_em"], "salt": b(salt), "iv": b(iv), "ct": b(ct)}

if __name__ == "__main__":
    tok, senha = os.environ["MONDAY_TOKEN"], os.environ["PAINEL_SENHA"]
    try: old = json.load(open("data.json", encoding="utf-8"))
    except Exception: old = {}
    try: prev = decrypt(old, senha)
    except Exception: prev = {"meses": []}
    old_det = {p["pedido"]: (p.get("detalhe", []), p.get("financeiro", "")) for m in prev["meses"] for p in m["pedidos"]}
    sheet = {}
    if os.environ.get("SHEET_CSV_URL"):
        sheet = load_sheet(urllib.request.urlopen(os.environ["SHEET_CSV_URL"], timeout=60).read().decode("utf-8"))
    out = build([(b, fetch_items(tok, b["id"])) for b in BOARDS], sheet, old_det)
    h = hashlib.sha256((json.dumps(out["meses"], sort_keys=True) + senha).encode()).hexdigest()
    age = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(old["t"])).total_seconds() if old.get("t") else 1e9
    if old.get("h") == h and age < 3600:
        print("sem mudancas"); sys.exit(0)
    json.dump(encrypt(out, senha, h), open("data.json", "w"))
    print("ok", sum(len(m["pedidos"]) for m in out["meses"]), "pedidos")
