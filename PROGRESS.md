# 🚀 MastoSky — Relatório de Progresso e Estado do Projeto (PROGRESS.md)

> **Data de atualização:** 7 de Novembro de 2026  
> **Versão:** v0.6.1  
> **Repositório:** `gjmcosta/MastoSky` (Branch: `main`)  
> **Testes Automatizados:** 142 testes aprovados (`python3 -m unittest discover -s tests`)

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
- **Cartão de Publicação Cruzada Renovado (*Cross-post Card*):** Geração dinâmica de cartões visuais para partilhar publicações de uma rede na outra com melhorias substanciais:
  - *Altura dinâmica e formato vertical adaptável:* Em vez de um quadrado 1:1 fixo com grandes espaços vazios, a altura do cartão agora adapta-se com precisão ao volume de texto e anexos (desde ~2:1 compacto para posts curtos até 4:5 vertical — a proporção máxima exibida por inteiro nas timelines e apps do Bluesky e Mastodon sem qualquer corte).
  - *Enquadramento inteligente sem cortes (Dynamic Aspect Ratio & Contain):* Pré-carregamento das imagens em anexo com deteção da relação de aspeto natural. Imagens isoladas (incluindo cartazes, pósteres verticais e ilustrações) utilizam agora renderização `contain` com altura dinâmica (até 760px) e fundo elegante em degradé escuro integrado, garantindo que 100% da imagem, textos e detalhes de topo e base são preservados na íntegra sem qualquer corte. O teto máximo do canvas foi expandido até 1500px para acomodar na perfeição cartazes verticais completos.
  - *Renderização de publicações citadas (*Quote Posts*):* Quando o post original cita outro post, é renderizado um cartão interno embutido elegante com o avatar, nome, handle, link e texto do autor citado.
  - *Preservação de quebras de linha:* Respeita parágrafos manuais, listas, IBANs e dados estruturados sem aglomerar o texto numa só linha.
  - *Céu estrelado enriquecido:* Fundo cósmico com 35+ estrelas e reflexos em cruz subtis sem poluição visual.
  - *Destaque oficial ao MastoSky:* Rodapé enriquecido com o logótipo oficial completo do elefante constelação (`/brand/logo-lockup-dark.svg`).
  - *Botões de tema circulares perfeitos:* Ajuste nos estilos de `.swatch` para eliminar quaisquer contornos ou artefactos quadrados em todos os navegadores.
- **Sistema de Rascunhos (*Drafts*):** Indicador de rascunho guardado automaticamente no `localStorage`.
- **Resposta Integrada Encadeada (*Threaded Reply Composer* à semelhança do Mastodon):** Ao clicar em "Responder" em qualquer publicação da timeline ou notificações, o post original pai passa a ser renderizado de forma destacada no topo da coluna de novo post (com avatar, autor, texto completo e anexos), seguido de uma linha conetora vertical de fio de conversa até ao autor atual e um botão `✕` para cancelar a resposta e voltar imediatamente ao modo de "Novo post" normal. Inclui highlight reativo na timeline (`.is-reply-target`), alternância por clique duplo (*toggle*), preenchimento automático da menção do autor em respostas Mastodon, foco imediato e botão de envio dinâmico ("Responder" / "Publicar").

### 🎨 Refinamentos Visuais e UX/UI (Tema, Pesquisa e Configurações)
- **Modo Escuro, Modo Claro e Automático (*Dark / Light / Auto*):**
  - Seletor de tema nas Configurações (Preferências: *Automático (Sistema)*, *Modo Escuro*, *Modo Claro*) com persistência no `localStorage`.
  - Botão de alternância rápida no cabeçalho e na barra lateral com ícones reativos (sol, lua e monitor de sistema).
  - Variáveis semânticas CSS completas para ambos os temas (`--bg`, `--card`, `--surface-2`, `--line`, `--ink`, `--muted`, `--accent`), garantindo alto contraste e leitura confortável.
  - Alternância automática dos logótipos oficiais claro e escuro (`.brand-logo-dark` / `.brand-logo-light`) e brilhos da constelação cósmica.
  - Script inline imediato no `<head>` com execução síncrona antes do primeiro render da página para eliminar a 100% qualquer *FOUC* (*Flash of Unstyled Content*).
