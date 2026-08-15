#!/bin/bash

# 🤖 AUTO ALERT BOT - JEDNODUCHÁ INSTALACE
# Běží na Ubuntu/Debian VPS

set -e

echo "================================================"
echo "  INSTALACE AUTO ALERT BOTA"
echo "================================================"
echo ""

# Kontrola root
if [[ $EUID -ne 0 ]]; then
   echo "❌ Musíš být root: sudo bash bazos_bot_install.sh"
   exit 1
fi

# Varianty
BOT_DIR="/opt/bazos_bot"
BOT_USER="bazos"

echo "📦 Aktualizuji balíčky..."
apt-get update -qq
apt-get upgrade -y -qq

echo "🔍 Zjišťuji dostupnou verzi Pythonu..."
PYTHON_BIN=""
for ver in python3.12 python3.11 python3.10 python3.9 python3.8 python3; do
    if apt-cache show "$ver" &>/dev/null || command -v "$ver" &>/dev/null; then
        PYTHON_BIN="$ver"
        break
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    echo "❌ Nenalezen žádný Python3. Instaluji python3 základní balíček..."
    PYTHON_BIN="python3"
fi

echo "✅ Použiji: $PYTHON_BIN"

echo "📦 Instaluji Python a PostgreSQL..."
apt-get install -y -qq \
    "$PYTHON_BIN" \
    "${PYTHON_BIN}-venv" \
    postgresql \
    postgresql-contrib \
    git \
    curl \
    2>&1 | grep -v "^$" || true

# Pokud venv balíček neexistuje pod tímto jménem, zkus obecný
if ! dpkg -l | grep -q "${PYTHON_BIN}-venv"; then
    apt-get install -y -qq python3-venv 2>/dev/null || true
fi

# Ověření, že python je funkční
if ! command -v "$PYTHON_BIN" &>/dev/null; then
    echo "❌ Python se nepodařilo nainstalovat. Zkus ručně: apt-get install python3 python3-venv"
    exit 1
fi

echo "✅ Python dostupný: $($PYTHON_BIN --version)"

echo "👤 Vytvářím uživatele..."
if ! id "$BOT_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$BOT_USER"
    echo "✅ Uživatel $BOT_USER vytvořen"
else
    echo "✅ Uživatel $BOT_USER již existuje"
fi

echo "📁 Vytvářím adresář..."
mkdir -p "$BOT_DIR"
chown -R "$BOT_USER:$BOT_USER" "$BOT_DIR"

echo "🐍 Vytvářím virtual environment..."
sudo -u "$BOT_USER" "$PYTHON_BIN" -m venv "$BOT_DIR/venv"

echo "📦 Instaluji Python balíčky..."
sudo -u "$BOT_USER" "$BOT_DIR/venv/bin/pip" install -q --upgrade pip

# Vytvořím soubor se všemi balíčky
cat > "$BOT_DIR/requirements.txt" << 'EOF'
python-telegram-bot==20.3
requests==2.31.0
beautifulsoup4==4.12.2
psycopg2-binary==2.9.9
python-dotenv==1.0.0
APScheduler==3.10.4
sqlalchemy==2.0.23
lxml==4.9.3
EOF

sudo -u "$BOT_USER" "$BOT_DIR/venv/bin/pip" install -q -r "$BOT_DIR/requirements.txt"

echo "✅ Python balíčky instalovány"

echo "🗄️  Kontroluji PostgreSQL..."
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Vytvoř databázi
if ! sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw bazos_bot_db; then
    echo "Vytvářím databázi..."
    sudo -u postgres createdb bazos_bot_db
    sudo -u postgres createuser -s bazos_bot_user 2>/dev/null || true
    echo "✅ Databáze vytvořena"
else
    echo "✅ Databáze již existuje"
fi

echo "📋 Vytvářím systemd service..."

# Vytvoř service soubor
cat > /etc/systemd/system/bazos_bot.service << 'EOF'
[Unit]
Description=Auto Alert Bot for Bazos
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=bazos
WorkingDirectory=/opt/bazos_bot
Environment="PATH=/opt/bazos_bot/venv/bin"
EnvironmentFile=/opt/bazos_bot/.env
ExecStart=/opt/bazos_bot/venv/bin/python /opt/bazos_bot/bazos_bot_complete.py

Restart=always
RestartSec=30

StandardOutput=journal
StandardError=journal
SyslogIdentifier=bazos_bot

NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
echo "✅ Service registrován"

echo ""
echo "================================================"
echo "  ✅ INSTALACE HOTOVA"
echo "================================================"
echo ""
echo "DALŠÍ KROKY:"
echo ""
echo "1️⃣  Nahraj soubor 'bazos_bot_complete.py' do $BOT_DIR/"
echo "    (pomocí SCP, SFTP nebo nahráním přes web)"
echo ""
echo "2️⃣  Vytvoř .env soubor:"
echo "    nano $BOT_DIR/.env"
echo ""
echo "3️⃣  Vyplň tyto hodnoty:"
echo "    TELEGRAM_BOT_TOKEN=tvuj_token"
echo "    TELEGRAM_ADMIN_ID=123456789"
echo "    TELEGRAM_GROUP_ID=-1001234567890"
echo "    DATABASE_URL=sqlite:///bazos_bot.db"
echo "    SCRAPER_INTERVAL_MINUTES=5"
echo "    MAX_PAGES_TO_SCRAPE=3"
echo ""
echo "4️⃣  Nastav správné oprávnění:"
echo "    sudo chown bazos:bazos $BOT_DIR/bazos_bot_complete.py"
echo "    sudo chmod 755 $BOT_DIR/bazos_bot_complete.py"
echo ""
echo "5️⃣  Spusť bot:"
echo "    sudo systemctl start bazos_bot"
echo ""
echo "6️⃣  Ověř, že běží:"
echo "    sudo systemctl status bazos_bot"
echo ""
echo "7️⃣  Zobrazuj logy:"
echo "    sudo journalctl -u bazos_bot -f"
echo ""
echo "❓ Jak získat hodnoty:"
echo "  • TELEGRAM_BOT_TOKEN - napiš /newbot na @BotFather"
echo "  • TELEGRAM_ADMIN_ID - napiš /start na @userinfobot"
echo "  • TELEGRAM_GROUP_ID - vytvoř supergroup, přidej bota, dostaneš ID"
echo ""
