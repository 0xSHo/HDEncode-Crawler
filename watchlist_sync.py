import time
import re
from datetime import datetime
from playwright.sync_api import sync_playwright  # type: ignore
import gspread  # type: ignore
from oauth2client.service_account import (  # type: ignore
    ServiceAccountCredentials,  # type: ignore
)

LETTERBOXD_USER = ""
GOOGLE_SHEET_ID = ""
SHEET_NAME = ""
CREDENTIALS_FILE = ""


def connect_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        CREDENTIALS_FILE, scope
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME)
    return sheet


def scrape_watchlist():
    print("Scraping Watchlist mit Playwright...")
    films = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        i = 1
        while True:
            print(f"Lade Seite {i}...")
            url = (
                f"https://letterboxd.com/{LETTERBOXD_USER}/watchlist/page/{i}/"
            )
            page.goto(url, timeout=60000)

            previous_height = 0
            while True:
                current_height = page.evaluate("document.body.scrollHeight")
                if current_height == previous_height:
                    break
                previous_height = current_height
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1.0)

            elements = page.query_selector_all(".frame-title")
            if not elements:
                print("⚠️ Keine weiteren Filme gefunden – Abbruch.")
                break

            for el in elements:
                raw = el.inner_text().strip()
                match = re.search(r'\((\d{4})\)$', raw)
                year = match.group(1) if match else ""
                title = re.sub(r'\s*\(\d{4}\)$', '', raw).strip()

                films.append((title, year, ""))
                print(f"→ Gefunden: {title} ({year})")

            i += 1
            time.sleep(1.5)

        browser.close()

    print(f"✓ Insgesamt {len(films)} Filme gesammelt.")
    return films


def sync_sheet(watchlist):
    print("Synchronisiere mit Google Sheet...")
    sheet = connect_sheet()

    # Erst alle Inhalte ab Zeile 2 löschen
    sheet.batch_clear(['A2:D'])

    # Spaltenüberschriften in Zeile 1 setzen
    sheet.update('A1:D1', [['Hinzugefügt', 'Name', 'Year']])

    # Aktuelles Datum (nur Datum, nicht Uhrzeit)
    today = datetime.now().strftime("%Y-%m-%d")

    # Zeilen vorbereiten
    rows = [[today, title, year, uri] for (title, year, uri) in watchlist]

    if rows:
        # Alle Filmdaten auf einmal schreiben (ab Zeile 2)
        sheet.update(f'A2:D{len(rows)+1}', rows)
        print(f"✓ {len(rows)} Filme synchronisiert.")
    else:
        print("Keine Filme zum Synchronisieren gefunden.")


if __name__ == "__main__":
    watchlist = scrape_watchlist()
    sync_sheet(watchlist)
