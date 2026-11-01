# MastoSky Background Startup / Arranque em Segundo Plano

Templates and instructions to run MastoSky automatically in the background on system startup or user login.

---

## 🍎 macOS (launchd)

1. Copy `docs/launchd/com.mastosky.plist` to `~/Library/LaunchAgents/`:
   ```bash
   cp docs/launchd/com.mastosky.plist ~/Library/LaunchAgents/
   ```
2. Edit `~/Library/LaunchAgents/com.mastosky.plist` and update the `WorkingDirectory` key with the absolute path to your MastoSky folder (e.g. `/Users/yourusername/MastoSky`).
3. Load the service:
   ```bash
   launchctl load ~/Library/LaunchAgents/com.mastosky.plist
   ```
4. To unload/stop:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.mastosky.plist
   ```

---

## 🐧 Linux (systemd --user)

1. Create the user systemd directory if it doesn't exist:
   ```bash
   mkdir -p ~/.config/systemd/user
   ```
2. Copy `docs/systemd/mastosky.service`:
   ```bash
   cp docs/systemd/mastosky.service ~/.config/systemd/user/
   ```
3. Enable and start the user service:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now mastosky.service
   ```
4. To check status or stop:
   ```bash
   systemctl --user status mastosky.service
   systemctl --user stop mastosky.service
   ```
