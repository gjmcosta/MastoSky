# MastoSky — guia de identidade (v0.2)

## Conceito
Um mastodonte desenhado como constelação: o animal é o Mastodon, as estrelas são o céu (Sky) da Bluesky.
Estilo geométrico: pontos e linhas rectas, sem curvas no símbolo.

## Estrela dourada (assinatura da marca)
O olho do mastodonte é uma estrela de quatro pontas dourada. É o único elemento dourado da marca e tem dois significados na app:
- **Notificação por ler.** Em vez de um ponto vermelho, usa `.star-badge` junto ao separador de notificações.
- **Identidade.** Marca a tua conta: contas com sessão activa na janela de configuração e os teus próprios posts.

Regra de parcimónia: o dourado aparece no máximo uma vez por ecrã, em vista normal, para continuar a significar "isto é para ti". Não usar como decoração, nem em botões.

## Paleta
| Nome | Hex | Uso |
|---|---|---|
| Noite | `#0B1020` | Fundo escuro, ícone da app, texto em fundo claro |
| Índigo | `#5B4BDB` | Cor principal; Mastodon; acção primária no tema claro |
| Azul céu | `#4DB2FF` | Apoio; Bluesky no tema escuro; "Sky" no logótipo escuro |
| Ouro estelar | `#FFD66B` | Estrela de identidade e notificações |
| Névoa | `#EEF0FF` | Fundo claro e superfícies |

Variantes de contraste para fundo claro: azul profundo `#0A78D6` (Bluesky e "Sky") e ouro `#F0B400`. Índigo claro `#9AA0FF` para texto e links em fundo escuro.
O azul céu `#4DB2FF` sobre branco tem cerca de 2,3:1: nunca o uses como texto em fundo claro.

## Tipografia
- Logótipo e cartões: letras desenhadas em linha única geométrica, em contornos no próprio SVG (sem fontes).
- Interface: stack do sistema (`system-ui, -apple-system, "Segoe UI", sans-serif`) e `ui-monospace` para handles.
- Frases em minúsculas com maiúscula inicial (sentence case). Sem tudo em maiúsculas.

## Uso do símbolo
- Espaço livre à volta: pelo menos a largura do olho (a estrela dourada) em todos os lados.
- Tamanho mínimo do símbolo completo: 32 px de altura. Abaixo disso usa só a estrela dourada (`star-badge.svg` ou `favicon.svg`).
- Fundo escuro: `*-dark.svg`. Fundo claro: `*-light.svg`. Uma só cor: `logo-mark-mono.svg` (herda `currentColor`).
- Não: rodar, esticar, trocar as cores, acrescentar sombras ou brilhos, nem desenhar a estrela dourada noutro sítio do símbolo.
- Não usar as marcas da Bluesky e do Mastodon dentro do logótipo. Para distinguir redes nos posts, usa a cor mais um rótulo de texto.

## Ficheiros
Todos os SVG são vectores simples (sem fontes, filtros ou efeitos) com grupos nomeados (`symbol`, `wordmark`, `tagline`, `background`, `background-stars`) para editar em Inkscape, Figma ou Illustrator.

**Fundo transparente** (para usar sobre qualquer fundo):
- `logo-mark-dark.svg`, `logo-mark-light.svg`, `logo-mark-mono.svg`
- `logo-lockup-dark.svg`, `logo-lockup-light.svg`
- `star-badge.svg` (a estrela dourada isolada; serve de favicon transparente)
- `app-icon-transparent.svg` (constelação e estrelas, sem o quadrado)
- `social-card-en-transparent-dark.svg`, `social-card-en-transparent-light.svg`

**Com fundo Noite** (prontos a publicar):
- `favicon.svg` e `app-icon.svg`
- `social-card-en.svg` e `social-card-en.png` (1200×630, inglês; banner do `README.md`)
- `social-card-pt.svg` (português; banner do `README.pt.md`; texto editável com fontes do sistema)

**Edição e exportação**
- `social-card-en-live-text.svg`: igual ao cartão em inglês, mas com a frase como texto editável (usa fontes do sistema).
- Redes sociais (Open Graph) pedem PNG ou JPG, não SVG: usa `social-card-en.png`.
- `source/build_brand.py` regenera tudo (Python 3, sem dependências). Para mudar a frase em contornos, edita `TAG_EN` e corre o script; só há desenho para as letras definidas em `GLYPHS`.
- `source/render_png.py` exporta qualquer um destes SVG para PNG (requer `matplotlib`).
- `tokens.css`: variáveis CSS para tema claro e escuro, mais a classe `.star-badge`.
