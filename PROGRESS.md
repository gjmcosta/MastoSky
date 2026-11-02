# 🚀 MastoSky — Relatório de Progresso e Estado do Projeto (PROGRESS.md)

> **Data de atualização:** 2 de Novembro de 2026  
> **Versão:** v0.5.1  
> **Repositório:** `gjmcosta/MastoSky` (Branch: `main`)  
> **Testes Automatizados:** 133 testes aprovados (`python3 -m unittest discover -s tests`)

---

## 📌 1. Visão Geral do Projeto
O **MastoSky** é um cliente web local-first unificado para **Bluesky** e **Mastodon**, concebido para permitir leitura e publicação simultânea ou seletiva entre ambas as redes sociais a partir de uma interface moderna, rápida e privada.

### Princípios Fundamentais de Engenharia:
1. **Zero Dependências Externas em Runtime:** Corre exclusivamente com a biblioteca padrão do Python 3 (`http.server`, `urllib`, `sqlite3`, `threading`, etc.). Não requer `pip install`.
2. **Local-first e Privacidade Total:** As credenciais (`config.json`) ficam guardadas exclusivamente no computador do utilizador e nunca passam por servidores de terceiros.
3. **Frontend Autónomo e Ágil:** Interface SPA num único ficheiro (`index.html`) em HTML5, CSS3 moderno e Vanilla JavaScript ES6 (sem frameworks pesadas como React ou Vue).
4. **Bilingue por Omissão (PT/EN):** Sistema de internacionalização integrado com suporte completo a Português e Inglês.

---

## 🏗️ 2. Arquitetura e Ficheiros Principais

| Ficheiro | Função |
| :--- | :--- |
| **`app.py`** | Servidor local multithreaded (`ThreadingHTTPServer`), clientes de API para AT Protocol (Bluesky) e REST API (Mastodon), gestão de cache, compressão, endpoints REST (`/api/*`), verificação CSRF e segurança. |
| **`index.html`** | Aplicação de página única (SPA) contendo estilos, ícones SVG, lógica de visualização (Deck View e Coluna Única), áudio espacial (Web Audio API), observadores de scroll e gestão de estado. |
| **`tests/test_app.py`** | Suite abrangente de testes unitários que cobrem APIs, resolução de URIs, paginação, extração de media, citações e segurança. |
| **`config.json`** | Ficheiro local gerado automaticamente com as credenciais do utilizador (ignorado no git por segurança). |
| **`prompts_conversa_mastosky.md`** | Histórico cronológico de todos os prompts de desenvolvimento para análise de prompt engineering. |

---

## ✅ 3. Funcionalidades Concluídas

### 📝 Caixa de Composição e Publicação Cruzada (*Composer*)
- Publicação simultânea para Bluesky e Mastodon com contadores de caracteres específicos (300 / 500).
- Seletor de alvo: Ambas as redes, apenas Bluesky ou apenas Mastodon.
- Seletor de visibilidade para Mastodon (Público, Não Listado, Seguidores, Direto).
- Suporte a avisos de conteúdo (*Content Warning* / Spoiler).
- Sondagens nativas no Mastodon e renderizadas no Bluesky.
- Upload de imagens (até 4) com pré-visualização, legendas (*alt text*) e colar da área de transferência (`Cmd+V` / arrastar e largar).
- Suporte a publicação de fios de publicações (*Threads*).
- **Cartão de Publicação Cruzada (*Cross-post Card*):** Geração dinâmica de cartões visuais para partilhar publicações de uma rede na outra.
- **Sistema de Rascunhos (*Drafts*):** Indicador de rascunho guardado automaticamente no `localStorage`.

### 🗂️ Modos de Visualização: Deck View e Coluna Única
- **Coluna Única:** Layout limpo e focado, com barra lateral flutuante de navegação rápida e alternador de abas.
- **Modo Deck (Multicoluna):** Inspirado no TweetDeck/Deck. Colunas lado a lado com scroll horizontal independente:
  - Novo Post / Compor
  - Timeline Unificada
  - Em Alta (*Explore / Trending*)
  - Pesquisa (Posts, Perfis e Hashtags)
  - Guardados / Favoritos
  - Notificações
  - Perfil
- **Reordenação e Personalização do Deck:** Possibilidade de mover colunas com setas ou arrastar (*drag-and-drop*), fechar colunas e reabri-las através do menu "+ Adicionar Coluna". Persistência da ordem no `localStorage`.