- **Novo Diálogo Aberto de Configurações (*Settings Screen*):**
  - Transformação do antigo formulário estreito (480px) em coluna única num ecrã aberto e desafogado (`max-width: 960px`) com grelha de 2 colunas responsivas (`.settings-grid`, `.settings-col`), eliminando a necessidade de scroll vertical para aceder às opções de preferências, notificações e contas.
  - Adição de botão de fechar no topo (`✕`), botão secundário "Cancelar" ao lado de "Guardar e Iniciar", e fecho prático com a tecla `Escape` ou clicando no fundo escurecido.
- **Coluna de Pesquisa Otimizada e Alinhada:**
  - Substituição do botão volumoso de texto "Pesquisar" por um botão compacto de ícone de lupa (`#searchBtn` com `#i-search`), libertando espaço para o campo de texto.
  - Pílulas de filtro organizadas em grelhas consistentes: controlo segmentado em 4 colunas iguais para tipos de pesquisa (*Tudo*, *Publicações*, *Utilizadores*, *Hashtags*) e linha dedicada de 3 colunas para redes (*Ambas*, *Bluesky*, *Mastodon*) com as cores das marcas.

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
- **Preservação de Posição de Leitura e Scroll Anchoring:** Durante as atualizações automáticas em segundo plano (auto-refresh/polling) na Timeline, Explore e Notificações, a posição do utilizador é mantida 100% estática e congelada no mesmo pixel do ecrã caso esteja a ler posts mais abaixo (`captureScrollAnchor` / `restoreScrollAnchor`), sem saltos visuais (*content jumps*) e sem perder posts carregados via paginação. Quando chegam novos posts ou notificações enquanto o utilizador está abaixo do topo:
  - É exibida uma pílula flutuante animada e com estilo unificado (`↑ X novas publicações` / `↑ X novas notificações`).
  - Clicar na pílula leva o utilizador com suavidade ao topo (`scrollColToTop`), tanto no modo Deck (na respetiva coluna) como no modo de Coluna Única (`window.scrollTo({top: 0, behavior: "smooth"})`).
  - O desaparecimento da pílula é feito via fade gradual com transição CSS para evitar o cancelamento precoce da animação de scroll em navegadores baseados em WebKit/Blink, e inclui auto-dispensa inteligente quando o utilizador faz scroll manual até às imediações do topo (<30px).

### 💬 Citações e Fios de Conversa (*Threads*)
- **Ícones Claros e Inconfundíveis:** Diferenciação visual total entre "Responder" (seta curva ↩️, padrão Mastodon/web) e "Ver conversa" (fio vertical com nós conetores 🧵).
- **Coluna Lateral Dedicada de Conversa no Modo Deck (*Side Thread Column*) e Coerência Universal de Clique:** À semelhança do Mastodon Web, clicar numa publicação (no texto ou cartão fora de links/botões/media) ou no botão de conversa abre a coluna lateral de conversa (`#colThread`) posicionada dinamicamente imediatamente ao lado da coluna onde a publicação foi vista. Este comportamento é agora **universal e consistente em todas as colunas**:
  - *Timeline, Em Alta, Pesquisa, Guardados, Perfil e Notificações:* Em qualquer uma das colunas, clicar no cartão de um post abre o detalhe e a árvore de respostas.
  - *Coluna de Notificações:* Notificações de resposta, menção, citação, gosto ou partilha associadas a um post abrem diretamente a conversa completa do post e marcam o item como lido; eventos de perfil (como novos seguidores) abrem o perfil do utilizador.
  - A coluna de origem permanece totalmente aberta, ativa e interativa, com realce luminoso suave no post inspecionado (`.is-thread-active`).
