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
