#!/usr/bin/env python3
"""
HDEncode Watcher - Überwacht RSS-Feed und benachrichtigt bei Watchlist-Matches.
"""

import os
import time
import threading
import requests
import feedparser
import logging
# logging.disable(logging.CRITICAL)
import csv
import signal
import sys
import re
import gspread
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
from bs4 import BeautifulSoup
from datetime import datetime
from telegram.ext import Updater, CommandHandler, CallbackContext
from telegram import Update
from io import StringIO
from oauth2client.service_account import ServiceAccountCredentials

# === KONFIGURATION ===
TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""

CHECK_INTERVAL = 3600
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_LINKS_FILE = os.path.join(SCRIPT_DIR, "seen_links.txt")
WATCHLIST_CSV = os.path.join(SCRIPT_DIR, "watchlist.csv")
LOG_FILE = os.path.join(SCRIPT_DIR, "watcher.log")

# === LOGGING ===
logging.basicConfig(
    level=logging.ERROR,  # Temporär auf DEBUG für bessere Diagnose
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler()]
)

# === GLOBALS ===
last_check_time = None
seen_links_lock = threading.Lock()
watchlist_lock = threading.Lock()
running = threading.Event()
running.set()


def normalize(text):
    """Erweiterte Normalisierung für Vergleiche."""
    if not text:
        return ""

    # Entferne alle Nicht-Alphanumerischen Zeichen
    text = re.sub(r'[^a-z0-9\s]', '', text.lower())

    # Entferne mehrfache Leerzeichen
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def normalize_title_for_matching(title):
    """Normalisiert Titel für bessere Übereinstimmung."""
    if not title:
        return ""

    # Zu lowercase
    title = title.lower()

    # Entferne häufige Präfixe/Suffixe
    title = re.sub(r'^(the|a|an|der|die|das|le|la|les|el|la)\s+', '', title)

    # Entferne Sonderzeichen, aber behalte Wortgrenzen
    title = re.sub(r'[^\w\s]', ' ', title)

    # Mehrfache Leerzeichen zu einem
    title = re.sub(r'\s+', ' ', title).strip()

    return title


def check_year_match(film_year, feed_title):
    """Prüft Jahr-Übereinstimmung falls Jahr angegeben."""
    if not film_year:
        return False

    years_in_feed = re.findall(r'\b(?:19|20)\d{2}\b', feed_title)

    if not years_in_feed:
        return False

    return film_year in years_in_feed


def is_problematic_substring_match(film_name_raw, feed_title_raw):
    """
    Prüft auf problematische Kontexte wie "beast" in "gospel of the beast".
    Nutzt moderat normalisierte Texte, um Wortgrenzen zu erhalten.
    """
    film_clean = normalize_title_for_matching(film_name_raw)
    feed_clean = normalize_title_for_matching(feed_title_raw)

    problematic_cases = [
        ("beast", "gospel"),
        ("beast", "beauty"),
        ("god", "godzilla"),
        ("war", "star"),  # Beispiel: "War" nicht in "Star Wars"
    ]

    for keyword, context in problematic_cases:
        if keyword in film_clean and context in feed_clean:
            return True
    return False


def is_title_match(film_name, film_year, feed_title):
    """Exaktes Wortgruppen-Matching nur bei eigenständiger Position."""
    logging.debug(
        f"Prüfe Match: '{film_name}' ({film_year}) gegen '{feed_title}'"
    )

    def normalize(text):
        text = text.lower()
        text = text.replace(".", " ")
        text = re.sub(r"[^\w\s]", "", text)
        return re.sub(r"\s+", " ", text).strip()

    film_phrase = normalize(film_name)
    feed_text = normalize(feed_title)

    words = film_phrase.split()
    pattern = (
        r"(?:^|\b(19|20)\d{2}\b\s*)\b"
        + r"\s+".join(map(re.escape, words))
        + r"\b"
    )

    logging.debug(f"Verwendetes Pattern: {pattern}")
    if re.search(pattern, feed_text):
        logging.debug(f"🎯 Gültige Wortgruppe erkannt: '{film_phrase}' in Feed")
        return check_year_match(film_year, feed_title)

    logging.debug("⛔ Kein gültiger Titel-Block gefunden")
    return False


