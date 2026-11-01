<p align="right">
  <b>English</b> | <a href="README.pt.md">Português</a>
</p>

<p align="center">
  <img src="brand/social-card-en.png" alt="MastoSky" width="600">
</p>

# MastoSky

> **A minimalist, unified, local-first client for Bluesky and Mastodon.**  
> One single browser tab to read, reply, boost/repost, and cross-publish across both networks simultaneously. Zero external dependencies, no telemetry, no intermediaries.

---

## ✨ Features

* **🔄 Unified Timeline:** Read posts from the people you follow on both Bluesky and Mastodon, seamlessly interleaved in chronological order.
* **🗂️ Multi-Column Deck View:** Seamlessly switch between a classic single-column timeline and a TweetDeck / Mastodon Advanced-style multi-column layout with customizable columns (Composer, Timeline, Trending, Notifications, Profile) and a dedicated side detail panel for threads and user inspection.
* **🌍 Bilingual Interface (i18n):** Instant 1-click toggle between Portuguese and English with persistent user preference and complete translation of all feeds, dialogs, and notices.
* **🧭 Flexible Navigation Modes:** Customize your browsing flow with a floating side-dock navigation rail, a sticky top header, or a static layout.
* **🎨 Custom Minimalist Brand Icons:** Crisp geometric SVG icons with stateful Mastodon visibility indicators (Public, Unlisted, Followers, Direct) and vibrant network constellation badges.
* **🔥 Explore / "What's Hot":** Discover trending posts and viral conversations from both networks, even from accounts you don't follow.
* **🔔 Centralized Notifications:** Track mentions, replies, likes, boosts, and quote posts in real-time with an unread badge.
* **👤 Profiles & Author Feeds:** View your Bluesky and Mastodon profiles side-by-side with avatars, bios, follower statistics, and your own published posts with fast network filtering and post deletion.
* **📝 1-Click Cross-Posting:** Compose once and choose whether to publish to Bluesky, Mastodon, or both at the same time, with live network-specific character count limits.
* **💬 Native Quote Posts:** Rich rendering of quoted posts from both networks with quoted author avatars, text, and embedded media.
* **🎬 Integrated Video Player:** Transparent HTML5 playback for both adaptive HLS streams (`.m3u8` from Bluesky) and direct video / animated files (`.mp4` and `gifv` from Mastodon).
* **🖼️ Media Galleries & Link Previews:** Uncropped image previews with full-size zoom on click, plus compact external link cards with domain labels.
* **📊 Interactive Polls:** Create polls with customizable options and expiration periods (native on Mastodon; formatted as clean text with voting options on Bluesky).
* **⚠️ Content Warnings (CW / Spoilers):** Add content warnings to sensitive posts (native spoiler text on Mastodon; clear `⚠️ [CW: ...]` text prefix on Bluesky).
* **🌐 Language & Visibility Controls:** Automatic post language tagging (`default_lang` in config) and customizable Mastodon post visibility (Public, Unlisted, Followers-only, Direct).
* **🧵 Conversation Threads:** Expand and follow complete conversation trees directly inline.
* **🌗 Dark & Light Themes:** Automatically matches your operating system's color scheme.

---

## 🔒 Philosophy: Zero Dependencies & Privacy by Design

* **Zero external dependencies:** Powered solely by the **Python 3 standard library** on the backend and **vanilla JavaScript & CSS** on the frontend. No `pip install`, no Node.js, no NPM.
* **100% Local-First:** The server binds strictly to `127.0.0.1` (localhost).
* **Total Privacy:** Your credentials and social data never pass through third-party servers; your computer talks directly to the official Bluesky ATProto XRPC endpoints and your own Mastodon instance API.

---

## 🚀 Getting Started

### Prerequisites
You only need **Python 3** installed (built-in on macOS and most Linux distributions).

### 1. Clone the repository
```bash
git clone https://github.com/gjmcosta/MastoSky.git
cd MastoSky
```

### 2. Start the application

Choose your preferred way to launch MastoSky:

* **🍎 macOS:** Double-click **`MastoSky.command`** (launches the server and automatically opens your browser).
* **🪟 Windows:** Double-click **`MastoSky.bat`** (launches the server and automatically opens your browser).
* **💻 Terminal (any OS):**
  ```bash
  python3 app.py --open
  ```

#### CLI Options
```text
python3 app.py [-h] [--port PORT] [--open] [--verbose]

Options:
  --port PORT   Local HTTP port (overrides config.json or default 8000)
  --open        Automatically open default web browser on launch
  --verbose     Log non-sensitive HTTP requests to stderr
```

### 3. Open in your browser
If it doesn't open automatically, navigate to:  
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

On your first launch, a friendly **Setup Window** will automatically appear to let you enter your Bluesky and/or Mastodon credentials right in the browser UI.

*(Alternatively, you can copy `cp config.example.json config.json` and edit it manually before starting).*

---

## 🔑 Obtaining Your Credentials

