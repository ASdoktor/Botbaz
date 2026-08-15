# 🚗 AUTO ALERT BOT - QUICK START

Telegram bot pro automatický monitoring inzerátů na Bazoši.

## 📋 Máš 3 soubory:

1. **`bazos_bot_complete.py`** - Hlavní aplikace (vše v jednom)
2. **`bazos_bot_install.sh`** - Instalační skript pro VPS
3. **`.env.example`** - Příklad konfigurace

---

## 🚀 INSTALACE NA VPS (5 minut)

### Krok 1: Připoj se na VPS

```bash
ssh root@tvuj-vps.com
```

### Krok 2: Stáhni instalační skript

Pomocí `curl`:
```bash
cd /tmp
curl -O https://tvuj-web.cz/bazos_bot_install.sh
sudo bash bazos_bot_install.sh
```

Nebo vytvoř soubor ručně:
```bash
nano bazos_bot_install.sh
# Zkopíruj obsah z bazos_bot_install.sh a vlož sem
# Ctrl+X, Y, Enter
```

### Krok 3: Spusť instalaci

```bash
sudo bash /tmp/bazos_bot_install.sh
```

Instalace trvá 2-3 minuty a automaticky:
- ✅ Nainstaluje Python 3.11
- ✅ Nainstaluje PostgreSQL
- ✅ Vytvoří uživatele `bazos`
- ✅ Vytvoří `virtual environment`
- ✅ Zaregistruje systemd service

### Krok 4: Nahraj soubor `bazos_bot_complete.py`

**Z tvého PC** (v jiném terminálu):
```bash
scp bazos_bot_complete.py root@tvuj-vps.com:/opt/bazos_bot/
```

**Nebo ručně na VPS:**
```bash
nano /opt/bazos_bot/bazos_bot_complete.py
# Zkopíruj obsah souboru a vlož sem
# Ctrl+X, Y, Enter
```

### Krok 5: Vytvoř `.env` soubor

```bash
nano /opt/bazos_bot/.env
```

Zkopíruj a vyplň:
```env
TELEGRAM_BOT_TOKEN=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabc_XYZ
TELEGRAM_ADMIN_ID=123456789
TELEGRAM_GROUP_ID=-1001234567890
DATABASE_URL=sqlite:///bazos_bot.db
SCRAPER_INTERVAL_MINUTES=5
MAX_PAGES_TO_SCRAPE=3
```

**Uložit:** Ctrl+X, potom Y, Enter

### Krok 6: Nastav oprávnění

```bash
sudo chown bazos:bazos /opt/bazos_bot/bazos_bot_complete.py
sudo chmod 755 /opt/bazos_bot/bazos_bot_complete.py
```

### Krok 7: Spusť bot

```bash
sudo systemctl start bazos_bot
sudo systemctl enable bazos_bot
```

### Krok 8: Ověř, že běží

```bash
sudo systemctl status bazos_bot
```

Měl by ukázat `active (running)`.

Zobrazuj logy:
```bash
sudo journalctl -u bazos_bot -f
```

---

## 📱 TESTOVÁNÍ V TELEGRAMU

1. Otevři Telegram skupinu `Auto Alerty` (kterou si vytvořil)
2. Napiš botovi `/start`
3. Bot by měl odpovědět s menu
4. Klikni na "➕ Nový alert"
5. Vyber značku (BMW, Škoda...)
6. Vyplň parametry (cena, rok...)
7. Bot vytvoří vlákno a začne posílat inzeráty

---

## 🔑 ZÍSKÁNÍ TELEGRAM ÚDAJŮ

### 1. TELEGRAM_BOT_TOKEN

```
V Telegramu:
  1. Hledej: @BotFather
  2. Napiš: /newbot
  3. Vyplň jméno (např. "AutoAlertBot")
  4. Vyplň username (např. "auto_alert_bot_xyz")
  5. Dostaneš TOKEN
```

### 2. TELEGRAM_ADMIN_ID

```
V Telegramu:
  1. Hledej: @userinfobot
  2. Napiš: /start
  3. Zobrazí ti "Your user id is: 123456789"
  4. Zkopíruj číslo
```

### 3. TELEGRAM_GROUP_ID