### 💬 Citações e Fios de Conversa (*Threads*)
- As publicações citadas abrem diretamente como uma conversa dentro do MastoSky (sem abrir separadores externos).
- Resolução direta de URLs web do Bluesky (`bsky.app/...`) para AT-URIs nativos (`at://...`).
- Histórico de navegação de conversas com botão de retrocesso (`← Voltar ao post anterior`).

### 👤 Perfis de Utilizador e Contas
- Visualização de perfis com avatar, cabeçalho, estatísticas de seguidores/a seguir e feed de publicações.
- Modal dedicado de perfil ao clicar no avatar ou autor de qualquer post, preservando a coluna de Composição intacta.
- **Seguir e Deixar de Seguir (*Follow / Unfollow*):** Suporte nativo completo a seguir e deixar de seguir perfis no Bluesky (`app.bsky.graph.follow` via AT Protocol) e Mastodon (`/api/v1/accounts/:id/follow` e `unfollow`), com deteção fidedigna do estado de relação (`viewer.following` no Bluesky e consulta a `/api/v1/accounts/relationships` com codificação robusta de arrays no Mastodon), botão dinâmico (*Follow* / *Following* com transição para *Unfollow* em *hover*), cores personalizadas por rede (azul `#0085FF` para Bluesky e roxo `#6364FF` oficial para Mastodon), cápsula perfeitamente alinhada e coerente com o botão "Ver na web / View on web ↗", atualização reativa do contador de seguidores e proteção CSRF no endpoint `/api/follow`.
- Gestão de contas ativas e alternância de sessão.

### 🔔 Sistema de Notificações Avançado
- **Filtros rápidos compactos por tipo:** Todas, Respostas, Gostos, Partilhas, Seguidores (pílulas compactas com expansão suave).
- **Leitura automática:** As notificações são marcadas como lidas ao fazer scroll sobre elas via `IntersectionObserver` ou ao passar o rato (hover).
- **Marcação manual em lote:** Botão de marcar todas como lidas no cabeçalho da coluna (`✓✓`).
- **Apresentação idêntica à Timeline nas Republicações:** As notificações de partilha exibem um banner superior com quem partilhou (`🔁 Nome republicou a tua publicação`) e, em baixo, o post original completo com a autoria real, eliminando qualquer ambiguidade.
- **Sons Espaciais via Web Audio API:** 4 efeitos cósmicos sutis sintetizados 100% em código (zero ficheiros áudio externos):
  - *Respostas / Menções:* Glissando estelar límpido (587Hz $\rightarrow$ 880Hz $\rightarrow$ 1175Hz).
  - *Gostos:* Gota de pulsar suave e aveludada (659Hz $\rightarrow$ 392Hz).
  - *Partilhas:* Acorde harmónico em quinta orbital (440Hz + 659Hz).
  - *Seguidores:* Feixe ascendente de entrada em órbita (392Hz $\rightarrow$ 523Hz $\rightarrow$ 784Hz).
- **Alertas de Desktop:** Notificações nativas do sistema operativo com botão para autorizar no navegador e clique para abrir a coluna diretamente.
- **Deteção inteligente em segundo plano:** Polling de 2 minutos que deteta novas notificações e toca apenas para novos eventos (sem alertas no carregamento inicial).

---

## 📋 4. Próximos Passos e Roadmap Pendente

1. **Acesso no iPad / Rede Local (LAN):**
   - Adicionar opção `--lan` ou `--host 0.0.0.0` no `app.py` para permitir que o iPad aceda ao MastoSky na mesma rede Wi-Fi via Safari.
   - Adicionar meta-tags para iOS/iPadOS (`apple-mobile-web-app-capable`, `apple-touch-icon`) para funcionar como Web App / PWA em ecrã inteiro.
   - Ajustar validação de `Host` e CSRF para IPs locais da rede doméstica.

2. **Empacotamento e Distribuição (Opcional):**
   - Criação de scripts simples de arranque para macOS (`run.command`) e Windows (`run.bat`).
   - Avaliação de instaladores nativos portáteis sem dependências.

---

## 💡 5. Como Retomar o Trabalho Numa Nova Sessão
Para iniciar uma nova sessão limpa com qualquer assistente de IA (Antigravity, Claude, etc.), basta enviar o seguinte prompt inicial:

```text
Olá! Estou a trabalhar no projeto MastoSky (cliente unificado Bluesky + Mastodon).
Por favor lê o ficheiro PROGRESS.md na raiz do projeto para obteres o contexto
completo da arquitetura, das funcionalidades já implementadas e dos próximos passos.
Depois de leres, confirma que estás pronto para continuarmos.
```
