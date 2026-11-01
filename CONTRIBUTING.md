# Contributing to MastoSky / Guia de Contribuição

Thank you for your interest in contributing to **MastoSky**! / Obrigado pelo interesse em contribuir para o **MastoSky**!

---

## 🔒 Core Principles & Architecture Rules / Princípios Fundamentais

To preserve the security, privacy, and minimalist philosophy of MastoSky, all contributions must respect the following core constraints:

1. **Zero External Dependencies / Zero Dependências Externas**
   - **Backend:** Only standard library modules included with **Python 3.9+**. Never add `requirements.txt`, `pip` dependencies, or external packages.
   - **Frontend:** Vanilla HTML, CSS, and modern JavaScript only. No frameworks (React, Vue, etc.), no bundlers (Webpack, Vite), and no external CDNs or analytics scripts.

2. **Strict Localhost & Privacy Isolation / Isolamento Absoluto em Localhost**
   - The server must **always** bind strictly to `127.0.0.1` (`localhost`). Never listen on `0.0.0.0` or allow external network exposure.
   - Host and Origin header validation (`allowed()`) and Content Security Policy (`CSP`) must remain intact.
   - **Zero telemetry, analytics, or third-party tracking.** Your computer speaks directly to Bluesky and Mastodon APIs only.

3. **No Secrets in Version Control / Nunca Enviar Segredos**
   - `config.json` is ignored by `.gitignore` and must **never** be committed.
   - Do not include personal tokens, passwords, handles, or private test data in tests or commits.

4. **Testing Required / Testes Obrigatórios**
   - All parser logic, API handlers, security guards, and edge cases must have unit test coverage.
   - Before submitting a pull request, run the test suite:
     ```bash
     python3 -m unittest discover -s tests -v
     python3 -m py_compile app.py
     ```
   - All tests must pass with zero errors.

5. **Design Tokens & Brand Consistency / Identidade Visual**
   - UI elements and colors should adhere to `brand/BRAND.md` and `brand/tokens.css`.
   - Maintain full support for both Light and Dark operating system color schemes.

---

## 🛠️ Submitting Changes / Como Submeter Alterações

1. **Fork** the repository and create a new feature branch (`git checkout -b feature/minha-melhoria`).
2. Make granular, focused commits with clear messages in English or Portuguese (e.g. `F1: suporte a menções no Bluesky`).
3. Ensure both `README.md` and `README.pt.md` are updated if user-facing behavior changes.
4. Open a Pull Request on GitHub describing your changes and testing performed.