def load_watchlist_from_csv(csv_path=None, file_content=None):
    """Lädt die Watchlist aus einer CSV-Datei oder aus einem String."""
    if csv_path is None and file_content is None:
        logging.warning("Weder Pfad noch Dateiinhalt angegeben für Watchlist.")
        return []

    watchlist = []

    try:
        if file_content:
            f = StringIO(file_content)
        else:
            if not os.path.exists(csv_path):
                logging.warning(f"Watchlist CSV nicht gefunden: {csv_path}")
                return []
            f = open(csv_path, 'r', encoding='utf-8-sig')

        with f:
            first_line = f.readline().strip()
            f.seek(0)

            is_header = any(
                word in first_line.lower()
                for word in ['title', 'year', 'name', 'film', 'movie']
            )
            if is_header:
                try:
                    dialect = csv.Sniffer().sniff(first_line)
                except csv.Error:
                    dialect = csv.excel
                reader = csv.DictReader(f, dialect=dialect)
                for row_num, row in enumerate(reader, start=2):
                    try:
                        title = None
                        year = None
                        title_columns = ['title', 'Title', 'Name', 'Film', 'Movie', 'name']
                        for col in title_columns:
                            if col in row and row[col] and row[col].strip():
                                title = row[col].strip()
                                break
                        year_columns = ['year', 'Year', 'Release Year', 'ReleaseYear', 'release_year']
                        for col in year_columns:
                            if col in row and row[col] and str(row[col]).strip():
                                year = str(row[col]).strip()
                                break
                        if title:
                            watchlist.append((title.lower(), year or ""))
                            logging.debug(f"Hinzugefügt: {title} ({year})")
                        else:
                            logging.warning(f"Zeile {row_num}: Kein Titel gefunden in {row}")
                    except Exception as e:
                        logging.error(f"Fehler in Zeile {row_num}: {e}")
                        continue
            else:
                reader = csv.reader(f)
                for row_num, row in enumerate(reader, start=1):
                    try:
                        if len(row) >= 3:
                            title = row[1].strip()
                            year = row[2].strip()
                            if title:
                                watchlist.append((title.lower(), year or ""))
                                logging.debug(f"Hinzugefügt: {title} ({year})")
                            else:
                                logging.warning(f"Zeile {row_num}: Kein Titel in {row}")
                        else:
                            logging.warning(f"Zeile {row_num}: Zu wenige Spalten in {row}")
                    except Exception as e:
                        logging.error(f"Fehler in Zeile {row_num}: {e}")
                        continue

    except Exception as e:
        logging.error(f"Fehler beim Laden der CSV-Watchlist: {e}")
        return []

    return watchlist

def load_watchlist_from_drive(_ignored=None):
    """Lädt die Watchlist direkt aus deinem Google Sheet."""
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            "client_secret.json", scope
        )
        client = gspread.authorize(creds)

        sheet = client.open_by_key("").sheet1

        records = sheet.get_all_records()

        watchlist = []
        for row in records:
            title = str(row.get("Name") or "").strip()
            year = str(row.get("Year") or "").strip()
            if title:
                watchlist.append((title.lower(), year))

        return watchlist

    except Exception as e:
        logging.error(f"Fehler beim Laden aus Google Sheet: {e}")
        return []



def get_dynamic_feed_url():
    """Ermittelt die RSS-Feed-URL dynamisch."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36"
    }
    url = "https://www.hdencode.org"

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        link = soup.find("link", {"type": "application/rss+xml"})
        if link and link.get("href"):
            feed_url = link["href"]
            logging.info(f"Feed-URL gefunden: {feed_url}")
            return feed_url
    except Exception as e:
        logging.warning(f"Feed-URL konnte nicht ermittelt werden: {e}")

    fallback = "https://hdencode.org/feed/?sfw=pass1751722421"
    logging.info(f"Verwende Fallback-Feed: {fallback}")
    return fallback


def load_seen_links(path=SEEN_LINKS_FILE):
    """Lädt bereits gesehene Links."""
    if not os.path.exists(path):
        return set()

    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except Exception as e:
        logging.error(f"Fehler beim Laden der seen_links: {e}")
        return set()


def save_seen_link(link, path=SEEN_LINKS_FILE):
    """Speichert einen gesehenen Link."""
    try:
        with seen_links_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(link + "\n")
    except Exception as e:
        logging.error(f"Fehler beim Speichern des Links: {e}")


def send_telegram_message(message):
    """Sendet eine Telegram-Nachricht."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logging.info("Telegram-Nachricht gesendet")
        else:
            logging.warning(
                f"Telegram API Fehler: {response.status_code} - "
                f"{response.text}"
            )
    except Exception as e:
        logging.error(f"Telegram-Sendefehler: {e}")