```
V Telegramu:
  1. Vytvoř novou supergroup (Nastavení → Nový chat → Nový supergroup)
  2. Jméno: "Auto Alerty"
  3. Přidej bota jako člena
  4. Přidělej mu roli "Správce"
  5. Nap bot v DM ID skupiny nebo:
  6. V prohlížeči navštiv:
     https://t.me/joinchat/XXXXXXXXXXXXX
  7. Číslo NA KONCI odkazu je Group ID
     Přidej znaménko "-100" na začátek
     Např: -1001234567890
```

---

## ⚙️ SPRÁVA BOTA

### Status bota
```bash
sudo systemctl status bazos_bot
```

### Restart bota
```bash
sudo systemctl restart bazos_bot
```

### Stop bota
```bash
sudo systemctl stop bazos_bot
```

### Start bota
```bash
sudo systemctl start bazos_bot
```

### Logy (poslední 50 řádků)
```bash
sudo journalctl -u bazos_bot -n 50
```

### Logy live (sledování)
```bash
sudo journalctl -u bazos_bot -f
```

### Logy s chybami
```bash
sudo journalctl -u bazos_bot | grep ERROR
```

---

## 🔧 ŘEŠENÍ PROBLÉMŮ

### Bot se nespustí

```bash
sudo journalctl -u bazos_bot -n 100
```

Hledej slovo `ERROR`.

**Běžné chyby:**

1. **`TELEGRAM_BOT_TOKEN is not set`**
   - Vyfyplnil si `.env`?
   - Zkontroluj: `cat /opt/bazos_bot/.env`

2. **`TELEGRAM_GROUP_ID must be set`**
   - Vygeneroval si Group ID?
   - Je v `.env` negativní? (`-100...`)

3. **`ModuleNotFoundError`**
   - Python balíčky se nenainstalovali?
   - Oprav: `sudo -u bazos /opt/bazos_bot/venv/bin/pip install -r /opt/bazos_bot/requirements.txt`

### Bot neposílá inzeráty

- Zkontroluj, že skrz Internet funguje
- Zkontroluj bot se v tém "Online" v Telegramu
- Zkontroluj logs: `sudo journalctl -u bazos_bot -f`

### Telegram odsekl bota

```bash
sudo systemctl restart bazos_bot
```

---

## 🗑️ ZÁLOHA A SMAZÁNÍ

### Záloha databáze
```bash
cp /opt/bazos_bot/bazos_bot.db /backup/bazos_bot_backup.db
```

### Smazání všeho (pokud chceš začít znovu)
```bash
sudo systemctl stop bazos_bot
sudo rm -rf /opt/bazos_bot
sudo userdel bazos
sudo dropdb bazos_bot_db
```

---

## 📊 STATISTIKA

```bash
# Počet inzerátů v databázi
sudo -u bazos sqlite3 /opt/bazos_bot/bazos_bot.db "SELECT COUNT(*) FROM listings;"

# Počet alertů
sudo -u bazos sqlite3 /opt/bazos_bot/bazos_bot.db "SELECT COUNT(*) FROM alerts;"

# Počet odeslaných inzerátů
sudo -u bazos sqlite3 /opt/bazos_bot/bazos_bot.db "SELECT COUNT(*) FROM alert_matches WHERE sent_to_telegram = 1;"
```

---

## 💡 TIPY

- **Bot běží 24/7** - Systemd automaticky restartuje bot, pokud padne
- **Databáze je lokální** - SQLite se ukládá v `/opt/bazos_bot/bazos_bot.db`
- **Logy se ukládají** - V systemd journal (lze číst pomocí `journalctl`)
- **Auto-start** - Bot se spustí sám při restartu VPS

---

## 🆘 NÁPOVĚDA

Máš problém?

1. **Zkontroluj logy:**
   ```bash
   sudo journalctl -u bazos_bot -f
   ```

2. **Zkontroluj status:**
   ```bash
   sudo systemctl status bazos_bot
   ```

3. **Restartuj bot:**
   ```bash
   sudo systemctl restart bazos_bot
   ```

4. **Zkontroluj `.env`:**
   ```bash
   cat /opt/bazos_bot/.env
   ```

---

**Vše připraveno!** 🎉 Bot teď monitoruje Bazoš a posílá ti nové inzeráty do Telegramu.
