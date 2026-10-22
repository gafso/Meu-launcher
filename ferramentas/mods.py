#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mods de imagem do jogo (mapa, fundos, tela de carregamento, castelo) SEM faltar tile.

Por que sempre faltava tile: o jogo só pede um tile quando você passa por perto, então o
_pedidos.txt só tem os tiles que você já viu. Esta ferramenta gera a GRADE INTEIRA do mapa
(todos os X,Y), inclusive os que você nunca visitou, e confere tudo no final.

Comandos (rodam na pasta onde estão _pedidos.txt e personalizados/):
  preparar              acha _pedidos.txt/_faltando.txt e copia para a raiz
  analisar              lista mapas (grade, tiles vistos/faltando) e as outras imagens pedidas
  baixar                baixa os originais, monta o mapa inteiro para editar e gera folhas de miniaturas (catalogo/)
  gerar                 aplica o que estiver em personalizados/  ->  saida_mods/mods/...
  castelo               troca os 2 fundos do castelo dentro do swf (personalizados/fortaleza_gelo.png e fortaleza_fogo.png)
  verificar             confere se não falta nenhum tile/arquivo e se os tamanhos batem

Nomes em personalizados/:
  mapa_<ID>.png|jpg     imagem do mapa INTEIRO (qualquer tamanho; é esticada para a grade)
  <nome>.png|jpg        troca a imagem pedida com esse nome (sem hash/extensão), ex.: loading_bg.jpg
  <pasta>__<nome>.png   igual, mas só na pasta indicada (quando o nome se repete em pastas)