def handle_search(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("🔍 Bitte gib einen Suchbegriff an. Beispiel: /suche inception")
        return

    query = " ".join(context.args).lower()
    feed_url = get_dynamic_feed_url()
    posts = get_rss_posts(feed_url)

    matches = []
    for title, link in posts:
        if query in title.lower():
            matches.append(f"🎬 <b>{title}</b>\n🔗 <a href='{link}'>Download</a>")

    if matches:
        for msg in matches[:5]:
            update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)
        if len(matches) > 5:
            update.message.reply_text(f"... {len(matches)-5} weitere Treffer gefunden.")
    else:
        update.message.reply_text("❌ Kein Treffer gefunden")


def search_hdencode_pages(query, max_pages=10):
    """Durchsucht mehrere Seiten der HDEncode-Webseite nach Titeln, die den Suchbegriff enthalten."""
    base_url = "https://www.hdencode.org/page/{}/"
    headers = {"User-Agent": "Mozilla/5.0"}
    query = query.lower()
    results = []

    for page_num in range(1, max_pages + 1):
        url = base_url.format(page_num)
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            entries = soup.find_all("h2", class_="title")

            for entry in entries:
                a_tag = entry.find("a")
                if a_tag and query in a_tag.text.lower():
                    title = a_tag.text.strip()
                    link = a_tag["href"]
                    results.append((title, link))
        except Exception as e:
            logging.warning(f"Fehler bei Seite {page_num}: {e}")
            continue

    return results