- **Navegação Completa e Fecho:** A coluna de conversa possui cabeçalho com botão de retorno para navegação profunda no histórico do fio (`←`), botão de subida ao topo e botão de fechar (`✕`), suportando também a tecla `Escape` para fecho rápido. No modo de coluna única, mantém-se a transição suave no feed com botão de voltar e reposicionamento exato de scroll.
- As publicações citadas abrem diretamente como uma conversa dentro do MastoSky (sem abrir separadores externos).
- Resolução direta de URLs web do Bluesky (`bsky.app/...`) para AT-URIs nativos (`at://...`).
- Histórico de navegação de conversas com botão de retrocesso (`← Voltar ao post anterior`).

### 👤 Perfis de Utilizador e Contas
- Visualização de perfis com avatar, cabeçalho, estatísticas de seguidores/a seguir e feed de publicações.
- Modal dedicado de perfil ao clicar no avatar ou autor de qualquer post, preservando a coluna de Composição intacta.
- **Seguir e Deixar de Seguir (*Follow / Unfollow*):** Suporte nativo completo a seguir e deixar de seguir perfis no Bluesky (`app.bsky.graph.follow` via AT Protocol) e Mastodon (`/api/v1/accounts/:id/follow` e `unfollow`), com deteção fidedigna do estado de relação (`viewer.following` no Bluesky e consulta a `/api/v1/accounts/relationships` com codificação robusta de arrays no Mastodon), botão dinâmico (*Follow* / *Following* com transição para *Unfollow* em *hover*), cores personalizadas por rede (azul `#0085FF` para Bluesky e roxo `#6364FF` oficial para Mastodon), cápsula perfeitamente alinhada e coerente com o botão "Ver na web / View on web ↗", atualização reativa do contador de seguidores e proteção CSRF no endpoint `/api/follow`.
- Gestão de contas ativas e alternância de sessão.
- **Resiliência e Onboarding Mastodon:** Sanitização automática do URL da instância (`sanitize_masto_instance`), aceitando formatos brutos e removendo caminhos acidentais colados pelos utilizadores (ex: `/@utilizador`, `/settings`, `/web`), e captura informativa de respostas HTML no cliente HTTP (`http()`), substituindo o erro padrão e críptico de JSON (`Expecting value: line 1 column 1 (char 0)`) por uma mensagem amigável que explica exatamente o formato esperado da instância. Documentação atualizada para esclarecer o uso do Redirect URI pré-definido (`urn:ietf:wg:oauth:2.0:oob`) e a seleção exclusiva de *Your access token*.

### 🔔 Sistema de Notificações Avançado
- **Sinalética Renovada & Alto Contraste:** Cartões não lidos com destaque notório no tema escuro (`border-left: 5px`, fundo com 18% da cor da rede, borda iluminada e sombra volumétrica). Cada notificação por ler exibe um ponto luminoso pulsante (*unread dot*) no canto superior.
- **Banner de Resumo e Contadores por Filtro:** Barra superior no feed com o número total de notificações pendentes (`🔵 X notificações não lidas`) e botão rápido `Marcar todas como lidas ✓✓`. As pílulas de filtro passam a exibir pequenos crachás numéricos dinâmicos com as não lidas por categoria (Respostas, Gostos, Partilhas, Seguidores).
- **Filtros rápidos compactos por tipo:** Todas, Respostas, Gostos, Partilhas, Seguidores (pílulas compactas com expansão suave).
- **Leitura automática:** As notificações são marcadas como lidas ao fazer scroll sobre elas via `IntersectionObserver` ou ao passar o rato (hover).
- **Marcação manual em lote:** Botão de marcar todas como lidas no cabeçalho da coluna (`✓✓`).
- **Ações Completas nos Cartões de Notificação:** Assim como nos cartões da Timeline, as notificações de publicações (respostas, menções, citações, gostos e partilhas) contam agora com a barra de ações completa:
  - Responder (`↩`) com contador de respostas e pré-preenchimento;
  - Partilhar / Repost (`🔁`) com popover para republicação direta ou geração de cartão de crossposting para a outra rede;
  - Gosto (`❤️`) com contagem reativa e sincronização com a respetiva rede (Bluesky / Mastodon);
  - Guardar / Bookmark (`🔖`) com persistência no armazenamento local;
  - Ver conversa (`🧵`) para inspecionar a árvore do fio na coluna lateral.
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
