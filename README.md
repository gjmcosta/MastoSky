<p align="right">
  <b>English</b> | <a href="README.pt.md">Português</a>
</p>

# MastoSky 🌌🐘

> **A minimalist, unified, local-first client for Bluesky and Mastodon.**  
> One single browser tab to read, reply, boost/repost, and cross-publish across both networks simultaneously. Zero external dependencies, no telemetry, no intermediaries.

---

## ✨ Features

* **🔄 Unified Timeline:** Read posts from the people you follow on both Bluesky and Mastodon, seamlessly interleaved in chronological order.
* **🔥 Explore / "What's Hot":** Discover trending posts and viral conversations from both networks, even from accounts you don't follow.
* **🔔 Centralized Notifications:** Track mentions, replies, likes, boosts, and quote posts in real-time with an unread badge.
* **📝 1-Click Cross-Posting:** Compose once and choose whether to publish to Bluesky, Mastodon, or both at the same time, with live network-specific character count limits.
* **💬 Native Quote Posts:** Rich rendering of quoted posts from both networks with quoted author avatars, text, and embedded media.
* **🎬 Integrated Video Player:** Transparent HTML5 playback for both adaptive HLS streams (`.m3u8` from Bluesky) and direct video / animated files (`.mp4` and `gifv` from Mastodon).
* **🖼️ Media Galleries & Link Previews:** Uncropped image previews with full-size zoom on click, plus compact external link cards with domain labels.
* **📊 Interactive Polls:** Create cross-network polls with customizable options and expiration periods.
* **⚠️ Content Warnings (CW / Spoilers):** Seamless spoiler labels that translate to native Mastodon CWs and Bluesky content labels.
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
  python3 app.py
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
3. Name it `MastoSky`. Leave the default permissions (`read`, `write`) and click **Save**.
4. Click on your newly created app and copy **Your access token**.

---

## 📁 Project Structure

```text
MastoSky/
├── MastoSky.command    # 1-Click launcher for macOS
├── MastoSky.bat        # 1-Click launcher for Windows
├── app.py              # Local HTTP server and API clients (ATProto / ActivityPub)
├── index.html          # Complete single-page UI (vanilla HTML, CSS, JavaScript)
├── config.example.json # Configuration template
├── .gitignore          # Security guard preventing credentials from being committed
├── README.md           # Documentation (English)
├── README.pt.md        # Documentation (Português)
└── LICENSE             # MIT License
```

---

## 🛡️ Security

Your personal credentials file (`config.json`) is strictly ignored by `.gitignore` and **must never** be committed to version control.

---

## 📄 License

This project is open-source under the [MIT License](LICENSE).
