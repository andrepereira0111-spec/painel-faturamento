"""Usado pela tarefa agendada do Claude: junta NFs lidas do Teams ao estado local e publica nf.json CRIPTOGRAFADO.
Uso:  python scripts/encrypt_nf.py --last-run   (imprime a data da ultima leitura)
      python scripts/encrypt_nf.py              (le nf_new.json, atualiza nf_state.json e grava nf.json)
A senha fica em ~/.painel_senha (arquivo local, fora do repositorio)."""
import json, os, re, sys, datetime, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_monday import encrypt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ST, NEW, OUT = (os.path.join(ROOT, f) for f in ("nf_state.json", "nf_new.json", "nf.json"))
state = json.load(open(ST, encoding="utf-8")) if os.path.exists(ST) else {"last_run": "2026-11-01T00:00:00Z", "nf": {}}
if "--last-run" in sys.argv:
    print(state["last_run"]); sys.exit(0)

RX = re.compile(r"^NF\s*0*(\d+)\b.*?(\d{2})\.(\d{2})\.(\d{4})", re.I)
def parse(e):
    m = RX.match(e["arquivo"].strip())
    return {"id": e.get("msg_id", "") + "|" + e["arquivo"], "numero": m.group(1) if m else "",
            "emissao": f"{m.group(4)}-{m.group(3)}-{m.group(2)}" if m else "",
            "arquivo": e["arquivo"], "url": e.get("url", ""), "texto": (e.get("texto") or "").strip()}

new = json.load(open(NEW, encoding="utf-8")) if os.path.exists(NEW) else []
for e in new:
    lst = state["nf"].setdefault(e["pedido"].strip(), [])
    p = parse(e)
    if not any(x["id"] == p["id"] for x in lst): lst.append(p)
state["last_run"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
json.dump(state, open(ST, "w", encoding="utf-8"), ensure_ascii=False)

senha = open(os.path.expanduser("~/.painel_senha"), encoding="utf-8").read().strip()
obj = {"atualizado_em": state["last_run"].replace("Z", "+00:00"), "nf": state["nf"]}
h = hashlib.sha256(json.dumps(state["nf"], sort_keys=True).encode()).hexdigest()
json.dump(encrypt(obj, senha, h), open(OUT, "w"))
if os.path.exists(NEW): os.remove(NEW)
print("NFs:", sum(len(v) for v in state["nf"].values()), "em", len(state["nf"]), "pedidos")
