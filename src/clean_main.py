#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = PROJECT_ROOT / "src" / "main.py"
CLEANED_PATH = PROJECT_ROOT / "src" / "main_cleaned.py"

# Le o arquivo original
with open(SOURCE_PATH, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Arquivo original com {len(lines)} linhas")

new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    
    # Mantem APENAS a primeira ocorrencia de cada msg de "Executando N\\u00e3o de Avalia\\u00e7\\u00e3o"
    if '"--- Executando' in line and 'history.append' in line:
        if not any('--- Executando N\\u00e3o de Avalia\\u00e7\\u00e3o (Ollama)' in new_lines[-5:]):
            new_lines.append(line)
    # Mantem APENAS a primeira ocorrencia da msg "needs_fix={needs_fix}"
    elif 'f">> Resultado da IA: needs_fix=' in line and i < 70:
        if not any('needs_fix={' in new_lines[-10:] and 'message"' in ''.join(new_lines[-10:])):
            new_lines.append(line)
    else:
        new_lines.append(line)
    
    i += 1

# Remove BOM se existir
if new_lines and new_lines[0].startswith('\ufeff'):
    new_lines = new_lines[1:]

# Escreve o arquivo limpo
with open(CLEANED_PATH, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Arquivo limpo criado com {len(new_lines)} linhas!")

# Verifica e valida sintaxe
import py_compile
try:
    py_compile.compile(str(CLEANED_PATH), doraise=True)
    print("✅ VALIDADO: Código Python válido!")
except py_compile.PyCompileError as e:
    print(f"❌ ERRO DE SINTAXE: {e}")