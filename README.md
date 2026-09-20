<h1 align="center">🎬 TamilMV RSS Telegram Bot</h1>

<p align="center">
  <b>An automated, high-performance Telegram bot that scrapes the latest torrent releases from 1TamilMV and posts them directly to your Telegram channel with thumbnails and metadata.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Pyrogram-Fork-green.svg?style=for-the-badge&logo=telegram&logoColor=white" alt="Pyrogram">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED.svg?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge" alt="License">
</p>

---

## ✨ Features

- 🚀 **Automated 1TamilMV Crawling**: Automatically checks for new forum topics, direct download links, and torrent files every 5 minutes.
- 🖼️ **Movie Poster & Direct Link Posts**: Fetches movie poster images and direct download links (e.g. Cyberloom), posting clean summary photo messages before sending torrent files.
- 📁 **Torrent File Delivery**: Downloads and sends `.torrent` files directly to your channel with custom thumbnails, release metadata, and file sizes.
- ⚡ **Non-Blocking Asynchronous Engine**: Web scraping and file downloads run on dedicated worker threads, ensuring Telegram MTProto keepalives never freeze.
- 🛡️ **24/7 Supervisor Recovery**: Built-in background supervisor automatically catches transient network errors and restarts scraping cycles without crashing.
- ⏳ **Smart FloodWait Protection**: Gracefully catches Telegram rate limits and retries automatically without spamming or dropping connections.
- 🐳 **VPS & Docker Ready**: Includes `docker-compose.yml` and `Dockerfile` configured with `restart: unless-stopped` and unbuffered logging for rock-solid 24/7 uptime.
- 🌐 **Web Health Check**: Integrated lightweight Flask server on port `5000` for platforms like Render, Koyeb, and Heroku.

---

## 📋 Environment Variables

Create a `.env` file in the root directory (or configure them in your hosting provider):

| Variable | Required | Description | Example |
| :--- | :---: | :--- | :--- |
| `TOKEN` | **Yes** | Telegram Bot Token from [@BotFather](https://t.me/BotFather) | `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ` |
| `API_ID` | **Yes** | Telegram API ID from [my.telegram.org](https://my.telegram.org) | `1234567` |
| `API_HASH` | **Yes** | Telegram API Hash from [my.telegram.org](https://my.telegram.org) | `0123456789abcdef0123456789abcdef` |
| `OWNER` | **Yes** | Telegram User ID of the owner (from [@userinfobot](https://t.me/userinfobot)) | `1892771262` |
| `CHANNEL_ID` | **Yes** | Target Channel ID (bot must be admin with Post permission) | `-1002194076115` |
| `PORT` | No | Port for Flask web server (default: `5000`) | `5000` |

---

## 🚀 Deployment & Running

### Option 1: Docker Compose on VPS (Recommended)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/GouthamSER/Tamilmv-Rss-Bot.git
   cd Tamilmv-Rss-Bot
   ```

2. **Configure environment variables:**
   ```bash
   nano .env
   ```
   Paste your credentials into `.env`:
   ```env
   TOKEN=your_bot_token
   API_ID=your_api_id
   API_HASH=your_api_hash
   OWNER=your_owner_id
   CHANNEL_ID=your_channel_id
   ```

3. **Start the bot in the background (24/7):**
   ```bash
   docker compose up -d --build
   ```

4. **Monitor logs in real-time:**
   ```bash
   docker compose logs -f
   ```

5. **Stop or Restart:**
   ```bash
   docker compose restart
   docker compose down
   ```

---

### 🖥️ Running with tmux + Docker (Prevents SSH Disconnects)

Using `tmux` creates a persistent terminal session on your VPS so you can monitor live logs 24/7 without worrying about SSH terminal disconnects:

1. **Install tmux on your VPS:**
   ```bash
   apt update && apt install -y tmux
   ```

2. **Create a new session:**
   ```bash
   tmux new -s bot
   ```

3. **Start the bot & monitor logs:**
   ```bash
   cd Tamilmv-Rss-Bot
   docker compose up -d --build
   docker compose logs -f
   ```

4. **Detach from tmux (safe to close SSH):**
   - Press `Ctrl + B`, release, then press `D`.

5. **Reattach to check logs anytime:**
   ```bash
   tmux attach -t bot
   ```

#### 💡 tmux Cheat Sheet

| Action | Command / Shortcut |
| :--- | :--- |
| **New Session** | `tmux new -s bot` |
| **Detach (Keep running)** | `Ctrl + B` then `D` |
| **Reattach (Resume session)**| `tmux attach -t bot` |
| **List Sessions** | `tmux ls` |
| **Kill Session** | `tmux kill-session -t bot` |
| **Scroll Logs** | `Ctrl + B` then `[` (arrow keys to scroll, `q` to exit) |

---

### Option 2: Plain Docker CLI

1. **Build the image:**
   ```bash
   docker build -t tamilmv-bot .
   ```

2. **Run the container with automatic restart:**
   ```bash
   docker run -d \
     --name tamilmv-bot \
     --restart unless-stopped \
     --env-file .env \
     -p 5000:5000 \
     tamilmv-bot
   ```

3. **View live logs:**
   ```bash
   docker logs -f tamilmv-bot
   ```

---

### Option 3: Local Environment (Python)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/GouthamSER/Tamilmv-Rss-Bot.git
   cd Tamilmv-Rss-Bot
   ```

2. **Create a virtual environment & install requirements:**
   ```bash
   python -m venv venv
   # On Linux/macOS:
   source venv/bin/activate
   # On Windows:
   venv\Scripts\activate

   pip install -r requirements.txt
   ```

3. **Run the bot:**
   ```bash
   python bot.py
   ```

---

### Option 4: Cloud Platforms (Render / Koyeb)

#### **Render**
1. Fork or push this repository to GitHub.
2. Create a new **Web Service** on [Render](https://render.com).
3. Connect your repository.
4. Set:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
5. Add the required environment variables in the **Environment** tab.

#### **Koyeb**
1. Create a new App on [Koyeb](https://www.koyeb.com).
2. Connect your repository and select **Dockerfile** deployment.
3. Configure the environment variables and deploy.

---

## 📌 Important Notes

- **Channel Permissions**: Ensure your bot is added as an **Administrator** in your target Telegram channel with permission to **Post Messages**.
- **First Run Caching**: When the bot boots up for the first time, it records existing torrents in memory so it doesn't spam older posts. Only freshly uploaded torrents will be dispatched to your channel.
- **Auto-Restart on VPS**: The `--restart unless-stopped` flag in Docker Compose guarantees that the bot will automatically come back online if your VPS reboots or experiences temporary disruptions.

---

## 👥 Contributors

- **[MNTGXO](https://github.com/MNTGXO)** — Original code & contributor

---

## 👨‍💻 Credits & Contact

- **Developer & Support**: [@im_goutham_josh](https://t.me/im_goutham_josh)
- **Contributor & Inspiration**: [MNTGXO](https://github.com/MNTGXO)
- **Updates Channel**: [TamilMV Kuttu](https://t.me/tamilmvkuttu)
- **Source Code**: [GitHub Repository](https://github.com/GouthamSER/Tamilmv-Rss-Bot)

---

## 📄 License

This project is licensed under the **[MIT License](LICENSE)**. Feel free to modify and distribute.
