# 🚀 MastoSky — Relatório de Progresso e Estado do Projeto (PROGRESS.md)

> **Data de atualização:** 10 de Novembro de 2026  
> **Versão:** v0.8.0  
> **Repositório:** `gjmcosta/MastoSky` (Branch: `main`)  
> **Testes Automatizados:** 159 testes aprovados (`python3 -m unittest discover -s tests`)

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
- **Upload de Vídeo Nativo:** Suporte completo para vídeos (MP4, WebM, MOV até 50MB e 10 minutos) com publicação no Bluesky e Mastodon:
  - *Bluesky:* Obtenção automática de token JWT com escopo restrito (`com.atproto.server.getServiceAuth` com audiência `did:web:video.bsky.app`), upload binário para o serviço dedicado `video.bsky.app` e acompanhamento assíncrono do job de encoding até conclusão (`JOB_STATE_COMPLETED`). Suporte a proporção de aspeto natural (`aspectRatio`) e legenda acessível (`alt`).
  - *Mastodon:* Upload via `/api/v2/media` com polling assíncrono em `/api/v1/media/{id}` até o vídeo estar processado e com URL público antes de submeter o status.
  - *Frontend e Interface:* Pré-visualização com leitor `<video controls>`, indicação de duração formatada, botão de remoção rápida e campo de descrição acessível. Exclusão mútua automática com imagens e sondagens. Suporte a publicação direta ou em fios (*Threads*).
- **Geração de Legendas Acessíveis (Alt-Text) com IA Aprimorada:**
  - Cascata de fallback de modelos Gemini (`gemini-3.5-flash` $\rightarrow$ `gemini-3.5-flash-lite` $\rightarrow$ `gemini-3.8-flash` $\rightarrow$ `gemini-flash-latest`), eliminando falhas por descontinuação de modelos antigos (404) ou congestionamento transitório da API gratuita (503).
  - Desativação de tokens de raciocínio interno (`thinkingBudget: 0`) e teto de saída calibrado para respostas ágeis sem truncamento.
  - Redimensionamento automático de imagens no cliente (máx 1024px) reduzindo tráfego de rede e prevenindo timeouts.
  - Instruções de sistema restritas e sanitização backend (`clean_alt_text()`), garantindo descrições WCAG limpas no idioma escolhido (Português de Portugal por omissão), sem asteriscos ou formatações Markdown indesejadas.
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

### 🤖 Acessibilidade e Geração Automática de Alt-Text com IA
- **Fornecedores Múltiplos e Configuráveis:**
  - *Google Gemini (Recomendado / Nuvem Gratuita):* Suporte nativo aos modelos `gemini-2.0-flash` e `gemini-1.5-flash` via Google AI Studio API (gratuito, resposta rápida e excelente compreensão visual em Português).
  - *Ollama (100% Local e Privado):* Execução local no computador do utilizador (porta `11434`) com modelos de visão como `llama3.2-vision` ou `moondream`, sem envio de dados para a nuvem.
  - *Compatível com OpenAI:* Suporte a qualquer endpoint compatível (LocalAI, LM Studio, Groq, etc.).