### 🦋 Bluesky
1. Go to [bsky.app](https://bsky.app) and navigate to **Settings** > **Privacy and Security** > **App Passwords**.
2. Create a new App Password named `MastoSky`.
3. Use your handle (e.g. `yourname.bsky.social`) and the generated 16-character password (`xxxx-xxxx-xxxx-xxxx`).
*(Note: Never use your primary account password; always use an App Password!)*

### 🐘 Mastodon
1. Go to your Mastodon instance (e.g. `https://masto.pt`, `https://mastodon.social`, etc.).
2. Navigate to **Preferences** > **Development** > **New Application**.
3. Name it `MastoSky`. **Untick** the default scopes (`read`, `write`, `follow`, `push`) and tick only the minimum MastoSky needs: `read:statuses read:notifications write:statuses write:media write:favourites`. Click **Save**.
4. Click on your newly created app and copy **Your access token**.

---

## 📁 Project Structure

```text
MastoSky/
├── MastoSky.command    # 1-Click launcher for macOS
├── MastoSky.bat        # 1-Click launcher for Windows
├── app.py              # Local HTTP server and API clients (ATProto / ActivityPub)
├── index.html          # Complete single-page UI (vanilla HTML, CSS, JavaScript)
├── brand/              # Visual identity, tokens and vector assets (see brand/BRAND.md)
├── docs/               # Background services (launchd, systemd) and extra docs
├── config.example.json # Configuration template
├── CONTRIBUTING.md     # Guidelines for contributors
├── .gitignore          # Security guard preventing credentials from being committed
├── README.md           # Documentation (English)
├── README.pt.md        # Documentation (Português)
└── LICENSE             # MIT License
```

---

## 🔄 Running in the Background

Want MastoSky to start automatically on system startup? Check out the ready-to-use service templates in [`docs/`](docs/README.md):
* **macOS:** [`docs/launchd/com.mastosky.plist`](docs/launchd/com.mastosky.plist)
* **Linux:** [`docs/systemd/mastosky.service`](docs/systemd/mastosky.service)

---

## 🤝 Contributing

Contributions are warmly welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for our principles: zero runtime dependencies, strict localhost isolation (`127.0.0.1`), and mandatory unit tests.

---

## 🛡️ Security & Threat Model

MastoSky is built around a strict **local-first, zero-telemetry** architecture. Since the core pitch is *"Your credentials stay on your machine"*, the system enforces defense-in-depth across every boundary:

### 1. Localhost Isolation (Network Boundary)
* The HTTP server binds exclusively to `127.0.0.1` (loopback interface). It **never** binds to `0.0.0.0` or public network adapters. Other devices on your local Wi-Fi or LAN cannot access your MastoSky instance or port.

### 2. DNS Rebinding & Host Enforcement
* Every request verifies the HTTP `Host` header against an explicit whitelist (`127.0.0.1:{PORT}` and `localhost:{PORT}`). Requests carrying spoofed or external hostnames (e.g. malicious domains resolving to `127.0.0.1` via DNS rebinding) are immediately rejected with `403 Forbidden`.

### 3. Cross-Origin Protection & Per-Session CSRF Token
* When you browse the web in the same browser, malicious websites cannot interact with your local MastoSky instance:
  * **Strict Origin Validation:** The server rejects any request carrying a foreign `Origin` header (`403 Forbidden`).
  * **Per-Session CSRF Token:** On startup, the server generates a cryptographically random token (`secrets.token_hex(32)`) injected into the UI. Every state-changing request (`/api/post`, `/api/action`, `/api/setup`) must supply this token via the `X-CSRF-Token` header.
  * **Same-Origin Policy:** Third-party websites cannot read this token due to the browser's Same-Origin Policy.
  * **Mandatory CORS Preflight:** The custom `X-CSRF-Token` header forces browsers to trigger an `OPTIONS` preflight, preventing blind `<form>`, `<img>`, or `sendBeacon` submissions from foreign origins.

### 4. Frame Sandboxing & Content Security Policy (CSP)
* All responses include strict security headers:
  * `Content-Security-Policy: frame-ancestors 'none'; base-uri 'none'; form-action 'none'` (prevents framing and clickjacking).
  * `X-Frame-Options: DENY`
  * `X-Content-Type-Options: nosniff`
  * `Referrer-Policy: no-referrer`

### 5. SSRF (Server-Side Request Forgery) Mitigation
* The local image proxy (`/api/proxy_image`) parses and verifies target IP addresses before fetching, strictly blocking private, loopback, or link-local subnets (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).

### 6. Credential Storage
* Your credentials (App Passwords and Access Tokens) are stored locally in `config.json` with restricted file permissions (`0600` — readable only by your user account). They are never transmitted to any third-party server, analytics service, or proxy — only directly to the official Mastodon instance and Bluesky API endpoints you configure. The file is also strictly ignored by `.gitignore`.

---

## 📄 License

This project is open-source under the [MIT License](LICENSE).