def handle_search_all(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("🔍 Bitte gib einen Suchbegriff an. Beispiel: /suchealle dune")
        return

    query = " ".join(context.args).strip()
    update.message.reply_text(f"🔎 Suche nach '{query}' im gesamten HDEncode-Katalog...")

    results = search_hdencode_pages(query, max_pages=25)

    if results:
        for title, link in results[:5]:
            update.message.reply_text(
                f"🎬 <b>{title}</b>\n🔗 <a href='{link}'>Download</a>",
                parse_mode='HTML',
                disable_web_page_preview=True
            )
        if len(results) > 5:
            update.message.reply_text(f"... {len(results)-5} weitere Treffer gefunden")
    else:
        update.message.reply_text("❌ Kein Treffer gefunden")

def handle_status(update: Update, context: CallbackContext):
    status = "🟢 Läuft" if running.is_set() else "🔴 Gestoppt"
    last_check = (
        last_check_time.strftime('%Y-%m-%d %H:%M:%S') if last_check_time else "Nie"
    )
    update.message.reply_text(f"{status}\n🕒 Letzter Check: {last_check}")

def start_telegram_bot():
    """Startet den Telegram-Bot mit Befehlshandlern."""
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    updater.start_polling(drop_pending_updates=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("suche", handle_search))
    dp.add_handler(CommandHandler("status", handle_status))
    dp.add_handler(CommandHandler("suchealle", handle_search_all))
    logging.info("Telegram-Bot läuft und wartet auf Kommandos.")


def get_rss_posts(feed_url):
    """Ruft RSS-Feed-Einträge ab."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36"
    }

    try:
        response = requests.get(feed_url, headers=headers, timeout=15)
        response.raise_for_status()

        feed = feedparser.parse(response.text)

        if hasattr(feed, 'bozo') and feed.bozo:
            logging.warning(
                f"RSS-Feed hat Parsing-Probleme: {feed.bozo_exception}"
            )

        posts = []
        for entry in feed.entries:
            if hasattr(entry, 'title') and hasattr(entry, 'link'):
                posts.append((entry.title.strip(), entry.link.strip()))

        return posts

    except Exception as e:
        logging.error(f"RSS-Feed Fehler: {e}")
        return []


def find_matches(watchlist, feed_posts, seen_links):
    matches = []
    found_films = set()  # Tracking für bereits gefundene Filme

    logging.info(
        f"Starte Matching mit {len(watchlist)} Watchlist-Einträgen "
        f"und {len(feed_posts)} Feed-Posts"
    )

    for title, link in feed_posts:
        if link in seen_links:
            continue

        title_clean = title.lower()
        logging.debug(f"Prüfe Feed-Titel: {title_clean}")

        for film_name, film_year in watchlist:
            # Erstelle einen eindeutigen Schlüssel für den Film
            film_key = f"{film_name.lower()}_{film_year}"

            # Überspringe wenn dieser Film bereits gefunden wurde
            if film_key in found_films:
                continue

            # Verbesserte Titel-Übereinstimmung
            if is_title_match(film_name, film_year, title_clean):
                match = {
                    'film_name': film_name,
                    'film_year': film_year,
                    'feed_title': title,
                    'link': link
                }
                matches.append(match)
                found_films.add(film_key)  # Markiere als gefunden
                logging.info(
                    f"✅ Match: {film_name} ({film_year}) → {title}"
                )
                break  # Stoppe weitere Suche für diesen Feed-Titel

    logging.info(f"Matching abgeschlossen: {len(matches)} Matches gefunden")
    return matches


def run_watcher():
    """Hauptfunktion des Watchers."""
    global last_check_time

    try:
        # Initialisierung
        seen_links = load_seen_links()
        watchlist = load_watchlist_from_drive()

        if not watchlist:
            send_telegram_message("⚠️ Konnte Watchlist nicht von Google Drive laden. Fallback auf lokale csv-Datei")
            watchlist = load_watchlist_from_csv()

        if not watchlist:
            logging.warning("Keine Watchlist gefunden. Prüfe Google Drive oder file_ID")
            send_telegram_message("Fehler beim Laden der Watchlist auf Google Drive")
            return
        else:
            send_telegram_message(f"✅ Watchlist erfolgreich von Google Drive geladen ({len(watchlist)} Filme)")

        print(f"🎥 Watchlist geladen: {len(watchlist)} Filme")
        for film, year in watchlist[:5]:  # Zeige erste 5
            print(f"  → {film} ({year})")
        if len(watchlist) > 5:
            print(f"  ... und {len(watchlist) - 5} weitere")

        feed_url = get_dynamic_feed_url()
        send_telegram_message(
            "🚀 HDEncode Watcher gestartet"
        )

        # Hauptschleife
        while running.is_set():
            try:
                last_check_time = datetime.now()
                logging.info(
                    f"Starte Check um {last_check_time.strftime('%H:%M:%S')}"
                )

                # RSS-Feed abrufen
                posts = get_rss_posts(feed_url)
                if not posts:
                    logging.warning("Keine RSS-Posts erhalten")
                    time.sleep(CHECK_INTERVAL)
                    continue

                logging.info(f"📦 {len(posts)} Feed-Einträge erhalten")

                # Matches suchen
                matches = find_matches(watchlist, posts, seen_links)

                # Matches verarbeiten
                for match in matches:
                    message = (
                        f"🎬 <b>{match['feed_title']}</b>\n"
                        f"📅 Match: {match['film_name']} "
                        f"({match['film_year']})\n"
                        f"🔗 <a href='{match['link']}'>Download</a>"
                    )

                    send_telegram_message(message)
                    seen_links.add(match['link'])
                    save_seen_link(match['link'])

                if matches:
                    logging.info(f"✅ {len(matches)} neue Matches gefunden")

            except Exception as e:
                logging.error(f"Fehler im Watcher-Loop: {e}")

            # Warten mit Unterbrechbarkeit
            for _ in range(CHECK_INTERVAL):
                if not running.is_set():
                    break
                time.sleep(1)

    except Exception as e:
        logging.error(f"Kritischer Fehler im Watcher: {e}")
        send_telegram_message(f"❌ Watcher-Fehler: {e}")


def handle_exit(signum, frame):
    """Signal-Handler für sauberes Beenden."""
    logging.info("Beende Watcher...")
    running.clear()
    sys.exit(0)


def main():
    """Startet den Watcher im Hintergrund (ohne Tray)."""
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    telegram_thread = threading.Thread(target=start_telegram_bot, daemon=True)
    telegram_thread.start()

    watcher_thread = threading.Thread(target=run_watcher, daemon=False)
    watcher_thread.start()

    try:
        while watcher_thread.is_alive():
            watcher_thread.join(timeout=1)
    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt empfangen, Watcher wird beendet.")
        running.clear()
        watcher_thread.join()


if __name__ == "__main__":
    print("🎬 Starte HDEncode Watcher (headless mode)")
    print(f"📁 Arbeitsverzeichnis: {SCRIPT_DIR}")
    print(f"📋 Watchlist: {WATCHLIST_CSV}")
    print(f"📝 Log-Datei: {LOG_FILE}")
    main()
