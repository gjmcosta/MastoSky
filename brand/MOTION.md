# MastoSky — Motion Design

Sistema de movimento editorial para a identidade MastoSky, construído inteiramente em **SVG + CSS nativos (sem dependências externas)** e desenhado para respeitar todas as regras de [BRAND.md](BRAND.md).

---

## Classificação e Conceito

- **Classificação:** Constelação Geométrica / Line Art + Wordmark Monolinha (`stroke-dominant`)
- **Conceito narrativo:** O mastodonte não "salta" nem se deforma — forma-se como um mapa celeste. Primeiro acendem-se os vértices no céu nocturno, depois traçam-se as ligações da constelação e o logótipo em linha única, e por fim acende-se o **olho em estrela dourada** como assinatura de identidade e notificação.
- **Curva de easing:** `cubic-bezier(0.16, 1, 0.3, 1)` (saída rápida e assento longo, preciso e calmo — alinhado com o carácter astronómico e local-first da marca).
- **Duração total:**
  - Símbolo isolado (`logo-mark-*-animated.svg`): **2,25 s**
  - Logótipo completo e cartões (`logo-lockup-*-animated.svg`, `social-card-*-animated.svg`, previews Full HD): **2,75 s**
  - Emblema de notificação (`star-badge-animated.svg`): ignição de **0,55 s** + respiração cíclica de **3,6 s**

---

## Estrutura em 3 Actos

| Acto | Janela | Elementos | Técnica |
|---|---|---|---|
| **Acto 1 — Antecipação** | `0.00 s – 0.65 s` | 22 estrelas-vértice (`#symbol-stars`) em 4 grupos anatómicos + estrelas de fundo | `opacity: 0 → 1` e escala uniforme `0.35 → 1` (`transform-origin: center`) |
| **Acto 2 — Construção** | `0.22 s – 2.00 s` | 8 traços anatómicos da constelação (`#symbol-lines`) e 8 letras monolinha (`Masto` + `Sky`) | Path trim (`pathLength="1"`, `stroke-dashoffset: 1 → 0`) sequencial |
| **Acto 3 — Resolução** | `1.85 s – 2.75 s` | Tagline (nos cartões/previews) e olho em estrela dourada (`#symbol-eye`) | Elevação suave da tagline (`+6px → 0`) e ignição com micro-pulso uniforme (`0 → 1.18 → 1`) do olho dourado |

---

## Conformidade estrita com `BRAND.md`

- **Sem rotação:** nenhuma rotação aplicada ao símbolo, às estrelas ou às letras.
- **Sem deformação (`stretch`):** apenas escala uniforme centrada no próprio elemento (`transform-box: fill-box; transform-origin: center`).
- **Sem sombras nem brilhos:** zero `drop-shadow`, `filter: blur` ou efeitos no símbolo.
- **Paleta exata por tema:**
  - Escuro: `#8F96FF` (linhas), `#FFFFFF` (estrelas e `Masto`), `#4DB2FF` (`Sky`), `#FFD66B` (olho), `#0B1020` (Noite).
  - Claro: `#5B4BDB` (linhas e estrelas), `#0B1020` (`Masto`), `#0A78D6` (`Sky`), `#F0B400` (olho).
  - Monocromático: `currentColor`.
- **Acessibilidade:** todos os ficheiros incluem `@media (prefers-reduced-motion: reduce)` para desativar animações e apresentar o estado final estático de imediato.

---

## Ficheiros Criados

| Ficheiro | Dimensão / `viewBox` | Uso recomendado |
|---|---|---|
| `logo-mark-dark-animated.svg` | `0 0 160 120` | Símbolo animado para fundos escuros |
| `logo-mark-light-animated.svg` | `0 0 160 120` | Símbolo animado para fundos claros |
| `logo-mark-mono-animated.svg` | `0 0 160 120` | Símbolo monocromático (`currentColor`) |
| `logo-lockup-dark-animated.svg` | `0 0 530 120` | Logótipo completo para cabeçalho escuro |
| `logo-lockup-light-animated.svg` | `0 0 530 120` | Logótipo completo para cabeçalho claro |
| `star-badge-animated.svg` | `0 0 24 24` | Estrela dourada isolada animada |
| `social-card-pt-animated.svg` | `1200×630` | Cartão editorial animado (PT) |
| `social-card-en-animated.svg` | `1200×630` | Cartão editorial animado (EN) |
| `preview-landscape-1080p.svg` | `1920×1080` | Frame Full HD 16:9 (vídeo / apresentação) |
| `preview-portrait-1080p.svg` | `1080×1920` | Frame Full HD 9:16 (Reels / Shorts / mobile) |
| `motion.css` | — | Tokens CSS, `.star-badge-pulse` e classes `.ms-anim-svg` |

---

## Como usar e exportar

1. **Na web / interface:** incorporar como `<img src="...">` (a animação CSS corre autonomamente dentro do SVG) ou importar `brand/motion.css` quando o SVG estiver inline.
2. **Para vídeo (MP4 / WebM / GIF):** abrir `preview-landscape-1080p.svg` ou `preview-portrait-1080p.svg` no browser em 1920×1080 ou 1080×1920 e gravar os primeiros 3–5 segundos.
