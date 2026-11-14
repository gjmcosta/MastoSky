<p align="right">
  <a href="README.md">English</a> | <b>Português</b>
</p>

<p align="center">
  <img src="brand/social-card-pt.png" alt="MastoSky" width="600">
</p>

# MastoSky

Cliente web leve e *local-first* para Bluesky e Mastodon.

O MastoSky corre localmente no teu computador e junta numa única janela a leitura de feeds, pesquisa e publicação cruzada em ambas as redes, sem servidores intermediários, sem telemetria e sem dependências externas.

---

## Destaques

- **Feeds unificados:** Vê os posts de quem segues no Bluesky e no Mastodon integrados por ordem cronológica, ou filtra por rede.
- **Compositor e fios:** Escreve uma vez e publica no Bluesky, Mastodon ou em ambos. Suporta upload de vídeo (MP4/WebM/MOV até 50MB com processamento assíncrono em ambas as redes), fios/threads encadeados, colagem direta de imagens (Cmd+V ou arrastar), rascunhos locais com auto-save, sondagens e avisos de conteúdo (CW).
- **Pesquisa unificada:** Pesquisa publicações, perfis e hashtags em ambas as redes em simultâneo.
- **Vista clássica e em colunas:** Alterna entre uma timeline única ou uma vista personalizável em várias colunas (estilo Deck View).
- **Mensagens diretas e conversas privadas:** Consulta conversas do Bluesky (via AT Protocol Chat) e Mastodon (mensagens com visibilidade direta), envia novas mensagens e responde em tempo real com indicador de não lidas.
- **Notificações e perfis:** Acompanha respostas, gostos, partilhas e consulta perfis e estatísticas de seguidores lado a lado.
- **Alt-Text com IA:** Geração automática de descrições acessíveis (diretrizes WCAG) para imagens via Google Gemini (grátis), Ollama (100% local) ou endpoints compatíveis com OpenAI, com idioma configurável.
- **Zero dependências externas:** O backend usa apenas a biblioteca padrão do Python 3; o frontend é HTML, CSS e JavaScript puros. Sem `pip install`, sem Node.js.
- **Privacidade e execução local:** Corre exclusivamente em `127.0.0.1`. As tuas credenciais nunca saem da tua máquina.

---

## Instalação e Execução

### Instalador em comando único

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/gjmcosta/MastoSky/main/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/gjmcosta/MastoSky/main/install.ps1 | iex
```

### Instalação manual via Git

Requer apenas Python 3.3+.

```bash
git clone https://github.com/gjmcosta/MastoSky.git
cd MastoSky
python3 app.py --open
```

No primeiro arranque, acede a [http://127.0.0.1:8000](http://127.0.0.1:8000) (se não abrir automaticamente) para configurar as contas.

### Utilização no Telemóvel e iPad (Rede Local & PWA)

Para acederes a partir do teu iPhone, iPad ou Android na mesma rede Wi-Fi:

```bash
python3 app.py --lan
```

- O terminal mostra o endereço da rede local e imprime um **QR Code ASCII** para leitura instantânea pela câmara.
- No computador podes também clicar no ícone `📱` no cabeçalho do MastoSky para ver o QR Code em alta definição e instruções:
  - **iPhone & iPad (Safari):** Toca em *Partilhar* $\rightarrow$ *«Adicionar ao Ecrã Principal»* para correr em ecrã inteiro como uma app nativa.
  - **Android (Chrome):** Toca no menu (⋮) $\rightarrow$ *«Instalar aplicação»* ou *«Adicionar ao ecrã principal»*.
- Acesso seguro protegido por verificação de IPs privados (RFC 1918), validação de origem e tokens CSRF de sessão.

---

## Configuração de Credenciais

### Bluesky
1. Abre o [bsky.app](https://bsky.app) → **Definições** → **Privacidade e Segurança** → **Palavras-passe da aplicação**.
2. Cria uma palavra-passe específica (ex.: `MastoSky`).
3. Introduz o teu handle (ex.: `utilizador.bsky.social`) e a palavra-passe gerada de 16 caracteres.

### Mastodon
1. Na tua instância Mastodon, vai a **Preferências** → **Desenvolvimento** → **Nova aplicação**.
2. Dá o nome `MastoSky`. Mantém o **Redirect URI** pré-definido (`urn:ietf:wg:oauth:2.0:oob`).
3. Seleciona apenas as permissões necessárias: `read:statuses`, `read:notifications`, `write:statuses`, `write:media`, `write:favourites`.
4. Clica em **Guardar**, abre a aplicação criada e copia o **Teu token de acesso** (*Your access token* — não copies a *Client key* nem o *Client secret*).
5. No MastoSky, introduz apenas o domínio da tua instância (ex: `mastodon.social` ou `https://mastodon.social` — sem o teu `@utilizador`) e cola o token de acesso.

---

## Segurança

O MastoSky foi desenhado para manter o controlo absoluto no teu computador:

- **Apenas localhost:** O servidor faz bind estrito em `127.0.0.1`. Não escuta em redes públicas ou na tua rede local.
- **Comunicação direta:** Os pedidos vão diretamente do teu computador para os servidores oficiais do Bluesky (XRPC) e da tua instância Mastodon. Sem telemetria nem servidores intermédios.
- **Proteção contra CSRF e Origin:** Valida cabeçalhos `Host` e `Origin`, e exige um token de sessão criptográfico (`X-CSRF-Token`) em todas as ações de escrita.
- **Armazenamento local:** As credenciais ficam guardadas no ficheiro `config.json` (permissões `0600`), protegido pelo `.gitignore`.

---

## Licença

[MIT](LICENSE)
