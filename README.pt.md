<p align="right">
  <a href="README.md">English</a> | <b>Português</b>
</p>

# MastoSky 🌌🐘

> **Cliente unificado, minimalista e *local-first* para Bluesky e Mastodon.**  
> Uma única interface no teu browser para ler, responder, partilhar e publicar em ambas as redes simultaneamente. Sem dependências externas, sem telemetria, sem intermediários.

---

## ✨ Funcionalidades

* **🔄 Timeline Unificada:** Visualiza os posts das pessoas que segues no Bluesky e no Mastodon misturados cronologicamente numa única página.
* **🔥 Aba "Em Alta":** Descobre o que está a ser mais partilhado e com mais interação em ambas as redes (mesmo de perfis que não segues).
* **🔔 Notificações Centralizadas:** Vê respostas, gostos, partilhas (*boosts* / *reposts*) e citações com contador de novos alertas em tempo real.
* **📝 Publicação Cruzada com 1 Clique:** Escreve um post e escolhe se queres publicar apenas no Bluesky, apenas no Mastodon ou em ambos em simultâneo com contagem de caracteres inteligente.
* **💬 Citações Ricas (*Quote Posts*):** Suporte nativo a publicações citadas de ambas as redes, com identificação do autor original, texto e imagens.
* **🎬 Leitor de Vídeo Integrado:** Suporte transparente para streaming adaptativo HLS (`.m3u8` do Bluesky) e ficheiros de vídeo/animações (`.mp4` e `gifv` do Mastodon).
* **🖼️ Suporte a Imagens e Cartões de Links:** Pré-visualização de imagens sem cortes forçados, zoom em tamanho original e cartões de link com domínio.
* **📊 Sondagens:** Cria sondagens com opções personalizadas e duração ajustável.
* **⚠️ Avisos de Conteúdo (*Content Warning* / Spoiler):** Marca spoilers ou avisos sensíveis que são respeitados e integrados com as regras nativas de ambas as plataformas.
* **🧵 Conversas e Fios:** Explora discussões completas em árvore com o botão de conversa.
* **🌗 Modo Claro e Escuro:** Respeita automaticamente o tema do teu sistema operativo.

---

## 🔒 Filosofia: Zero Dependências & Privacidade Absoluta

* **Zero dependências externas:** Construído apenas com a biblioteca padrão do **Python 3** no servidor e **Vanilla JavaScript / CSS** no cliente. Nada de `pip install`, nem Node.js, nem NPM.
* **100% Local-First:** O servidor corre estritamente em `127.0.0.1` (localhost).
* **Privacidade total:** As tuas credenciais e dados nunca passam por servidores de terceiros ou serviços de recolha de dados; o teu computador comunica diretamente com a API do Bluesky e com a tua instância do Mastodon.

---

## 🚀 Como Executar

### Pré-requisitos
Apenas precisas do **Python 3** instalado (já vem por defeito no macOS e na maioria das distribuições Linux).

### 1. Clonar o repositório
```bash
git clone https://github.com/gjmcosta/MastoSky.git
cd MastoSky
```

### 2. Iniciar a aplicação
```bash
python3 app.py
```

### 3. Abrir no Browser
Acede a:
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

Se for a primeira vez que abres a ferramenta, surge automaticamente o **ecrã de configuração** para introduzires as tuas credenciais do Bluesky e/ou do Mastodon.

*(Em alternativa, podes copiar `cp config.example.json config.json` e preencher manualmente antes de iniciar).*

---

## 🔑 Onde obter as credenciais?

### 🦋 Bluesky
1. Vai a [bsky.app](https://bsky.app) e acede a **Definições** (*Settings*) > **Privacidade e Segurança** > **Palavras-passe da aplicação** (*App Passwords*).
2. Cria uma nova palavra-passe com o nome `MastoSky`.
3. Utiliza o teu handle (ex: `oteunome.bsky.social`) e a palavra-passe gerada (formato `xxxx-xxxx-xxxx-xxxx`).
*(Nota: Nunca uses a tua palavra-passe principal da conta; usa sempre uma App Password!)*

### 🐘 Mastodon
1. Acede à tua instância do Mastodon (ex: `https://masto.pt`, `https://mastodon.social`, etc.).
2. Vai a **Preferências** (*Preferences*) > **Desenvolvimento** (*Development*) > **Nova aplicação** (*New Application*).
3. Dá o nome `MastoSky`. Podes deixar as permissões padrão (`read`, `write`) e clicar em **Guardar**.
4. Clica na aplicação criada e copia o **Token de acesso** (*Your access token*).

---

## 📁 Estrutura do Projeto

```text
MastoSky/
├── app.py              # Servidor HTTP local e clientes de API (ATProto / ActivityPub)
├── index.html          # Interface de utilizador completa (HTML, CSS e JavaScript vanilla)
├── config.example.json # Modelo de configuração de exemplo
├── .gitignore          # Bloqueio de segurança para credenciais e ficheiros temporários
└── README.md           # Documentação
```

---

## 🛡️ Segurança

O ficheiro com as tuas credenciais pessoais (`config.json`) está protegido pelo ficheiro `.gitignore` e **nunca** deve ser adicionado ao controlo de versões.

---

## 📄 Licença

Este projeto é de código aberto sob a licença [MIT](LICENSE).
