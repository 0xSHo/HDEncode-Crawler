# 🎬 HDEncode Crawler

Ein automatischer Crawler für [HDEncode.org](https://hdencode.org), der die persönliche Letterboxd-Watchlist regelmäßig mit aktuellen Releases abgleicht und bei einem Treffer automatisch eine Benachrichtigung über Telegram versendet.

---

## ✨ Features

- ✅ Automatische Synchronisierung deiner Letterboxd-Watchlist in ein Google Sheet
- ✅ Überwachung des HDEncode-RSS-Feeds
- ✅ Abgleich mit Watchlist aus Google Sheet (Fallback: lokale `watchlist.csv`)
- ✅ Telegram-Benachrichtigung bei Match (inkl. Download-Link)
- ✅ Telegram-Bot-Kommandos:
  - `/status` – zeigt den aktuellen Zustand des Watchers
  - `/suche <Titel>` – durchsucht den aktuellen RSS-Feed
  - `/suchealle <Titel>` – durchsucht bis zu 25 Seiten der HDEncode-Webseite

---

## 🧰 Voraussetzungen

- Python 3.8+
- Telegram-Bot-Token (via [@BotFather](https://t.me/botfather) erstellen)
- Telegram Chat-ID
- Python-Virtualenv (empfohlen)
- Google Drive Account
- Service Account + `client_secret.json`* mit Zugriff auf ein Google Sheet

*Es ist wichtig, dass der Pfad zur client_secret.json korrekt ist. Wenn die Datei anders benannt ist oder sie sich an einem anderen Ort befindet, muss die CREDENTIALS_FILE entsprechend angepasst werden.

---

## 🔧 Installation

```bash
# Repository klonen
git clone https://github.com/0xSHo/hdencode_crawler.git
cd hdencode_crawler

# Virtuelle Umgebung einrichten
python3 -m venv venv
source venv/bin/activate

```

```bash
# requirements.txt mit folgendem Inhalt erstellen:
requests
feedparser
beautifulsoup4
python-telegram-bot==13.15
unidecode
oauth2client
gspread
playwright
```

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt
playwright install
```

📁 Projektstruktur

```bash
hdencode-watcher/
├── hdencode_crawler_linux.py    # Hauptskript (Telegram-Bot + Feed-Watcher)
├── watchlist_sync.py            # Letterboxd-Scraper → Google Sheet
├── client_secret.json           # Google API-Zugriff
├── seen_links.txt               # Bereits benachrichtigte Film-Links
├── watcher.log                  # Logfile (optional, systemd nutzt journalctl)
└── README.md
```

---

## 🔁 Automatische Watchlist-Synchronisierung

Das Skript `watchlist_sync.py` lädt die aktuelle Watchlist von  
[`letterboxd.com/<USERNAME>/watchlist/`](https://letterboxd.com/)  
und überträgt sie in ein definiertes Google Sheet.

Die Hauptdatei `hdencode_crawler_linux.py` nutzt dieses Sheet als Datenquelle. Wenn das Laden fehlschlägt, wird optional auf eine lokal gespeicherte`watchlist.csv` zurückgegriffen (Fallback).

Die Synchronisierung läuft automatisch 1× täglich via `systemd.timer`.

---

## 🤖 Konfiguration

Folgende Werte müssen in den Skripten bearbeitet werden:

 `hdencode_crawler_linux.py`

```python
TELEGRAM_TOKEN = "bot_token"
TELEGRAM_CHAT_ID = "chat_id"
SHEET = client.open_by_key("GOOGLE SHEET ID").sheet1
```

 `watchlist_sync.py`

```python
LETTERBOXD_USER = "BENUTZERNAME"
GOOGLE_SHEET_ID = "GOOGLE SHEET ID"
SHEET_NAME = "Name des ersten Tabellenblatts"
CREDENTIALS_FILE = "client_secret.json"
```

🔒 **Hinweis:** Sensible Daten wie Token oder IDs sollten idealerweise nicht direkt im Code stehen, sondern z. B. über Umgebungsvariablen oder `.env`-Dateien verwaltet werden.

---

## 🧪 Starten

```bash
python hdencode_crawler_linux.py     # startet den Telegram-Bot und Watcher
python watchlist_sync.py             # synchronisiert Letterboxd-Watchlist
```

---

## 🛠️ Als systemd-Dienst einrichten (optional)

### 1. HDEncode Watcher

`/etc/systemd/system/hdencode.service`

```ini
[Unit]
Description=HDEncode Telegram Watcher
After=network-online.target

[Service]
WorkingDirectory=/pfad/zum/projekt
ExecStart=/pfad/zum/projekt/venv/bin/python hdencode_crawler_linux.py
Restart=always
RestartSec=5s
User=dein_linux_user

[Install]
WantedBy=multi-user.target
```

Aktivieren:

```bash
sudo systemctl daemon-reexec
sudo systemctl enable hdencode.service
sudo systemctl start hdencode.service
```

---

### 2. Letterboxd Watchlist Sync (Timer)

`/etc/systemd/system/letterboxd_sync.service`

```ini
[Unit]
Description=Letterboxd Watchlist Synchronisation
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/pfad/zum/projekt
ExecStart=/pfad/zum/projekt/venv/bin/python watchlist_sync.py
User=dein_linux_user
```

`/etc/systemd/system/letterboxd_sync.timer`

```ini
[Unit]
Description=Täglicher Letterboxd-Sync

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Timer aktivieren:

```bash
sudo systemctl daemon-reexec
sudo systemctl enable --now letterboxd_sync.timer
```

Nach jeder Änderung an `.service` oder `.timer`:

```bash
sudo systemctl daemon-reload
```

---

## 📡 Telegram-Befehle

| Befehl              | Funktion                                                  |
|---------------------|-----------------------------------------------------------|
| `/status`           | Gibt aktuellen Status & letzten Check zurück              |
| `/suche <Titel>`    | Durchsucht den RSS-Feed nach einem Titel                      |
| `/suchealle <Titel>`| Durchsucht bis zu 25 Seiten auf [hdencode.org](https://hdencode.org) |