- **Seletor de Idioma Dedicado:** Opção nas Configurações para escolher o idioma do Alt-Text (*Português (PT)*, *Português (BR)*, *Inglês*, *Espanhol*, *Francês* ou seguir automaticamente o idioma da interface).
- **Prompt Especializado em Acessibilidade (Diretrizes WCAG):** Instruções rigorosas à IA para produzir descrições concisas (1 a 3 frases), focadas na ação e elemento central, sem chavões como "Foto de" ou "Imagem de", e com transcrição precisa de textos visíveis entre aspas.
- **Experiência Fluida no Compositor (UX):**
  - Botão discreto com ícone de varinha mágica `✨` embutido no campo de texto alternativo de cada imagem (tanto na publicação principal como em publicações de fios/threads).
  - Animação de carregamento subtil durante a geração.
  - Opção de automação: *"Gerar Alt-Text automaticamente ao anexar imagens"*, preenchendo as descrições assim que as imagens são carregadas ou coladas via clipboard (`Cmd+V` / drag & drop).
  - Campo 100% editável para que o utilizador possa rever, ajustar ou apagar o texto gerado a qualquer momento antes da publicação.

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
- **⚡ Atalhos de Teclado Globais (Experiência Power User / TweetDeck):**
  - *Navegação de Posts:* Teclas `J` / `↓` e `K` / `↑` para navegar continuamente entre publicações na coluna ativa com auto-scroll suave e deteção inteligente do primeiro post visível.
  - *Realce Visual:* Classe `.is-keyboard-focused` com anel luminoso de alto contraste e sombra volumétrica sem sobreposição.
  - *Ações Imediatas no Post em Foco:* `L` para gosto/unlike, `T` para partilhar/repost, `R` para responder encadeadamente (com foco e cursor no compositor), `S` para marcar/guardar nos favoritos e `Enter` / `O` para abrir a conversa completa.
  - *Geral e Compositor:* `N` ou `C` para novo post (rola até ao compositor e foca o texto), `/` para pesquisar, `.` para saltar para o topo da coluna, `1` a `6` para alternar colunas/abas diretamente, `M` para alternar modo claro/escuro e `⌘+Enter` / `Ctrl+Enter` para publicar instantaneamente.
  - *Teclas de Escape Contextual:* Tecla `Escape` para fechar progressivamente modais, o visualizador de imagens, a coluna lateral de conversa, desfazer o foco do post atual ou desfocar caixas de texto.
  - *Modal de Ajuda dos Atalhos (*Cheat Sheet*):* Modal elegante aberto via tecla `?` ou pelos novos botões dedicados na barra de cabeçalho (`#shortcutsBtn`) e barra lateral (`#sideShortcutsBtn`), com suporte bilingue completo (PT/EN) e tags `<kbd>` personalizadas.
  - *Segurança de Digitação:* Desativação automática de atalhos de tecla única sempre que o utilizador está a escrever em qualquer `input`, `textarea`, `select` ou campo editável.

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

### 🛠️ Refinamentos de UX, Robustez & Conectividade
- **Cópia de Segurança & Restauro Local (Backup JSON):**
  - Secção dedicada nas Definições (`#setupOverlay`) e atalho no modal de rascunhos para exportar e restaurar todos os dados locais num ficheiro JSON estruturado (`mastosky-backup-YYYY-MM-DD.json`).
  - Cobre rascunhos de publicações, posts guardados nos marcadores, ordem e visibilidade das colunas do Deck, e preferências completas de interface (tema, idioma, modo de navegação e notificações).
  - Importação resiliente com deduplicação automática (por ID de rascunho e chave única de post), garantindo que rascunhos ou posts guardados existentes não são repetidos.
  - Mensagens informativas de feedback em tempo real com contagem exata de itens restaurados.
- **Sinalização de Conectividade em Tempo Real & Rate Limit:**
  - Pílula flutuante animada (`#netStatusPill`) para alertas contextuais imediatos:
    - *Modo Offline:* Deteta corte de rede via `window.offline` (`📡 Sem ligação à Internet — Modo offline`) e auto-recupera ao restabelecer ligação (`window.online`), recarregando os feeds em background.
    - *Servidor Local Desligado:* Deteta falhas de rede no cliente HTTP (`api()`), informa o utilizador (`⚠️ A aguardar pelo servidor local MastoSky...`) e mantém um *ping* periódico automático na rota de verificação, reconectando e atualizando o token CSRF assim que o servidor `app.py` for reiniciado.
    - *Limite de Taxa (Rate Limit 429):* Captura avisos de taxa limite do Bluesky ou Mastodon e exibe aviso claro e discreto (`⏳ Limite de pedidos temporário atingido — aguarda um momento`).

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