Requer: pip install pillow
"""
import argparse
import os
import re
import shutil
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import urllib.request

from PIL import Image

Image.MAX_IMAGE_PIXELS = None
UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"
IMG = (".jpg", ".jpeg", ".png")
TILE_RE = re.compile(r"^tile_(\d+)_(\d+)(?:_[0-9A-Za-z]+)?\.(jpg|jpeg|png)$", re.I)
HASH_RE = re.compile(r"_[0-9a-fA-F]{8}(\.[A-Za-z0-9]+)$")
PASTA_OK = re.compile(r"^[A-Za-z0-9_\-]+$")

ORIG, SAIDA, PERS = "originais", "saida_mods", "personalizados"
MODS = os.path.join(SAIDA, "mods")
EDITAR = os.path.join(SAIDA, "editar")


# ----------------------------------------------------------------- leitura dos pedidos
def ler_lista(arq, base=None):
    itens, vistos = [], set()
    if not os.path.exists(arq):
        return itens
    for ln in open(arq, encoding="utf-8", errors="ignore"):
        ln = ln.strip().split("?")[0].split("#")[0]
        if not ln or ln in vistos:
            continue
        vistos.add(ln)
        url = ln
        if not re.match(r"^(https?|file)://", ln):
            if not base:
                continue
            url = base.rstrip("/") + "/" + ln.lstrip("/")
        partes = url.split("/")
        nome = partes[-1]
        pasta = partes[-2] if len(partes) >= 5 else ""
        itens.append({"url": url, "pasta": pasta, "nome": nome,
                      "ext": os.path.splitext(nome)[1].lower(), "dir": "/".join(partes[:-1])})
    return itens


def carregar(args):
    itens = ler_lista(args.lista, args.base)
    nomes = {i["url"] for i in itens}
    for i in ler_lista(args.faltando, args.base):      # tiles que o app anotou como faltantes
        if i["url"] not in nomes:
            itens.append(i)
    return itens


def parse_grade(txt, pasta):
    """'30x20' vale para todos; '10000=30x20,10010=18x12' vale por mapa."""
    if not txt:
        return None
    for parte in txt.split(","):
        parte = parte.strip()
        if "=" in parte:
            k, v = parte.split("=", 1)
            if k.strip() != pasta:
                continue
        else:
            v = parte
        m = re.match(r"^(\d+)\s*[xX]\s*(\d+)$", v.strip())
        if m:
            return int(m[1]), int(m[2])
    return None


def filtro_mapas(args):
    """Se o campo 'grade' tiver ID=CxR (ex.: 10000=30x20), só esses mapas são processados."""
    ids = set()
    for parte in (args.grade or "").split(","):
        if "=" in parte:
            ids.add(parte.split("=", 1)[0].strip())
    return ids or None


def nomes_personalizados():
    nomes = set()
    if os.path.isdir(PERS):
        for f in os.listdir(PERS):
            if f.lower().endswith(IMG) and not f.lower().startswith("mapa_"):
                st = os.path.splitext(f)[0]
                nomes.add(st.split("__", 1)[1].lower() if "__" in st else st.lower())
    return nomes


def mapas_de(itens):
    mapas = {}
    for i in itens:
        m = TILE_RE.match(i["nome"])
        if m and PASTA_OK.match(i["pasta"]):
            mapas.setdefault(i["pasta"], {})[(int(m[1]), int(m[2]))] = i
    return mapas


def grade_de(tiles, args, pasta):
    g = parse_grade(args.grade, pasta)
    if g:
        return g
    return max(x for x, _ in tiles) + 1, max(y for _, y in tiles) + 1


# ----------------------------------------------------------------- originais
def dir_orig(pasta):
    return os.path.join(ORIG, pasta or "_raiz")


def arquivo_orig(item):
    return os.path.join(dir_orig(item["pasta"]), item["nome"])


def baixar_url(url, destino, tentativas=3, quieto=False):
    if os.path.exists(destino) and os.path.getsize(destino) > 0:
        return True
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    erro = None
    for _ in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                dados = r.read()
            tmp = destino + ".part"
            with open(tmp, "wb") as f:
                f.write(dados)
            if destino.lower().endswith(IMG):
                with Image.open(tmp) as im:
                    im.verify()
            os.replace(tmp, destino)
            return True
        except Exception as e:                       # noqa: BLE001
            erro = e
            if os.path.exists(destino + ".part"):
                os.remove(destino + ".part")
    if not quieto:
        print(f"  falhou: {url}  ({erro})")
    return False


def tiles_originais(pasta):
    """(x,y) -> caminho do arquivo baixado (prefere o que tem hash, que é o pedido de verdade)."""
    res = {}
    d = dir_orig(pasta)
    if not os.path.isdir(d):
        return res
    for f in sorted(os.listdir(d)):
        m = TILE_RE.match(f)
        if m:
            k = (int(m[1]), int(m[2]))
            if k not in res or HASH_RE.search(f):
                res[k] = os.path.join(d, f)
    return res


def info_mapa(pasta, args, tiles_pedidos):
    orig = tiles_originais(pasta)
    chaves = set(tiles_pedidos) | set(orig)
    if not chaves:
        sys.exit(f"Mapa {pasta}: nenhum tile conhecido. Rode 'baixar' antes (ou jogue e suba o _pedidos.txt).")
    cols, rows = grade_de(chaves, args, pasta)
    tams = Counter()
    for p in orig.values():
        with Image.open(p) as im:
            tams[im.size] += 1
    if args.tam:
        m = re.match(r"^(\d+)\s*[xX]\s*(\d+)$", args.tam)
        tw, th = int(m[1]), int(m[2])
    elif tams:
        (tw, th), _ = tams.most_common(1)[0]
    else:
        sys.exit(f"Mapa {pasta}: sem tiles baixados para medir o tamanho. Use --tam 256x256 ou rode 'baixar'.")
    exts = Counter(os.path.splitext(p)[1].lower() for p in orig.values())
    ext = exts.most_common(1)[0][0] if exts else ".jpg"
    return {"orig": orig, "cols": cols, "rows": rows, "tw": tw, "th": th, "ext": ext}


# ----------------------------------------------------------------- comandos
def cmd_preparar(args):
    """Acha _pedidos.txt / _faltando.txt em qualquer pasta do repositório e copia para a raiz."""
    for nome in ("_pedidos.txt", "_faltando.txt"):
        achados = []
        for raiz, dirs, files in os.walk("."):
            dirs[:] = [d for d in dirs if d not in (".git", "_proj", SAIDA, ORIG)]
            if nome in files:
                achados.append(os.path.join(raiz, nome))
        if achados:
            achados.sort(key=lambda p: (p.count(os.sep), p))
            if os.path.abspath(achados[0]) != os.path.abspath(nome):
                shutil.copyfile(achados[0], nome)
            print(f"{nome}: usando {achados[0]}")
        elif nome == "_pedidos.txt":
            sys.exit("ERRO: suba o _pedidos.txt (de Android/data/<app>/files/mods/) para a raiz do repositório.")


def cmd_catalogo(args):
    """Folhas de miniaturas (com nome e tamanho) de todas as imagens baixadas, para você ver qual é qual."""
    from PIL import ImageDraw
    CW, CH, COLS, LIN = 230, 200, 5, 4
    pasta_cat = os.path.join(SAIDA, "catalogo")
    os.makedirs(pasta_cat, exist_ok=True)
    total = 0
    if not os.path.isdir(ORIG):
        return
    for pasta in sorted(os.listdir(ORIG)):
        d = os.path.join(ORIG, pasta)
        arqs = [f for f in sorted(os.listdir(d)) if f.lower().endswith(IMG) and not TILE_RE.match(f)]
        for n in range(0, len(arqs), COLS * LIN):
            folha = Image.new("RGB", (COLS * CW, LIN * CH), (40, 40, 48))
            dr = ImageDraw.Draw(folha)
            for k, f in enumerate(arqs[n:n + COLS * LIN]):
                cx, cy = (k % COLS) * CW, (k // COLS) * CH
                try:
                    with Image.open(os.path.join(d, f)) as im:
                        tam = im.size
                        im = im.convert("RGBA")
                        im.thumbnail((CW - 10, CH - 40))
                        fundo = Image.new("RGBA", im.size, (110, 110, 118, 255))
                        fundo.alpha_composite(im)
                        folha.paste(fundo.convert("RGB"), (cx + 5, cy + 5))
                except Exception:                                  # noqa: BLE001
                    tam = (0, 0)
                dr.text((cx + 5, cy + CH - 32), f[:34], fill=(255, 255, 255))
                dr.text((cx + 5, cy + CH - 18), f"{tam[0]}x{tam[1]}", fill=(255, 220, 120))
            folha.save(os.path.join(pasta_cat, f"{pasta}_{n // (COLS * LIN) + 1}.jpg"), quality=80)
            total += 1
    print(f"catalogo: {total} folha(s) de miniaturas em {pasta_cat}")


def cmd_analisar(args):
    itens = carregar(args)
    if not itens:
        sys.exit(f"Nenhum pedido em {args.lista}. Jogue com o app, copie mods/_pedidos.txt para a raiz do repositório.")
    mapas = mapas_de(itens)
    linhas = []
    for pasta, tiles in sorted(mapas.items()):
        cols, rows = grade_de(tiles, args, pasta)
        total = cols * rows
        faltam = total - len(tiles)
        linhas.append(f"MAPA {pasta}: {len(tiles)} tiles vistos, grade {cols}x{rows} ({total} no total), "
                      f"{faltam} nunca vistos (a ferramenta gera todos)")
        if not parse_grade(args.grade, pasta):
            linhas.append(f"   aviso: grade deduzida só dos tiles vistos; se o mapa for maior, informe (ex.: {pasta}=30x20)")
    outros = {}
    for i in itens:
        if TILE_RE.match(i["nome"]) and PASTA_OK.match(i["pasta"]):
            continue
        outros.setdefault(i["pasta"] or "(raiz)", []).append(i)
    linhas.append("")
    linhas.append("OUTROS ARQUIVOS PEDIDOS (candidatos a fundo / carregamento / castelo):")
    for pasta, lst in sorted(outros.items()):
        imgs = [i["nome"] for i in lst if i["ext"] in IMG]
        outr = len(lst) - len(imgs)
        linhas.append(f" [{pasta}] {len(imgs)} imagem(ns), {outr} outro(s) (swf/dados: não trocáveis aqui)")
        for n in sorted(imgs)[:60]:
            linhas.append(f"      {n}")
    texto = "\n".join(linhas)
    print(texto)
    os.makedirs(SAIDA, exist_ok=True)
    with open(os.path.join(SAIDA, "relatorio.txt"), "w", encoding="utf-8") as f:
        f.write(texto + "\n")


def cmd_baixar(args, montar=True):
    itens = carregar(args)
    filtro = filtro_mapas(args)
    pers = nomes_personalizados() if filtro else None
    imgs = []
    for i in itens:
        if i["ext"] not in IMG:
            continue
        eh_tile = bool(TILE_RE.match(i["nome"])) and bool(PASTA_OK.match(i["pasta"]))
        if filtro:
            if eh_tile:
                if i["pasta"] not in filtro:
                    continue
            else:
                base = os.path.splitext(HASH_RE.sub(r"\1", i["nome"]))[0].lower()
                if base not in pers and os.path.splitext(i["nome"])[0].lower() not in pers:
                    continue
        imgs.append(i)
    if filtro:
        print(f"Só os mapas {', '.join(sorted(filtro))} (e as imagens de personalizados/) serão processados.")
    print(f"Baixando {len(imgs)} imagem(ns) pedidas...")
    with ThreadPoolExecutor(8) as ex:
        ok = list(ex.map(lambda i: baixar_url(i["url"], arquivo_orig(i)), imgs))
    print(f"  {sum(ok)}/{len(imgs)} ok")
    # tiles nunca vistos: tenta sem hash (alguns servidores aceitam)
    mapas = {p: t for p, t in mapas_de(itens).items() if not filtro or p in filtro}
    for pasta, tiles in mapas.items():
        cols, rows = grade_de(tiles, args, pasta)
        faltam = [(x, y) for y in range(rows) for x in range(cols) if (x, y) not in tiles]
        if not faltam:
            continue
        ref = next(iter(tiles.values()))
        ext = os.path.splitext(ref["nome"])[1]
        x0, y0 = faltam[0]
        sonda = f"{ref['dir']}/tile_{x0}_{y0}{ext}"
        if not baixar_url(sonda, os.path.join(dir_orig(pasta), f"tile_{x0}_{y0}{ext}"), tentativas=1, quieto=True):
            print(f"  mapa {pasta}: o servidor não entrega tile sem hash; {len(faltam)} tiles nunca vistos "
                  f"não têm original (serão gerados só a partir da sua imagem).")
            continue
        print(f"  mapa {pasta}: baixando {len(faltam)} tiles nunca vistos (sem hash)...")
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(lambda k: baixar_url(f"{ref['dir']}/tile_{k[0]}_{k[1]}{ext}",
                                             os.path.join(dir_orig(pasta), f"tile_{k[0]}_{k[1]}{ext}"),
                                             tentativas=1, quieto=True), faltam))
    if montar:
        for pasta, tiles in mapas.items():
            cmd_juntar(args, pasta, tiles)


def cmd_juntar(args, pasta, tiles_pedidos=None):
    if tiles_pedidos is None:
        tiles_pedidos = mapas_de(carregar(args)).get(pasta, {})
    inf = info_mapa(pasta, args, tiles_pedidos)
    tw, th, cols, rows = inf["tw"], inf["th"], inf["cols"], inf["rows"]
    grande = Image.new("RGB", (cols * tw, rows * th))
    soma, n, sem = [0, 0, 0], 0, []
    for y in range(rows):
        for x in range(cols):
            p = inf["orig"].get((x, y))
            if not p:
                sem.append((x, y))
                continue
            with Image.open(p) as im:
                im = im.convert("RGB")
                grande.paste(im, (x * tw, y * th))
                px = im.resize((1, 1), Image.BOX).getpixel((0, 0))
                soma = [a + b for a, b in zip(soma, px)]
                n += 1
    if sem and n:
        cor = tuple(int(v / n) for v in soma)
        for x, y in sem:
            grande.paste(cor, (x * tw, y * th, (x + 1) * tw, (y + 1) * th))
    os.makedirs(EDITAR, exist_ok=True)
    destino = os.path.join(EDITAR, f"mapa_{pasta}_original.png")
    grande.save(destino, compress_level=3)
    prev = grande.copy()
    prev.thumbnail((2400, 2400))
    prev.save(os.path.join(EDITAR, f"mapa_{pasta}_previa.jpg"), quality=85)
    print(f"mapa {pasta}: {grande.size[0]}x{grande.size[1]} ({cols}x{rows} tiles de {tw}x{th}); "
          f"{len(sem)} tile(s) sem original (cor média) -> {destino}")


def _preencher_jpeg(dados, alvo):
    """Completa o JPEG com segmentos COM (comentário, válidos) logo após o SOI até ter 'alvo' bytes."""
    falta = alvo - len(dados)
    if falta <= 0 or dados[:2] != b"\xff\xd8":
        return dados
    blocos = b""
    while falta > 0:
        n = min(falta, 65535)
        if n < 4:                      # um COM precisa de 4 bytes no mínimo
            n = 4
        blocos += b"\xff\xfe" + (n - 2).to_bytes(2, "big") + b"\0" * (n - 4)
        falta -= n
    return dados[:2] + blocos + dados[2:]


def _preencher_png(dados, alvo):
    """Completa o PNG com um chunk tEXt (ignorado pelo leitor) antes do IEND."""
    import zlib
    falta = alvo - len(dados)
    if falta < 12 or dados[-12:-8] != b"\0\0\0\0" or dados[-8:-4] != b"IEND":
        return dados
    corpo = b"pad\0" + b"0" * (falta - 12 - 4)
    chunk = len(corpo).to_bytes(4, "big") + b"tEXt" + corpo + zlib.crc32(b"tEXt" + corpo).to_bytes(4, "big")
    return dados[:-12] + chunk + dados[-12:]


def salvar_img(im, destino, ext, alvo=None):
    """Salva a imagem. Se 'alvo' (bytes do arquivo original) for dado, ajusta o tamanho do arquivo para ele:
    o jogo recusa o mod quando o tamanho difere do original em 3000 bytes ou mais e baixa o original."""
    import io
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    buf = io.BytesIO()
    if ext in (".jpg", ".jpeg"):
        for q in ((92, 85, 78, 70, 60, 50, 40, 30, 20, 10) if alvo else (92,)):
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=q, subsampling=0 if q >= 85 else 2)
            if not alvo or buf.tell() <= alvo:
                break
        dados = buf.getvalue()
        if alvo:
            dados = _preencher_jpeg(dados, alvo)
    else:
        im.save(buf, "PNG", optimize=bool(alvo))
        dados = buf.getvalue()
        if alvo:
            dados = _preencher_png(dados, alvo)
    if alvo and abs(len(dados) - alvo) >= 3000:
        print(f"  AVISO: {os.path.basename(destino)} ficou com {len(dados)} bytes (original {alvo}); "
              f"o jogo pode recusar. Use uma imagem mais simples/menos detalhada.")
    with open(destino, "wb") as f:
        f.write(dados)


def cmd_fatiar(args, pasta, imagem, tiles_pedidos=None):
    if tiles_pedidos is None:
        tiles_pedidos = mapas_de(carregar(args)).get(pasta, {})
    inf = info_mapa(pasta, args, tiles_pedidos)
    tw, th, cols, rows, orig = inf["tw"], inf["th"], inf["cols"], inf["rows"], inf["orig"]
    img = Image.open(imagem).convert("RGB")
    alvo = (cols * tw, rows * th)
    if img.size != alvo:
        r1, r2 = img.size[0] / img.size[1], alvo[0] / alvo[1]
        aviso = "  (proporção diferente: a imagem será esticada!)" if abs(r1 - r2) / r2 > 0.02 else ""
        print(f"mapa {pasta}: ajustando {img.size[0]}x{img.size[1]} -> {alvo[0]}x{alvo[1]}{aviso}")
        img = img.resize(alvo, Image.LANCZOS)
    n = 0
    for y in range(rows):
        for x in range(cols):
            w, h, ext = tw, th, inf["ext"]
            if (x, y) in orig:
                with Image.open(orig[(x, y)]) as o:
                    w, h = min(o.size[0], tw), min(o.size[1], th)
                ext = os.path.splitext(orig[(x, y)])[1].lower()
            c = img.crop((x * tw, y * th, x * tw + w, y * th + h))
            salvar_img(c, os.path.join(MODS, pasta, f"tile_{x}_{y}{ext}"), ext,
                       os.path.getsize(orig[(x, y)]) if (x, y) in orig else None)
            n += 1
    print(f"mapa {pasta}: {n} tiles gravados em {os.path.join(MODS, pasta)} (grade completa {cols}x{rows})")


def achar_originais(itens, nome, pasta_dica=None):
    """Acha os arquivos pedidos que correspondem ao nome dado (sem hash/extensão)."""
    alvo = nome.lower()
    exatos, parciais = [], []
    for i in itens:
        if i["ext"] not in IMG or (TILE_RE.match(i["nome"]) and PASTA_OK.match(i["pasta"])):
            continue
        if pasta_dica and i["pasta"].lower() != pasta_dica.lower():
            continue
        base = os.path.splitext(HASH_RE.sub(r"\1", i["nome"]))[0].lower()
        if alvo in (base, i["nome"].lower(), os.path.splitext(i["nome"])[0].lower()):
            exatos.append(i)
        elif alvo in i["nome"].lower():
            parciais.append(i)
    return exatos or parciais


def cmd_trocar(args, nome, imagem, itens=None, pasta_dica=None):
    itens = itens if itens is not None else carregar(args)
    achados = achar_originais(itens, nome, pasta_dica)
    if not achados:
        print(f"'{nome}': nenhuma imagem pedida com esse nome (veja 'analisar').")
        return 0
    if len(achados) > 6:
        print(f"'{nome}': {len(achados)} arquivos combinam; seja mais específico (ex.: pasta__nome.png).")
        return 0
    feitos = 0
    for i in achados:
        o = arquivo_orig(i)
        if not os.path.exists(o):
            print(f"'{i['nome']}': original não baixado (rode 'baixar').")
            continue
        with Image.open(o) as orig:
            tam, ext = orig.size, i["ext"]
            tem_alpha = orig.mode in ("RGBA", "LA") or "transparency" in orig.info
        novo = Image.open(imagem)
        novo = novo.convert("RGBA" if (ext == ".png" and tem_alpha) else "RGB")
        modo = args.ajuste
        if modo == "esticar" or novo.size == tam:
            res = novo.resize(tam, Image.LANCZOS) if novo.size != tam else novo
        else:
            k = max(tam[0] / novo.size[0], tam[1] / novo.size[1]) if modo == "cobrir" \
                else min(tam[0] / novo.size[0], tam[1] / novo.size[1])
            nv = novo.resize((max(1, round(novo.size[0] * k)), max(1, round(novo.size[1] * k))), Image.LANCZOS)
            fundo = Image.new(nv.mode, tam, (0, 0, 0, 0) if nv.mode == "RGBA" else (0, 0, 0))
            fundo.paste(nv, ((tam[0] - nv.size[0]) // 2, (tam[1] - nv.size[1]) // 2))
            res = fundo
        salvar_img(res, os.path.join(MODS, i["pasta"] or "", i["nome"]), ext, os.path.getsize(o))
        print(f"trocado: {i['pasta']}/{i['nome']}  ({tam[0]}x{tam[1]}, {ext[1:]})")
        feitos += 1
    return feitos


def cmd_gerar(args):
    itens = carregar(args)
    if not itens:
        sys.exit(f"Sem pedidos em {args.lista}.")
    if not os.path.isdir(PERS) or not [f for f in os.listdir(PERS) if f.lower().endswith(IMG)]:
        sys.exit(f"Coloque suas imagens em {PERS}/ (mapa_<ID>.png ou <nome da imagem>.png).")
    mapas = mapas_de(itens)
    for f in sorted(os.listdir(PERS)):
        if not f.lower().endswith(IMG):
            continue
        caminho = os.path.join(PERS, f)
        stem = os.path.splitext(f)[0]
        m = re.match(r"^mapa_(.+)$", stem, re.I)
        if m:
            pasta = m[1]
            if pasta not in mapas:
                print(f"{f}: mapa '{pasta}' não aparece nos pedidos (mapas: {', '.join(sorted(mapas)) or 'nenhum'}).")
                continue
            cmd_fatiar(args, pasta, caminho, mapas[pasta])
            continue
        pasta_dica = None
        if "__" in stem:
            pasta_dica, stem = stem.split("__", 1)
        if cmd_trocar(args, stem, caminho, itens, pasta_dica) == 0:
            print(f"{f}: nada foi trocado.")


# ----------------------------------------------------------------- verificação (espelha o app)
def achar_mod(item):
    """Mesma regra do SwfFixer.modFor do app."""
    nome, pasta = item["nome"], item["pasta"]
    dirs = []
    if PASTA_OK.match(pasta):
        dirs.append(os.path.join(MODS, pasta))
    cands = []
    m = TILE_RE.match(nome)
    for d in dirs:
        cands += [os.path.join(d, nome), os.path.join(d, HASH_RE.sub(r"\1", nome))]
        if m:
            cands += [os.path.join(d, f"tile_{m[1]}_{m[2]}.{e}") for e in ("jpg", "png", "jpeg")]
    if not m:
        cands += [os.path.join(MODS, nome), os.path.join(MODS, HASH_RE.sub(r"\1", nome))]
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def cmd_verificar(args):
    itens = [i for i in carregar(args) if i["ext"] in IMG]
    if not os.path.isdir(MODS):
        sys.exit("Ainda não há saida_mods/mods. Rode 'gerar' antes.")
    problemas, ok, sem_mod = [], 0, 0
    pastas_com_mod = {p for p in os.listdir(MODS) if os.path.isdir(os.path.join(MODS, p))}
    for pasta, tiles in sorted(mapas_de(itens).items()):
        if pasta not in pastas_com_mod:
            continue
        cols, rows = grade_de(tiles, args, pasta)
        faltam = [(x, y) for y in range(rows) for x in range(cols)
                  if not any(os.path.isfile(os.path.join(MODS, pasta, f"tile_{x}_{y}.{e}")) for e in ("jpg", "png", "jpeg"))]
        sem_pedido_na_grade = [k for k in tiles if k[0] >= cols or k[1] >= rows]
        print(f"mapa {pasta}: {cols * rows - len(faltam)}/{cols * rows} tiles da grade com mod"
              + (" -> COMPLETO" if not faltam and not sem_pedido_na_grade else ""))
        for k in faltam[:20]:
            problemas.append(f"FALTA tile_{k[0]}_{k[1]} no mapa {pasta}")
        for (x, y), it in sorted(tiles.items()):
            m = achar_mod(it)
            o = arquivo_orig(it)
            if m and os.path.exists(o) and abs(os.path.getsize(m) - os.path.getsize(o)) >= 3000:
                problemas.append(f"BYTES tile_{x}_{y} mapa {pasta}: original {os.path.getsize(o)}, mod {os.path.getsize(m)} (o jogo recusa)")
        for k in sem_pedido_na_grade:
            problemas.append(f"tile {k} pedido fora da grade {cols}x{rows} do mapa {pasta} (aumente a grade)")
    for i in itens:
        if TILE_RE.match(i["nome"]) and PASTA_OK.match(i["pasta"]):
            continue
        mod = achar_mod(i)
        if not mod:
            sem_mod += 1
            continue
        o = arquivo_orig(i)
        if os.path.exists(o):
            with Image.open(o) as a, Image.open(mod) as b:
                if a.size != b.size:
                    problemas.append(f"TAMANHO {i['pasta']}/{i['nome']}: original {a.size}, mod {b.size}")
                    continue
        ok += 1
    print(f"imagens avulsas: {ok} com mod, {sem_mod} sem mod (ficam originais)")
    if problemas:
        print("\nPROBLEMAS:")
        for p in problemas:
            print("  " + p)
    else:
        print("\nTUDO CERTO: nenhum tile faltando e todos os tamanhos conferem.")
    with open(os.path.join(SAIDA, "verificacao.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(problemas) if problemas else "OK\n")
    return 1 if problemas else 0



# ----------------------------------------------------------------- SWF (castelo etc.)
FFDEC_URL = "https://github.com/jindrapetrik/jpexs-decompiler/releases/download/version21.1.1/ffdec_21.1.1.zip"
SWF_PADRAO = [
    "https://res1011oas.creaction-network.com/ui/zh_cn/swf/castlemap1_95ecebc3.swf",
    "https://res1011oas.creaction-network.com/ui/zh_cn/swf/castle_898a87b9.swf",
    "https://res1011oas.creaction-network.com/swf/castle/npc/castlenpc.swf",
]


def garantir_ffdec():
    import subprocess
    jar = os.path.join("ffdec", "ffdec.jar")
    if os.path.exists(jar):
        return jar
    os.makedirs("ffdec", exist_ok=True)
    zp = os.path.join("ffdec", "f.zip")
    print("baixando o decompilador de SWF (ffdec)...")
    urllib.request.urlretrieve(FFDEC_URL, zp)
    subprocess.run(["unzip", "-q", "-o", zp, "-d", "ffdec"], check=True)
    return jar


def cmd_swf(args):
    """Baixa os SWF (por padrao os do castelo), extrai as imagens e lista as classes, para saber o que e cada um."""
    import subprocess
    from PIL import ImageDraw
    jar = garantir_ffdec()
    urls = args.swf.split() if getattr(args, "swf", "") else SWF_PADRAO
    for url in urls:
        nome = url.split("?")[0].split("/")[-1]
        base = os.path.splitext(nome)[0]
        dest = os.path.join(ORIG, "swf", nome)
        if not baixar_url(url, dest):
            continue
        saida = os.path.join(SAIDA, "swf", base)
        shutil.rmtree(saida, ignore_errors=True)
        os.makedirs(saida, exist_ok=True)
        print(f"\n=== {nome}: {os.path.getsize(dest)} bytes ===")
        cmd = ["java", "-Djava.awt.headless=true", "-jar", jar]
        subprocess.run(cmd + ["-export", "image", os.path.join(saida, "imagens"), dest],
                       capture_output=True, text=True, timeout=600)
        subprocess.run(cmd + ["-export", "script", os.path.join(saida, "scripts"), dest],
                       capture_output=True, text=True, timeout=600)
        classes = []
        for raiz, _, files in os.walk(os.path.join(saida, "scripts")):
            for f in files:
                classes.append(os.path.relpath(os.path.join(raiz, f), os.path.join(saida, "scripts")))
        with open(os.path.join(saida, "classes.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(classes)))
        print(f"  classes/scripts: {len(classes)} (ex.: {', '.join(sorted(classes)[:6])})")
        imgs = []
        d = os.path.join(saida, "imagens")
        if os.path.isdir(d):
            imgs = sorted((f for f in os.listdir(d) if f.lower().endswith(IMG)),
                          key=lambda f: -os.path.getsize(os.path.join(d, f)))
        print(f"  imagens: {len(imgs)}")
        CW, CH, COLS, LIN = 230, 200, 5, 4
        for n in range(0, len(imgs), COLS * LIN):
            folha = Image.new("RGB", (COLS * CW, LIN * CH), (40, 40, 48))
            dr = ImageDraw.Draw(folha)
            for k, f in enumerate(imgs[n:n + COLS * LIN]):
                cx, cy = (k % COLS) * CW, (k // COLS) * CH
                try:
                    with Image.open(os.path.join(d, f)) as im:
                        tam = im.size
                        im = im.convert("RGBA")
                        im.thumbnail((CW - 10, CH - 40))
                        fundo = Image.new("RGBA", im.size, (110, 110, 118, 255))
                        fundo.alpha_composite(im)
                        folha.paste(fundo.convert("RGB"), (cx + 5, cy + 5))
                except Exception:                                  # noqa: BLE001
                    tam = (0, 0)
                dr.text((cx + 5, cy + CH - 32), f"id {os.path.splitext(f)[0]}"[:34], fill=(255, 255, 255))
                dr.text((cx + 5, cy + CH - 18), f"{tam[0]}x{tam[1]}", fill=(255, 220, 120))
            folha.save(os.path.join(saida, f"folha_{n // (COLS * LIN) + 1}.jpg"), quality=80)
        for f in imgs[:8]:
            try:
                with Image.open(os.path.join(d, f)) as im:
                    print(f"    id {os.path.splitext(f)[0]}: {im.size[0]}x{im.size[1]}")
            except Exception:                                      # noqa: BLE001
                pass
        shutil.rmtree(os.path.join(saida, "scripts"), ignore_errors=True)   # so a lista de classes interessa


def cmd_castelo(args):
    """Troca os 2 fundos do castelo (InnerCityBgAsset) DENTRO do swf e gera o swf modificado em saida_mods/mods/.
    Usa personalizados/fortaleza_gelo.(png|jpg) = fundo nevado (id menor) e fortaleza_fogo.(png|jpg) = 2o fundo (id maior)."""
    import subprocess
    jar = garantir_ffdec()
    imgs = {}
    if os.path.isdir(PERS):
        for chave in ("gelo", "fogo"):
            for f in sorted(os.listdir(PERS)):
                if f.lower().startswith("fortaleza_" + chave) and f.lower().endswith(IMG):
                    imgs[chave] = os.path.join(PERS, f)
                    break
    if not imgs:
        print("ERRO: coloque fortaleza_gelo.png e/ou fortaleza_fogo.png na pasta personalizados/ do repositorio.")
        sys.exit(1)
    print("imagens novas:", ", ".join(f"{k}={v}" for k, v in imgs.items()))
    tmp = os.path.join(SAIDA, "_tmp_castelo")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    os.makedirs(MODS, exist_ok=True)
    urls = args.swf.split() if getattr(args, "swf", "") else SWF_PADRAO
    java = ["java", "-Djava.awt.headless=true", "-jar", jar]
    relatorio, feitos = [], 0

    def fundos(pasta):
        achados = []
        if os.path.isdir(pasta):
            for f in os.listdir(pasta):
                m = re.match(r"^(\d+)_.*InnerCityBg", f)
                if m:
                    achados.append((int(m.group(1)), f))
        return sorted(achados)

    for url in urls:
        nome = url.split("?")[0].split("/")[-1]
        base = os.path.splitext(nome)[0]
        dest = os.path.join(ORIG, "swf", nome)
        if not baixar_url(url, dest):
            relatorio.append(f"{nome}: nao baixou")
            continue
        exp = os.path.join(tmp, base + "_orig")
        subprocess.run(java + ["-export", "image", exp, dest], capture_output=True, text=True, timeout=600)
        achados = fundos(exp)
        if not achados:
            print(f"{nome}: sem InnerCityBg (pulando)")
            continue
        print(f"{nome}: fundos encontrados: {[f for _, f in achados]}")
        pares = []
        for (idn, f), chave in zip(achados, ("gelo", "fogo")):
            if chave not in imgs:
                continue
            tam = Image.open(os.path.join(exp, f)).size
            im = Image.open(imgs[chave]).convert("RGB")
            if im.size != tam:
                im = im.resize(tam, Image.LANCZOS)
            jpg = os.path.join(tmp, f"{base}_{idn}.jpg")
            im.save(jpg, quality=92)
            pares += [str(idn), jpg]
        saida = os.path.join(MODS, nome)
        r = subprocess.run(java + ["-replace", dest, saida] + pares, capture_output=True, text=True, timeout=900)
        print((r.stdout or "")[-600:], (r.stderr or "")[-600:])
        if not os.path.exists(saida) or os.path.getsize(saida) == 0:
            relatorio.append(f"{nome}: FALHOU ao gerar o swf")
            continue
        # confere: reexporta do swf novo e compara com o original
        chk = os.path.join(tmp, base + "_novo")
        subprocess.run(java + ["-export", "image", chk, saida], capture_output=True, text=True, timeout=600)
        novos = dict(fundos(chk))
        for idn, f in achados:
            a = os.path.join(exp, f)
            b = os.path.join(chk, novos[idn]) if idn in novos else None
            mudou = bool(b) and open(a, "rb").read() != open(b, "rb").read()
            relatorio.append(f"{nome} id {idn}: {'TROCADO' if mudou else 'IGUAL ao original (nao trocou)'}")
        feitos += 1
        print(f"{nome}: original {os.path.getsize(dest)} bytes -> novo {os.path.getsize(saida)} bytes")
    shutil.rmtree(tmp, ignore_errors=True)
    txt = ["RESULTADO castelo:"] + relatorio
    txt.append("")
    txt.append("Copie o(s) .swf de mods/ para Android/data/<pacote>/files/mods/ , apague o cache do jogo e reinicie o app.")
    with open(os.path.join(SAIDA, "castelo_resultado.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(txt))
    print("\n".join(txt))
    if feitos == 0:
        sys.exit(1)


PREDIOS_PADRAO = [
    "https://res1011oas.creaction-network.com/images/neizhengting_425254ff.swf",      # Prefeitura
    "https://res1011oas.creaction-network.com/images/bojinshiyanshi_92701ed3.swf",    # Laboratorio de Platina
    "https://res1011oas.creaction-network.com/images/mofalvguan_242000c6.swf",        # Bar da Fantasia
    "https://res1011oas.creaction-network.com/images/wuxianta_6643c199.swf",          # Labirinto
    "https://res1011oas.creaction-network.com/images/home_c68d9bce.swf",              # Residencia
    "https://res1011oas.creaction-network.com/images/chuansong.swf",                  # Transmissor
    "https://res1011oas.creaction-network.com/images/binyin_a10009a1.swf",            # Quartel
    "https://res1011oas.creaction-network.com/images/shenxueyuan_151a8e94.swf",       # Santuario
]


def recolor_fogo(im):
    """Troca o tema do prédio para fogo/lava: azuis e verdes viram vermelho-alaranjado/brasa, escurece um pouco."""
    import numpy as np
    im = im.convert("RGBA")
    rgb = im.convert("RGB")
    a = np.asarray(im)[:, :, 3]
    hsv = np.asarray(rgb.convert("HSV")).astype(np.float32)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    # H em 0..255 (360 graus = 256)
    green = (h >= 30) & (h < 96)          # 42..135 graus (verdes, vegetação)
    blue = (h >= 96) & (h < 215)          # 135..300 graus (ciano, azul, violeta)
    nh = h.copy(); ns = s.copy(); nv = v.copy()
    # azul/ciano -> vermelho-laranja, mantém variação leve
    t = np.clip((h - 96) / 119.0, 0, 1)
    nh = np.where(blue, 3 + t * 14, nh)               # 4..24 graus
    ns = np.where(blue, np.clip(s * 1.05 + 20, 0, 255), ns)
    nv = np.where(blue, v * 0.88, nv)
    # verde -> marrom-brasa seco
    nh = np.where(green, 14 + (h - 30) * 0.12, nh)
    ns = np.where(green, s * 0.75, ns)
    nv = np.where(green, v * 0.72, nv)
    # quentes (laranja/amarelo/vermelho): reforça calor
    warm = ~(green | blue)
    ns = np.where(warm, np.clip(s * 1.08, 0, 255), ns)
    nv = np.where(warm, v * 0.95, nv)
    out = np.stack([nh, ns, nv], axis=2).clip(0, 255).astype(np.uint8)
    res = Image.fromarray(out, "HSV").convert("RGB")
    # brilho quente leve nas partes claras (brasa)
    arr = np.asarray(res).astype(np.float32)
    lum = arr.mean(axis=2, keepdims=True) / 255.0
    glow = np.array([40, 8, -10], dtype=np.float32)[None, None, :] * (lum ** 2)
    arr = np.clip(arr + glow, 0, 255).astype(np.uint8)
    r = Image.fromarray(arr, "RGB").convert("RGBA")
    r.putalpha(Image.fromarray(a, "L"))
    return r


def cmd_predios(args):
    """Troca as imagens dos predios do castelo DENTRO dos swfs.
    - Se existir personalizados/predios/<swf>_<id>.png (ex.: binyin_1.png) usa essa imagem;
    - senao recolore a original para o tema fogo.
    Os originais de cada imagem sao salvos em saida_mods/predios_originais/ (para voce usar como base)."""
    import subprocess
    jar = garantir_ffdec()
    urls = args.swf.split() if getattr(args, "swf", "") else PREDIOS_PADRAO
    pers = os.path.join(PERS, "predios")
    tmp = os.path.join(SAIDA, "_tmp_predios")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    os.makedirs(MODS, exist_ok=True)
    origs = os.path.join(SAIDA, "predios_originais")
    os.makedirs(origs, exist_ok=True)
    java = ["java", "-Djava.awt.headless=true", "-jar", jar]
    relatorio, feitos = [], 0

    def imagens(pasta):
        out = []
        if os.path.isdir(pasta):
            for f in os.listdir(pasta):
                m = re.match(r"^(\d+)(?:_.*)?\.(png|jpg|jpeg|gif)$", f, re.I)
                if m:
                    out.append((int(m.group(1)), f))
        return sorted(out)

    for url in urls:
        nome = url.split("?")[0].split("/")[-1]
        base = re.sub(r"_[0-9a-fA-F]{8}$", "", os.path.splitext(nome)[0])
        dest = os.path.join(ORIG, "swf", nome)
        if not baixar_url(url, dest):
            relatorio.append(f"{nome}: nao baixou")
            continue
        exp = os.path.join(tmp, base + "_orig")
        subprocess.run(java + ["-export", "image", exp, dest], capture_output=True, text=True, timeout=900)
        achadas = imagens(exp)
        if not achadas:
            relatorio.append(f"{nome}: sem imagens")
            continue
        pares, n_pers, n_cor = [], 0, 0
        for idn, f in achadas:
            orig = Image.open(os.path.join(exp, f)).convert("RGBA")
            orig.save(os.path.join(origs, f"{base}_{idn}.png"))
            novo = None
            for ext in ("png", "jpg", "jpeg"):
                cand = os.path.join(pers, f"{base}_{idn}.{ext}")
                if os.path.exists(cand):
                    novo = Image.open(cand).convert("RGBA")
                    if novo.size != orig.size:
                        novo = novo.resize(orig.size, Image.LANCZOS)
                    n_pers += 1
                    break
            if novo is None:
                if getattr(args, "tema", "fogo") == "nenhum":
                    continue
                novo = recolor_fogo(orig)
                n_cor += 1
            png = os.path.join(tmp, f"{base}_{idn}.png")
            novo.save(png)
            pares += [str(idn), png]
        if not pares:
            relatorio.append(f"{nome}: nada a trocar")
            continue
        saida = os.path.join(MODS, nome)
        r = subprocess.run(java + ["-replace", dest, saida] + pares, capture_output=True, text=True, timeout=1200)
        print((r.stdout or "")[-400:], (r.stderr or "")[-400:])
        if not os.path.exists(saida) or os.path.getsize(saida) == 0:
            relatorio.append(f"{nome}: FALHOU ao gerar o swf")
            continue
        chk = os.path.join(tmp, base + "_novo")
        subprocess.run(java + ["-export", "image", chk, saida], capture_output=True, text=True, timeout=900)
        novos = dict(imagens(chk))
        mudou = 0
        for idn, f in achadas:
            if idn in novos:
                a = open(os.path.join(exp, f), "rb").read()
                b = open(os.path.join(chk, novos[idn]), "rb").read()
                if a != b:
                    mudou += 1
        relatorio.append(f"{nome} ({base}): {len(achadas)} imagens, {mudou} trocadas ({n_cor} recoloridas, {n_pers} suas) | {os.path.getsize(dest)} -> {os.path.getsize(saida)} bytes")
        feitos += 1
    shutil.rmtree(tmp, ignore_errors=True)
    txt = ["RESULTADO predios:"] + relatorio + ["", "Copie os .swf de mods/ para Android/data/<pacote>/files/mods/ , apague o cache do jogo e reinicie o app (launcher v2.7 ou mais novo)."]
    with open(os.path.join(SAIDA, "predios_resultado.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(txt))
    print("\n".join(txt))
    if feitos == 0:
        sys.exit(1)


CODIGO_PADRAO = [
    "https://res1011oas.creaction-network.com/2_995229b1.png",
    "https://res1011oas.creaction-network.com/3_a3b798c7.png",
]
NOME_RE = r"explor|fog|mist|dark|mine|diamond|transfer|teleport|eye|walk|path|astar|treasure|dig|worldmap|mapview|scene"
CONTEUDO_RE = r"explor|fog|mist|diamond|teleport|transfer|treasure"


def filtrar_scripts(raiz, nome_re=NOME_RE, conteudo_re=CONTEUDO_RE, limite=18 * 1024 * 1024):
    """Devolve (todos, escolhidos): caminhos relativos de .as; escolhidos = nome ou conteudo casam, ate 'limite' bytes."""
    todos, nomes, conts = [], [], []
    rn, rc = re.compile(nome_re, re.I), re.compile(conteudo_re, re.I)
    for d, _, fs in os.walk(raiz):
        for f in fs:
            if not f.lower().endswith(".as"):
                continue
            full = os.path.join(d, f)
            rel = os.path.relpath(full, raiz)
            todos.append(rel)
            if rn.search(rel):
                nomes.append(rel)
            else:
                try:
                    with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                        if rc.search(fh.read(300000)):
                            conts.append(rel)
                except Exception:
                    pass
    escolhidos, total = [], 0
    for rel in sorted(nomes) + sorted(conts):
        sz = os.path.getsize(os.path.join(raiz, rel))
        if total + sz > limite:
            continue
        escolhidos.append(rel)
        total += sz
    return sorted(todos), escolhidos


def cmd_scripts(args):
    """Baixa o codigo do jogo (os .png que na verdade sao swfs), exporta os scripts AS3 com o FFDec e
    separa os que tratam de exploracao/mapa/teletransporte. Saida em saida_mods/:
    scripts_diagnostico.txt (sempre), lista_classes.txt, scripts_filtrados_<nome>.zip"""
    import subprocess, zipfile, traceback
    os.makedirs(SAIDA, exist_ok=True)
    diag = []

    def grava_diag():
        with open(os.path.join(SAIDA, "scripts_diagnostico.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(diag))

    diag.append("acao scripts iniciada")
    grava_diag()
    try:
        jar = garantir_ffdec()
        diag.append(f"ffdec: {jar} existe={os.path.exists(jar)}")
    except Exception as e:
        diag.append("ERRO ao preparar o ffdec: " + repr(e))
        grava_diag()
        print("\n".join(diag))
        return
    urls = args.swf.split() if getattr(args, "swf", "") else CODIGO_PADRAO
    saida = os.path.join(SAIDA, "scripts")
    shutil.rmtree(saida, ignore_errors=True)
    os.makedirs(saida, exist_ok=True)
    java = ["java", "-Xmx4g", "-Djava.awt.headless=true", "-jar", jar]
    todos_geral = []
    for url in urls:
        nome = url.split("?")[0].split("/")[-1]
        base = os.path.splitext(nome)[0]
        try:
            # o jogo guarda o codigo como ".png", mas e um swf: salvar com extensao .swf evita a checagem de imagem
            dest = os.path.join(ORIG, "swf", base + "_codigo.swf")
            ok = baixar_url(url, dest)
            if not ok or not os.path.exists(dest):
                diag.append(f"{nome}: NAO BAIXOU ({url})")
                grava_diag()
                continue
            with open(dest, "rb") as fh:
                cab = fh.read(8)
            diag.append(f"{nome}: baixou {os.path.getsize(dest)} bytes, cabecalho={cab[:3]!r} (FWS/CWS/ZWS = swf valido)")
            exp = os.path.join(saida, base)
            os.makedirs(exp, exist_ok=True)
            r = subprocess.run(java + ["-export", "script", exp, dest], capture_output=True, text=True, timeout=3000)
            diag.append(f"{nome}: ffdec codigo={r.returncode} stdout={(r.stdout or '')[-300:]!r} stderr={(r.stderr or '')[-500:]!r}")
            todos, esc = filtrar_scripts(exp)
            diag.append(f"{nome}: {len(todos)} scripts, {len(esc)} separados")
            todos_geral += [f"{base}/{t}" for t in todos]
            zpath = os.path.join(SAIDA, f"scripts_filtrados_{base}.zip")
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
                for rel in esc:
                    z.write(os.path.join(exp, rel), rel)
            diag.append(f"{nome}: zip {os.path.getsize(zpath)} bytes")
        except Exception:
            diag.append(f"{nome}: EXCECAO\n" + traceback.format_exc())
        grava_diag()
    with open(os.path.join(SAIDA, "lista_classes.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(todos_geral))
    shutil.rmtree(saida, ignore_errors=True)
    grava_diag()
    print("\n".join(diag))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comando", choices=["preparar", "analisar", "baixar", "catalogo", "gerar", "verificar", "juntar", "fatiar", "trocar", "swf", "castelo", "predios", "scripts"])
    ap.add_argument("extra", nargs="*", help="juntar PASTA | fatiar PASTA IMAGEM | trocar NOME IMAGEM")
    ap.add_argument("--lista", default="_pedidos.txt")
    ap.add_argument("--faltando", default="_faltando.txt")
    ap.add_argument("--base", default="", help="endereço base (só se o _pedidos.txt tiver caminhos sem https://host)")
    ap.add_argument("--grade", default=os.environ.get("GRADE", ""), help="ex.: 30x20  ou  10000=30x20,10010=18x12")
    ap.add_argument("--tam", default="", help="tamanho do tile, ex.: 256x256 (se não houver original)")
    ap.add_argument("--swf", default=os.environ.get("SWF_URLS", ""), help="links de .swf separados por espaco (padrao: os do castelo)")
    ap.add_argument("--tema", default=os.environ.get("TEMA", "fogo"), choices=["fogo", "nenhum"], help="predios: fogo = recolore; nenhum = so troca as imagens que voce colocou")
    ap.add_argument("--ajuste", default="esticar", choices=["esticar", "cobrir", "conter"])
    a = ap.parse_args()
    c = a.comando
    if c == "preparar":
        cmd_preparar(a)
    elif c == "analisar":
        cmd_analisar(a)
    elif c == "baixar":
        cmd_baixar(a)
        cmd_catalogo(a)
        cmd_analisar(a)
    elif c == "catalogo":
        cmd_baixar(a, montar=False)
        cmd_catalogo(a)
    elif c == "gerar":
        cmd_baixar(a, montar=False)      # precisa dos originais para saber tamanhos/formatos
        cmd_gerar(a)
        shutil.rmtree(EDITAR, ignore_errors=True)
        sys.exit(cmd_verificar(a))
    elif c == "verificar":
        sys.exit(cmd_verificar(a))
    elif c == "swf":
        cmd_swf(a)
    elif c == "castelo":
        cmd_castelo(a)
    elif c == "predios":
        cmd_predios(a)
    elif c == "scripts":
        cmd_scripts(a)
    elif c == "juntar":
        cmd_juntar(a, a.extra[0])
    elif c == "fatiar":
        cmd_fatiar(a, a.extra[0], a.extra[1])
    elif c == "trocar":
        cmd_trocar(a, a.extra[0], a.extra[1])


if __name__ == "__main__":
    main()
