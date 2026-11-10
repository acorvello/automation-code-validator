# 📂 Índice — Pasta Server

Tudo que o dashboard precisa para subir está aqui, na mesma pasta:

| Arquivo | Descrição |
|---------|-----------|
| `start_server.cmd` ⚡ | Inicia o servidor Flask (a partir da raiz do projeto) e abre o navegador automaticamente |
| `create_shortcut.cmd` 🔗 | Cria atalhos no Menu Iniciar e no Desktop |

---

## ⚡ Uso Rápido

- **Dois cliques** em `start_server.cmd` → servidor sobe e o navegador abre em `http://127.0.0.1:5000`
- `create_shortcut.cmd` → atalho no Menu Iniciar (e opcional no Desktop)

---

## 📝 Notas

- O servidor **sempre roda a partir da raiz do projeto** (a `start_server.cmd` faz o `cd` automaticamente).
- O launcher prefere `.venv\Scripts\python.exe` e verifica as dependências antes de iniciar. Se estiverem faltando, execute o comando de instalação exibido.
- O Flask escuta somente em `127.0.0.1`, pois a aplicação não possui autenticação para acesso pela rede.
- Porta: `5000` (fixa). Se estiver em uso, o script avisa e encerra.
- Ícone do atalho: `dashboard.ico` na raiz do projeto.
- Dependências: instale o projeto com `python -m pip install -e .` ou sincronize com `uv sync`.