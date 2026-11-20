# 🚀 MastoSky — Relatório de Progresso e Estado do Projeto (PROGRESS.md)

> **Data de atualização:** 20 de Novembro de 2026  
> **Versão:** v1.1.0  
> **Repositório:** `gjmcosta/MastoSky` (Branch: `main`)  
> **Testes Automatizados:** 215 testes aprovados (`python3 -m unittest discover -s tests -v`)

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
  - Cascata de fallback de modelos Gemini atualizada para a nova geração (`gemini-3.5-flash-lite` $\rightarrow$ `gemini-3.1-flash-lite` $\rightarrow$ `gemini-flash-lite-latest` $\rightarrow$ `gemini-3.5-flash` $\rightarrow$ `gemini-3.8-flash`), eliminando o bloqueio por descontinuação dos modelos 2.0/2.5 antigos (404) e prevenindo exaustão de quota diária por modelo na camada gratuita.
  - Feedback visual no input de alt-text durante o carregamento (`✨ A gerar descrição com IA...`) e indicação imediata de erros caso ocorra algum problema de quota ou conectividade.
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
- **Tradução Instantânea de Publicações com IA (1 clique):**
  - Ícone de ação nativo `ICONS.translate` (globo Feather SVG em stroke 2) integrado diretamente na barra de ações dos posts (`.acts`), alinhado de forma elegante com os restantes ícones (responder, partilhar, gostar, guardar e ver fio).
  - Animação de rotação contínua (`spin-rotate`) durante a tradução assíncrona com feedback visual e tratamento gracioso de erros.
  - Reutilização inteligente do fornecedor de IA configurado (Google Gemini, Ollama ou OpenAI-compatible), com deteção e tradução para o idioma ativo da interface (Português ou Inglês).
  - Suporte resiliente para a API do Google Gemini com modelos atualizados (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.8-flash`), eliminando falhas por descontinuação de modelos antigos ou exaustão de quota.
  - Suporte completo a publicações com citações / reposts citados (*Quote Posts*): tradução independente do cartão citado e da publicação de topo.
  - Caixa de tradução contextual elegante (`.post-translated-box`) com realce luminoso, preservando na totalidade o post original, menções, hashtags, hiperligações e quebras de linha.
  - Opção rápida para alternar / ocultar a tradução a qualquer momento com realce ativo (`.act-translate.on`).
  - Regras estritas de prompt engineering para assegurar que a IA devolve apenas a tradução pura, sem preâmbulos ou aspas desnecessárias.
  - Endpoint seguro e protegido contra CSRF no backend: `/api/translate`.

### 📱 Acesso Móvel, iPad e Otimização para iOS/Android
- **Navegação Inteligente de Hashtags e Menções @Utilizador (In-App):**
  - **Pesquisa Instantânea de Hashtags:** Ao tocar em qualquer `#hashtag` num post, o MastoSky muda automaticamente para a coluna/aba de Pesquisa, define o tipo de filtro como "Publicações" e executa a pesquisa em ambas as redes (`Bluesky` e `Mastodon`), apresentando de imediato os posts correspondentes e rolando com suavidade até à caixa de resultados.
  - **Abertura Interna de Menções (@user):** Clicar em qualquer menção `@utilizador` dentro do texto das publicações agora abre diretamente o perfil nativo no modal interno do MastoSky (`openUserProfile`), resolvendo utilizadores de ambas as redes ou do Fediverso sem encaminhar para o browser externo ou para as aplicações oficiais. Suporte a URLs completos de perfis e resolução remota no Mastodon.
  - **Memória de Posição de Leitura Entre Abas (*Scroll Restoration*):** A posição de scroll de cada feed (`timeline`, `explore`, `search`, `saved`, `notifs`, `profile`) é preservada individualmente via `tabScrolls`. Ao voltar atrás de uma hashtag ou pesquisa para a Timeline (ou ao alternar entre abas e utilizar o gesto de retroceder no iOS/Android via `popstate`), o feed recorda exatamente o post onde o utilizador se encontrava, eliminando o salto indesejado para o topo.
- **Barra de Abas Fixa e Imutável no Topo Mobile (Sem Scroll Instável):**
  - Eliminação do scroll horizontal (`overflow-x: auto`) e efeito elástico (*rubber-banding*) na linha de abas do topo móvel que provocava instabilidade ("dança" ao arrastar com o polegar) e dificultava o toque.
  - Distribuição fixa e proporcional a 100% da largura (`flex: 1 1 0; min-width: 0`), bloqueio de gestos horizontais espúrios com `touch-action: pan-y` e `overflow-x: hidden`.
  - Apresentação em controlo segmentado ergonómico com ícones Feather SVG verticais (18px) centrados e etiquetas inferiores concisas com tamanho adaptativo (10px / 9px em ecrãs muito compactos).
  - Emblema numérico de notificações (*badge*) integrado no canto superior do ícone de sino, com realce ativo e transições suaves ao selecionar qualquer aba.
- **PWA e Otimização para Ecrãs Táteis:**
  - Suporte completo a PWA com `manifest.json`, ícone de aplicação para iOS (`apple-touch-icon`), temas com suporte a `viewport-fit=cover` e respeito integral pelas *Safe Area Insets* (entalhe / Dynamic Island e barra de início inferior).
  - Modo LAN dedicado (`python3 app.py --lan`) com geração automática de QR Code em SVG para emparelhamento instantâneo de telemóveis e tablets na mesma rede Wi-Fi local sem configurações manuais de IP.

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
- **Normalização de DIDs e Menções no Perfil:** Decodificação e desaninhamento resiliente de DIDs percent-encoded (`did%3Aplc...` $\rightarrow$ `did:plc...`) no frontend e backend (`Bsky.user_profile` e `Bsky.user_feed`), prevenindo erros 400 (`Invalid AT identifier`) ao clicar em menções de publicações cujos identificadores AT vinham codificados por URLs.
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
- **Pré-visualização de Ligações no Compositor e Cartão Nativo no Bluesky (`GET /api/link_preview`):**
  - Deteção automática da primeira ligação HTTP/HTTPS ao escrever ou colar num novo post (`extractFirstComposerUrl()`, `scheduleComposerLinkPreview()`), exibindo o cartão visual `#composerLinkPreview` com miniatura, domínio, título, descrição e botão `✕` para dispensar sem apagar o link.
  - Endpoint `GET /api/link_preview` (`fetch_link_preview()`, `_validate_remote_http_url()`, `_LinkPreviewParser`) com cache em memória (30 min) e proteção anti-SSRF contra destinos locais, redes privadas e endereços Tailscale.
  - Ao publicar no Bluesky sem imagens/vídeo/citação/sondagem, envia `link_card` em `POST /api/post` e `Bsky.post()` anexa o embed nativo `app.bsky.embed.external` (incluindo upload da miniatura como blob).
- **Publicação Cruzada com Ligações Externas e Cartões de Citação Aprimorados:**
  - Quando a publicação original ou a sua citação contém uma ligação externa (cartão de artigo ou `<a href>` externo), `extractCrossPostExternalUrl()` extrai o URL completo e inclui-o como link clicável (`🌐 <url>`) apenas na publicação enviada para a rede de destino (mantendo a ação nativa na rede original inalterada).
  - Cartão visual (`drawQuotedCard()` e `renderCrossCanvas()`) passa a renderizar também a imagem/cartão da ligação ou media dentro da citação (`getValidCardMedia()`, `measureQuotedCard()`), limpa o prefixo `RE: ...` em citações Mastodon (`plain(..., strip_quote_inline=True, strip_re=True)` e `extractCleanCardText()`) e preserva quebras de linha e listas com marcadores (`<br>` → `\n`).
  - Modal de Publicação Cruzada (`#crossPostOverlay`, `executeCrossPost()`) passa a oferecer dois botões lado a lado: **Publicar só no {dest}** (`#submitCrossPostOnly`, sem republicar na rede original) e **Publicar nas duas redes** (`#submitCrossPost`).
  - Sobreposição de modais a partir do Perfil (`#userProfileOverlay`): `#crossPostOverlay` abre acima do modal de perfil (`z-index: 1020`, com prioridade na tecla `Escape`), enquanto **Citação** (`startQuote()`) e **Responder** (`startReply()`) fecham o modal de perfil automaticamente e focam a caixa de novo post.
- **Alojamento em CasaOS (Docker), Acesso Remoto Tailscale e Sincronização (`user_data.json`):**
  - `Dockerfile` baseado em `python:3.12-alpine` (zero dependências externas), `.dockerignore` (protege `config.json` e `user_data.json` locais) e `docker-compose.yml` pronto para **CasaOS** (metadados `x-casaos`, volume `/DATA/AppData/mastosky:/data` e variável `MASTOSKY_DATA_DIR=/data`).
  - Suporte nativo em `app.py` para `MASTOSKY_DATA_DIR` (guardando `config.json` e `user_data.json` no volume persistente com permissões `0600`) e validação de rede privada alargada em `is_private_or_local_host()` para gama CGNAT Tailscale (`100.64.0.0/10`, incluindo IPv4-mapped IPv6), domínios `.ts.net` (MagicDNS) e `MASTOSKY_ALLOWED_HOSTS`.
  - Deteção automática de URL Tailscale (`get_tailscale_ip()` / `get_tailscale_url()` / `MASTOSKY_TAILSCALE_HOST`) em `GET /api/lan` e secção dedicada **Acesso Remoto (Tailscale)** no modal `#mobileModalOverlay`.
  - Novos endpoints autenticados com CSRF `GET /api/user_data` e `POST /api/user_data` (escrita atómica thread-safe em `user_data.json`) e motor de sincronização automática no `index.html` (`pullUserDataFromServer`, `scheduleServerSync`, `applySyncedUserData`, `initServerSync`) para sincronizar Guardados, Rascunhos, Palavras Silenciadas, Colunas do Deck e Preferências entre dispositivos.
  - **Atualização persistente com 1 clique no CasaOS/Docker (`run_self_update`, `schedule_process_restart`):** Descarrega o código de `main` do GitHub preservando `config.json` e `user_data.json`, persiste uma cópia em `/data/app_update` (restaurada automaticamente no arranque pelo `Dockerfile`), agenda reinício automático do processo Python em `POST /api/self_update` e mantém `#selfUpdateBtn` visível nas Definições (com `GET /api/version?force=1` ao clicar em "Verificar").
- **Experiência Nativa iOS (iPhone) e iPadOS (iPad):**
  - Ícones PNG oficiais (`brand/apple-touch-icon.png` `180×180`, `brand/icon-192.png` e `brand/icon-512.png`) servidos em `/brand/*.png` e `/apple-touch-icon.png` e declarados em `manifest.json` e `index.html`.
  - Modo de vista independente entre iPhone (`<768px`, `mastosky_view_mode_mobile` em Coluna Única) e iPad/Mac (`≥768px`, sincronizando `view_mode` e `deck_columns` via servidor).
  - Modo Deck otimizado para iPad (`768px–1180px` com colunas de `336px`, altura `100dvh` com margens `safe-area-inset` e botões de ação táteis de `32×32px` em `@media (pointer: coarse)`).
  - Gesto tátil *Pull-to-Refresh* (`initTouchPullToRefresh` + `#pullToRefreshIndicator`) para PWA standalone e preenchimento rápido de rascunho por partilha de URL (`handleIncomingShareParams` + `share_target` no `manifest.json`).
- **Cópia de Segurança & Restauro Local (Backup JSON):**
  - Secção dedicada nas Definições (`#setupOverlay`) e atalho no modal de rascunhos para exportar e restaurar todos os dados locais num ficheiro JSON estruturado (`mastosky-backup-YYYY-MM-DD.json`).
  - Cobre rascunhos de publicações, posts guardados nos marcadores, ordem e visibilidade das colunas do Deck, e preferências completas de interface (tema, idioma, modo de navegação e notificações).
  - Importação resiliente com deduplicação automática (por ID de rascunho e chave única de post), garantindo que rascunhos ou posts guardados existentes não são repetidos.
  - Mensagens informativas de feedback em tempo real com contagem exata de itens restaurados.
- **🔇 Silenciamento de Palavras-chave e Filtros de Conteúdo (Muted Words):**
  - Secção dedicada `#mutedWordsSection` nas Definições (`#setupOverlay`) para gerir palavras-chave e `#hashtags` silenciadas.
  - Adição rápida por botão ou tecla `Enter`, com etiquetas removíveis em `.muted-chips-list` / `.muted-chip`.
  - Dois modos configuráveis: *Mostrar aviso colapsável* (`.muted-post-banner` com botão mostrar/ocultar em `.muted-post-content`) e *Ocultar completamente*.
  - Correspondência Unicode com limites de palavra (`getMutedMatch`) aplicada em texto e `cw` na Timeline, Em Alta, Guardados e Pesquisa, e persistida nos backups JSON (`muted_words` e `mute_mode`).
- **🎨 Polimento Visual e Refinamentos de UX/UI:**
  - Definição explícita de `--surface` e `--surface-1` em ambos os temas (claro e escuro).
  - Unificação de todos os botões de fecho (`✕`) dos modais em `.setup-close-btn` e adição do modal customizado `#confirmModalOverlay` (`askConfirm` / `showAppAlert`), eliminando `window.confirm` e `window.alert` nativos.
  - Crachá interativo `ALT` nas imagens do feed (`.media-alt-badge` + `.media-alt-popover`), *Content Warning* (`cw` extraído no backend em `app.py`) colapsável em `.cw-banner` e *tooltips* com data/hora completa (`fullDateStr`) nos carimbos temporais (`.when`, citações, notificações e mensagens).
  - Tradução com IA disponível também nas notificações (`.act-translate` em `renderNotifs`).
  - Melhorias em Mensagens Diretas (correção de altura e duplo scroll em `.msg-thread-wrap`, cabeçalho `#convoPeerInfo` clicável para abrir o perfil do contacto e coluna `messages` sincronizada na configuração do Deck e na Dock Bar mobile com ordens 1–8).
  - Destaque visual da coluna ativa no Deck (`.deck-col.is-active-col`), tabs mobile adaptadas a ecrãs estreitos, menu de topo em modo de coluna única reorganizado em 7 abas simétricas com ícone superior + etiqueta fixa sem quebras de linha nem transbordamento (`flex: 1 1 0`), uniformização do sub-cabeçalho de filtros da coluna de Notificações (`.notif-header-bar` / `.notif-filter-pills` em cartão enquadrado com 5 controlos simétricos sem sobreposição no scroll), atalhos de teclado atualizados para `1 – 7` e internacionalização completa em `renderLoadMore` e `#newConvoModalOverlay`.
  - Correção da atualização em tempo real da coluna de Notificações após alerta sonoro: `dedupSort()` passou a deduplicar notificações pelo identificador único (`getNotifKey`) em vez do URL do post alvo (evitando descartar novos gostos/partilhas sobre o mesmo post), `captureScrollAnchor()` / `restoreScrollAnchor()` priorizam `data-notif-key` e `initNotifObserver()` deixou de limpar automaticamente `.fresh` e os crachás 600ms após renderização passiva no Deck.
- **Sinalização de Conectividade em Tempo Real & Rate Limit:**
  - Pílula flutuante animada (`#netStatusPill`) para alertas contextuais imediatos:
    - *Modo Offline:* Deteta corte de rede via `window.offline` (`📡 Sem ligação à Internet — Modo offline`) e auto-recupera ao restabelecer ligação (`window.online`), recarregando os feeds em background.
    - *Servidor Local Desligado:* Deteta falhas de rede no cliente HTTP (`api()`), informa o utilizador (`⚠️ A aguardar pelo servidor local MastoSky...`) e mantém um *ping* periódico automático na rota de verificação, reconectando e atualizando o token CSRF assim que o servidor `app.py` for reiniciado.
    - *Limite de Taxa (Rate Limit 429):* Captura avisos de taxa limite do Bluesky ou Mastodon e exibe aviso claro e discreto (`⏳ Limite de pedidos temporário atingido — aguarda um momento`).
- **📱 Acesso Móvel (iPhone, Android, iPad), Rede Local & PWA:**
  - *Opção de Rede Local (`--lan` e `--host`):* O servidor pode agora escutar na rede Wi-Fi/LAN com deteção automática do IP local (`get_local_ip()`) e suporte a mDNS (`.local`).
  - *QR Code no Terminal em Puro Python:* Ao arrancar com `--lan`, o terminal imprime a URL local e um **QR Code ASCII** legível pela câmara do telemóvel, implementado de raiz em Python 3 standard (zero dependências externas / sem `pip`).
  - *Segurança Estrita em Rede:* O método `allowed()` valida endereços IP privados (RFC 1918: `10.x.x.x`, `172.16-31.x.x`, `192.168.x.x`), link-local e mDNS, rejeitando qualquer domínio externo ou porta incorreta, e mantém verificação criptográfica de CSRF em todos os pedidos POST.
  - *Progressive Web App (PWA):*
    - Ficheiro `manifest.json` com `display: standalone`, ícones oficiais em SVG (`/brand/app-icon.svg`), cores de tema dinâmicas e scope configurado.
    - Meta-tags específicas para Apple iOS/iPadOS (`apple-mobile-web-app-capable`, `apple-touch-icon`, `viewport-fit=cover`).
    - Ajustes de CSS para áreas de segurança (Safe Area insets) em ecrãs com entalhe (*notch* / *Dynamic Island*) e barras de gestos (`env(safe-area-inset-*)`).
  - *Interface de Ligação Rápida no Frontend:*
    - Botão dedicado `📱` no cabeçalho com crachá luminoso reativo `[LAN]` quando o servidor corre com `--lan`.
    - Diálogo visual com SVG de alta definição do QR Code, botão de cópia de URL em 1 clique e guias passo a passo ilustrados para Safari (iOS) e Chrome (Android).
    - Deteção de estado desligado com botão de copiar comando (`python3 app.py --lan`).
    - Secção de acesso móvel integrada nas Definições (`#setupOverlay`).
  - *Otimização Responsiva para Mobile (iOS / Android):*
    - **Correção do Logótipo Duplo:** Remoção do estilo inline `display:block` e adição de regras com `!important` para o seletor de tema claro/escuro/sistema, garantindo que apenas um logótipo é renderizado independentemente da preferência do sistema operativo.
    - **Header Compacto em Ecrãs Móveis:** Ocultação automática de botões supérfluos no telemóvel (`#mobileConnectBtn` e `#shortcutsBtn`), redução do espaçamento e do tamanho dos ícones na barra de navegação superior para evitar transbordamento horizontal (*overflow*).
    - **Tabs com Scroll Horizontal Suave:** As abas de navegação principal (`.tabs`) passam a ter scroll horizontal touch nativo (`-webkit-overflow-scrolling: touch`) e `white-space: nowrap`, impedindo a quebra feia de linhas de texto (ex: "Em Alta") e prevenindo o encolhimento da coluna de conteúdo no iPhone/Android.
    - **Largura Total de Coluna & Scroll Nativo:** Ajuste do elemento `<main>` para 100% da largura útil e substituição de `overflow-x: hidden` no HTML por `overflow-x: clip` no body, eliminando o bloqueio de scroll vertical do WebKit/iOS Safari.
    - **Topo Fixo e Protegido da Dynamic Island/Notch:** O cabeçalho completo (`#topNavWrap`), contendo o logótipo, os botões de opções (Tema, Alternar Colunas/Única, Atualizar e Definições) e as abas, passa a ser fixo no topo (`position: sticky`) com efeito de desfoque (*backdrop-filter: blur*), margem segura de topo (`env(safe-area-inset-top)`) e estilo de status bar `default`, impedindo que os ícones fiquem ocultos ou sobrepostos pelo relógio/entalhe do iPhone.
    - **Barra Flutuante de Navegação Rápida (Dock Bar) no Mobile:** Reformulação da barra flutuante (`.side-nav-rail`) quando exibida no telemóvel ao fazer scroll:
      - Ocultação dos botões redundantes e de desktop (`#sideThemeBtn`, `#sideRefreshBtn`, `#sideSettingsBtn`, `#sideShortcutsBtn`, `#sideLangBtn`).
      - Limitação da largura a `calc(100vw - 24px)` (máx 380px) centrada no ecrã com margem de segurança contra corte nas laterais.
      - Botão de novo post (`#sideComposeBtn`) destacado e centralizado entre as abas de navegação.
      - Distribuição uniforme das opções com alvos de toque generosos (38-44px) e respeito pela área segura inferior (`env(safe-area-inset-bottom)`).

### 💬 Mensagens Diretas e Conversas Privadas (Concluído: Backend + Frontend)
- **Suporte Nativo ao Serviço de Chat do Bluesky (AT Protocol):**
  - Implementação completa do namespace `chat.bsky.convo.*` com roteamento pelo proxy dedicado (`atproto-proxy: did:web:api.bsky.chat#bsky_chat`).
  - Deteção e resolução dinâmica do PDS específico do utilizador (`#atproto_pds` / `serviceEndpoint` via `didDoc`), direcionando as chamadas de chat para o nó PDS correto (evitando o erro `501 MethodNotImplemented` que a porta genérica `bsky.social` devolve por não ser o host PDS onde a conta está alojada).
  - Listagem de conversas (`list_conversations`), obtenção de mensagens em ordem cronológica (`get_conversation_messages`), envio com extração e parsing automático de facets (`send_message`), marcação como lida (`mark_as_read`) e início de novas conversas (`start_conversation`).
  - Tratamento resiliente e amigável caso a App Password do utilizador não tenha a opção de Direct Messages ativada.
- **Suporte a Conversas Diretas do Mastodon (REST API):**
  - Listagem de conversas agregadas (`GET /api/v1/conversations`) com identificação automática do interlocutor e estado de leitura.
  - Reconstrução completa do histórico de mensagens a partir do contexto de statuses (`/api/v1/statuses/:id/context`: ancestrais + status atual + descendentes) deduplicados e ordenados cronologicamente.
  - Envio de mensagens com visibilidade direta (`visibility: "direct"`), garantia de menção explícita ao destinatário e encadeamento de `in_reply_to_id`.
  - Tratamento de permissões com aviso claro em caso de ausência do escopo `read:conversations`.
- **Endpoints REST Unificados no Backend (`app.py`):**
  - `GET /api/conversations`: agrega conversas de ambas as redes em paralelo com contagem de não lidas (`total_unread`) e ordenação por data da última mensagem.
  - `GET /api/conversation?network=&id=`: obtém o histórico completo de mensagens normalizado.
  - `POST /api/conversation/send`: envio de mensagem protegido contra CSRF.
  - `POST /api/conversation/read`: marcação de conversa como lida.
  - `POST /api/conversation/start`: criação ou procura de nova conversa.
- **Interface e Experiência de Utilizador (Frontend `index.html`):**
  - **Aba e Coluna Dedicada no Deck:** Nova aba "Mensagens" e coluna `#colMessages` com reordenação por drag-and-drop e alternância de visibilidade nas Definições.
  - **Lista de Conversas Agregada:** Exibição com fotos de perfil, nome, handle, crachá da rede social (`Bluesky` / `Mastodon`), pré-visualização do último snippet e data relativa (`ago()`).
  - **Filtros por Rede:** Pílulas de filtro rápido (*Ambas*, *Bluesky*, *Mastodon*) na barra de cabeçalho das mensagens.
  - **Vista de Conversa e Balões de Chat:** Ecrã dedicado de fio de mensagens com balões estilizados (mensagens enviadas à direita com acento de cor, mensagens recebidas à esquerda com fundo suave), carimbos de data/hora, avatares e rolagem suave automática para a mensagem mais recente.
  - **Formulário de Envio Instantâneo:** Campo de digitação com envio via `Enter` ou botão de avião de papel, feedback de estado e sanitização.
  - **Modal de Nova Mensagem:** Acesso pelo botão `+ Nova Mensagem` ou diretamente nos perfis de utilizador ("💬 Mensagem"), permitindo selecionar a rede, introduzir o handle e redigir a mensagem inicial.
  - **Crachás de Mensagens Não Lidas (Badges):** Indicadores numéricos em tempo real na aba móvel/desktop, no dock lateral flutuante e no cabeçalho da coluna do Deck, atualizados no arranque e em polling de segundo plano a cada 2 minutos.
  - **Atalhos e Acessibilidade:** Tecla `6` para saltar diretamente para a coluna/aba de Mensagens, tecla `Escape` para fechar o modal ou voltar à lista a partir de uma conversa aberta, e traduções integrais em Português e Inglês.
  - **Refinamento Visual do Subheader e Estado Vazio:** Barra de ferramentas unificada com pílulas e botão de nova mensagem perfeitamente alinhados (altura exata de 28px, geometria arredondada contínua, adaptação responsiva no Deck View para "Nova" e etiqueta completa em ecrãs largos, sem quebras de linha espúrias), contraste ideal no tema escuro/claro, renderização corrigida do estado vazio com ícone SVG estilizado e adição do botão de ação rápida `+` no cabeçalho superior da coluna do Deck.

### 🧩 Desduplicação, Cross-Posting Avançado, Produtividade e Leitura (Novembro 2026)
- **Desduplicação de Cross-posts na Timeline (*Crosstalk*):**
  - Deteção automática de publicações simultâneas do mesmo autor em Mastodon e Bluesky (`groupCrossPosts()`, `isCrossPostPair()`, `normalizeCrossPostText()`) fundidas num único cartão com seletor `🐘 + 🦋` no topo (prioridade Mastodon por omissão), preservando interações locais e paginação por cursor.
  - Opção configurável nas Definições (`#cfgCrosstalkDedup`), sincronizada em `user_data.json` e backup JSON.
- **Adaptação Inteligente de Limite (300 vs 500), Auto-Thread & Anéis Duplos:**
  - **Modo Híbrido Automático (301–500 caracteres):** Ao publicar para *Ambas as redes*, o servidor aceita `thread_by_network` (`app.py`) para enviar 1 post completo para o Mastodon e um fio numerado (`1/2`, `2/2`, …) para o Bluesky.
  - **Divisão Manual (`✂️ Dividir em fio`):** Botão `#splitThreadBtn` que divide textos longos por parágrafos, linhas, frases ou palavras em caixas editáveis do fio.
  - **Anéis de Progresso Duplos (`#countRings`):** Dois anéis SVG animados (`🦋 300` e `🐘 500`) com transição para âmbar (`≤ 20` restantes), vermelho (excedido) e traço tracejado (modo híbrido).
- **Agendamento de Publicações (*Scheduled Posts*):**
  - Persistência segura em `DATA_DIR/scheduled_posts.json` (`0600`) protegida em `run_self_update()`, com ciclo em background de 15s (`start_scheduler_thread()`).
  - Deteção no arranque de agendamentos em atraso (`missed`) para decisão manual, tratamento de falhas parciais com reenvio seletivo sem duplicação (`/api/scheduled/run_now`), seletor rápido no compositor (`#schedulePickerBar` com `+1h`, `+3h`, `Amanhã 09:00`) e modal de gestão (`#scheduledOverlay`).
- **Autocomplete de `@menções` & Mapeamento de Handles entre Redes:**
  - Menu flutuante `#mentionAcMenu` no compositor e nos fios com sugestões instantâneas de contactos locais/mapeados e pesquisa remota em `/api/search?type=actors`.
  - Gestão de pares equivalentes nas Definições (`#handleMapSection` + sugestões automáticas dos pares Crosstalk) com substituição automática por rede ao publicar (`applyHandleMappings()`).
- **Filtros Rápidos na Timeline & Modo Catch-Up (*"✨ O que perdi?"*):**
  - Barra de filtros persistente em `localStorage` (`Ambas | 🦋 Bluesky | 🐘 Mastodon` e `Sem boosts`).
  - Modal `#catchUpOverlay` com janelas de `6h`, `12h` e `24h`, ordenação por relevância/interação e resumo opcional por tópicos via IA (`POST /api/catchup_summary`).
- **Modo de Leitura Limpa de Artigos (*Reader View*):**
  - Extração HTML limpa com proteção SSRF (`GET /api/reader` / `fetch_article_reader()`), botão **`📖 Ler`** nos cartões `.ext-card` (mantendo o clique no cartão a abrir em nova janela) e modal `#readerOverlay` com controlos de tamanho de letra (`A-` / `A+`).
- **Refinamentos de UX e Hiperligações:**
  - Links externos abertos em nova janela (`target="_blank"` + `rel="opener"`), alinhamento dos botões do modal de cross-post e destaque primário no botão de publicação dupla.
- **Identidade Visual, Navegação Mobile & Performance (v0.8.5):**
  - **Barra de Filtros da Timeline & Ícones de Marca:** `#tlFilterBar` alinhada em 5 colunas simétricas idênticas às Notificações (`.notif-header-bar`), substituição global de emojis `🦋`/`🐘`/`📖` pelos ícones vetoriais oficiais (`#i-brand-bsky`, `#i-brand-masto`, `#i-book`, `#i-no-boosts`, `#i-sparkles`).
  - **Mobile iOS/Android & Tipografia:** Topo limpo sem abas duplicadas (`#topNavWrap .tabs` oculto em `<768px`) e Dock Bar fixa sempre visível em baixo com círculos `36×36px` simétricos (`stroke-width="1.75"`), badge de notificações compacto sem estrela oculta, dimensionamento corrigido do modal `#catchUpOverlay` (`box-sizing: border-box` e altura dinâmica `100dvh`), contraste `--accent-solid` (`#6558F5`) nos botões primários escuros, `-webkit-font-smoothing: antialiased`, `tabular-nums` e `--serif` no *Reader View*.
  - **Performance Backend & Frontend:** Compressão `gzip` (`zlib`) em `Handler.send()` e `http()`, cache em memória pré-comprimida de `index.html` (`_INDEX_HTML_CACHE`), pool persistente `_API_EXECUTOR`, *polling* pausado quando `document.hidden`, `content-visibility: auto` em `.post`, *blur* reduzido para `10px` em mobile, `loading="lazy"`/`decoding="async"` em `el("img")` e *scroll listeners* com `requestAnimationFrame`.
  - **Estado Visual de Acessibilidade (`ALT` nas Imagens Anexadas):** Crachás `✓ ALT` / `⚠️ Sem ALT` nas miniaturas do compositor e fios (`attachAltBadge()`), com foco rápido ao clicar e aviso opcional antes de publicar (`#cfgWarnMissingAlt` / `warnMissingAlt`).
  - **Agrupamento Visual de Republicações na Timeline (*estilo Phanpy*):** Compactação automática de sequências de boosts consecutivos do mesmo autor (`groupBoostClusters()`, `renderBoostCluster()`, `#cfgBoostCluster`).
  - **Gestão de Imagens no Compositor:** Reordenação das imagens anexadas (`←` / `→` e *drag-and-drop* em `attachImageCardControls()`) e modal de **Recorte Rápido** (`#cropModalOverlay`, `openCropModal()`) com predefinições `Livre`, `1:1`, `16:9` e `4:5`.
- **Qualidade JS, Mute Words Unificados, Feeds/Listas, Sondagens & Offline PWA:**
  - **Prevenção de `ReferenceError` nos Testes (`tests/js_lint.py`):** analisador de escopo JavaScript integrado na suíte de testes (`test_index_javascript_no_undeclared_identifiers`) para detetar identificadores não declarados antes de chegar ao browser.
  - **Mute Words Unificados:** preservação dos próprios posts (`is_own`), inspeção de `target_post`, e suporte completo nas Notificações (ocultar ou colapsar com aviso via `createMutedContentWrapper()`).
  - **Feeds Personalizados (Bluesky) & Listas (Mastodon):** endpoints `GET /api/lists` e `GET /api/list_feed`, coluna dedicada `#colLists` no Deck e seletor rápido `#exploreSourceSelect` no Explorar.
  - **Sondagens (*Polls*) do Mastodon:** extração em `Masto.item()`, votação via `POST /api/poll/vote` e renderização interativa com barras percentuais em `renderPostPoll()`.
  - **Service Worker PWA (`GET /sw.js`):** cache *Cache-First* para assets estáticos e *Network-First* para a interface e feeds de leitura (sem cache de tokens/dados sensíveis).
- **Reorganização das Definições, Polimento Deck & Endurecimento de Segurança (18 Nov 2026):**
  - **Novo Menu de Definições por Categorias (`.settings-shell`):** modal `#setupOverlay` reorganizado em 5 separadores (*Contas & Redes*, *Aparência & Feed*, *IA & Acessibilidade*, *Notificações & Filtros*, *Sistema & Dados*) com barra lateral fixa no desktop, abas horizontais em mobile e cabeçalho/rodapé sempre fixos (`setSettingsTab()`).
  - **Polimento do Modo Deck:** ajuste tipográfico em `#tlFilterBar` e `.notif-filter-pills` para eliminar truncamento (`...`) e sobreposição de `.filter-badge`, banner de notificações não lidas numa única linha (`.notif-summary-banner`), maior contraste em `.header-nav-btn` e atalho `+ Coluna` no cabeçalho (`#headerAddColBtn` / `scrollToAddCol()`).
  - **Hub de Perfil Vivo (`#panelHubView`):** remoção de ações redundantes e adição do feed **Publicações recentes** (`loadProfileHubFeed()` / `#profileHubFilterPills`) diretamente abaixo dos cartões de conta.
  - **Segurança Backend & Frontend:** remoção do fallback TLS sem verificação em `_urlopen_remote()`, validação SSRF de IPs resolvidos via `socket.getaddrinfo()` e redirecionamentos (`_SafeRedirectHandler`) em `_validate_remote_http_url()`, mascaramento de `gemini_key`/`openai_key` em `GET /api/status` (com preservação no `POST /api/setup`), e `rel="noopener noreferrer"` nos links externos do Reader View e Lightbox (cobertos por `test_security_hardening_ssrf_tls_and_masked_ai_keys`).
  - **Edição de Publicações:** edição nativa no Mastodon (`GET /api/post_source`, `POST /api/edit`, `Masto.edit_status()`, modal `#editPostOverlay`) e *"Apagar e editar no compositor"* no Bluesky (`reeditBlueskyPost()`).
  - **Separação Modular do Frontend:** extração dos estilos e lógica de `index.html` para `app.css` e `app.js` (servidos por `app.py` com gzip e incluídos no `/sw.js` e `Dockerfile`).

- **Refinamentos Mobile (iPhone / Coluna Única), Sync de Leitura, Notificações & Privacidade (v1.1.0 — 20 Nov 2026):**
  - **Compositor em Modal Mobile (`< 768px`):** Ocultação do compositor inline em coluna única e abertura em modal/gaveta (`body.mobile-compose-open`) via Dock Bar, Responder, Citar, Editar ou Partilha de URL, com indicador âmbar de rascunho em `.side-nav-compose.has-draft`.
  - **Estabilidade iOS & Acabamento Visual:** Bloqueio de auto-zoom em inputs (`font-size: 16px`), meta `viewport` com `maximum-scale=1, user-scalable=no`, contenção horizontal em `.deck-col`/`.post`, gradiente de fundo sob a cápsula da Dock Bar, placeholder de pesquisa compacto, correção da altura uniforme em `.panel-action-row`, e remoção do contorno espúrio (`stroke="none"`) nos logótipos SVG `#i-brand-bsky` e `#i-brand-masto`.
  - **Erros HTTP & Navegação em Modais:** Sanitização de respostas HTML em erros HTTP (`_clean_http_error_summary()` em `app.py`), botão *Tentar novamente* nas conversas (`renderThreadErrorBanner()`), e `closeModalsForNavigation()` para fechar *"O que perdi?"* (`#catchUpOverlay`) ao abrir posts, hashtags, respostas ou citações.
  - **Sincronização da Posição de Leitura (*Timeline Position Sync*):** Registo debounced do post visível no topo da Timeline sincronizado via `preferences.timeline_anchor` em `user_data.json`, com barra **`🔖 Retomar onde ficaste`** (`#resumeReadingBanner`) e salto suave entre dispositivos.
  - **Notificações Mais Ágeis:** Polling dedicado de 60s, atualização automática ao abrir a aba Notificações (`setTab("notifs")` com cooldown de 15s) e retoma imediata ao regressar do segundo plano no iOS (`handleForegroundResume()`).
  - **Proteção de Privacidade Mastodon ↔ Bluesky:** Exposição de `visibility` em `Masto.item()`, bloqueio de cross-post e citação cruzada para o Bluesky em publicações `private`/`direct` (com indicador `🔒`), ajuste automático do compositor para apenas Mastodon ao escolher `private`/`direct` e aviso contextual para `unlisted`.
- **Polimento Visual, Performance, Vídeo, Partilha & Definições Mobile (20 Nov 2026 — pós-v1.1.0):**
  - **Linguagem Visual, Contraste & Tipografia:** Substituição de emojis residuais (posts privados, menu de partilha e banners CW) por SVGs uniformes (`#i-vis-private`, `#i-vis-direct`, `#i-cross`, `#i-message`, `#i-cw`), ajuste de contraste WCAG (`--bsky` `#0768BD`, `--line` `#C8CEF0` no claro e `--accent-solid` `#584AE8` no escuro), *easing gradient* de 7 pontos sob a Dock Bar, curva `--ease-spring` em modais/popovers e afinação de `letter-spacing`/`line-height`.
  - **Performance Backend & Frontend:** `_STATIC_ASSET_CACHE` pré-comprimido em `gzip` com suporte a `ETag`/`304 Not Modified` para `/app.css` e `/app.js` em `app.py`, e inserção DOM em lote via `DocumentFragment` em `render()` e `renderNotifs()`.
  - **Leitura Limpa, Vídeo & Partilha Externa:** Mensagens HTTP claras em `fetch_article_reader()` (`403`/`404`/`429`) com fallback da descrição do cartão no `#readerContent`; preservação de vídeos em reprodução durante o polling (`isFeedVideoPlaying()` + `_deferredTimelineRender` + `.post:has(video) { content-visibility: visible }`); download direto de vídeos para Mastodon e Bluesky (`GET /api/download_video` + `getBlob` via PDS em `.acts .act-download`); e botão de partilha externa (`.act-share`, Web Share API no iOS + fallback clipboard no desktop).
  - **Content Warning & Definições Mobile:** Correção da quebra de linha em `.cw-banner .cw-label` (`white-space: normal; flex: 1`), barra de categorias das Definições em grelha fixa de 5 colunas em ecrãs móveis (`#settingsNav` sem scroll lateral, com ícones SVG e etiquetas curtas PT/EN) e correção do empilhamento dos modais acima da Dock Bar (`main` sem `z-index: 1` e ocultação da Dock Bar enquanto `.setup-overlay` está aberto).

---

## 📋 4. Próximos Passos e Roadmap Pendente

1. **Acesso Remoto Seguro & Empacotamento / Mobile Nativo (Opcional):**
   - Documentação complementar Tailscale / Cloudflare Tunnel e avaliação futura de wrapper nativo iOS/iPadOS/Android.

---

## 💡 5. Como Retomar o Trabalho Numa Nova Sessão
Para iniciar uma nova sessão limpa com qualquer assistente de IA (Antigravity, Claude, etc.), basta enviar o seguinte prompt inicial:

```text
Olá! Estou a trabalhar no projeto MastoSky (cliente unificado Bluesky + Mastodon).
Por favor lê o ficheiro PROGRESS.md na raiz do projeto para obteres o contexto
completo da arquitetura, das funcionalidades já implementadas e dos próximos passos.
Depois de leres, confirma que estás pronto para continuarmos.
```
