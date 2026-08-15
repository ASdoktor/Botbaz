#!/usr/bin/env python3
"""
🤖 TELEGRAM AUTO ALERT BOT - ALL IN ONE
Monitoring automobilových inzerátů z Bazoše
Jeden soubor obsahuje vše - databázi, scraper, matcher, telegram bot
"""

import os
import sys
import logging
import json
import re
import requests
from datetime import datetime, timedelta
from threading import Thread
from dotenv import load_dotenv
from bs4 import BeautifulSoup

# SQLAlchemy
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Scheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# ============================================================================
# KONFIGURACE
# ============================================================================

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ENV vars
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID", 0))
TELEGRAM_GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", 0))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bazos_bot.db")  # SQLite jako default
SCRAPER_INTERVAL = int(os.getenv("SCRAPER_INTERVAL_MINUTES", 5))
MAX_PAGES = int(os.getenv("MAX_PAGES_TO_SCRAPE", 3))

# ============================================================================
# DATABÁZE - MODELY
# ============================================================================

Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, index=True)
    username = Column(String(255), nullable=True)
    registered_at = Column(DateTime, default=datetime.utcnow)
    is_admin = Column(Boolean, default=False)
    
    alerts = relationship("Alert", back_populates="user", cascade="all, delete-orphan")


class Alert(Base):
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String(255))
    filters = Column(JSON)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    telegram_topic_id = Column(Integer, nullable=True, index=True)
    telegram_chat_id = Column(Integer, nullable=True)
    
    user = relationship("User", back_populates="alerts")
    matches = relationship("AlertMatch", back_populates="alert", cascade="all, delete-orphan")


class Listing(Base):
    __tablename__ = "listings"
    
    id = Column(Integer, primary_key=True)
    bazos_id = Column(String(50), unique=True, index=True)
    url = Column(String(500), unique=True)
    title = Column(String(500))
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=True)
    params = Column(JSON)
    image_url = Column(String(500), nullable=True)
    published_at = Column(DateTime, nullable=True)
    found_at = Column(DateTime, default=datetime.utcnow, index=True)
    source = Column(String(50), default="bazos")
    is_processed = Column(Boolean, default=False, index=True)
    
    matches = relationship("AlertMatch", back_populates="listing", cascade="all, delete-orphan")


class AlertMatch(Base):
    __tablename__ = "alert_matches"
    
    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), index=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), index=True)
    matched_at = Column(DateTime, default=datetime.utcnow, index=True)
    sent_to_telegram = Column(Boolean, default=False)
    sent_at = Column(DateTime, nullable=True)
    
    alert = relationship("Alert", back_populates="matches")
    listing = relationship("Listing", back_populates="matches")


class BotLog(Base):
    __tablename__ = "bot_logs"
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    level = Column(String(20))
    message = Column(Text)
    source = Column(String(50))


def init_db():
    """Inicializace databáze"""
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Databáze inicializována")


def log_to_db(message: str, level: str = "INFO", source: str = "bot"):
    """Log do databáze"""
    db = SessionLocal()
    try:
        log_entry = BotLog(timestamp=datetime.utcnow(), level=level, message=message, source=source)
        db.add(log_entry)
        db.commit()
    except:
        pass
    finally:
        db.close()


# ============================================================================
# SCRAPER
# ============================================================================

BASE_URL = "https://auto.bazos.cz"


def extract_listing_id_from_url(url: str) -> str:
    """Extrahuje ID z URL"""
    match = re.search(r'/(\d+)/?$', url)
    return match.group(1) if match else None


def parse_listing(item) -> dict:
    """Parsuje jeden inzerát"""
    try:
        link_elem = item.find('a', class_='nadpis')
        if not link_elem:
            return None
        
        title = link_elem.text.strip()
        url = link_elem.get('href', '')
        if not url.startswith('http'):
            url = BASE_URL + url
        
        listing_id = extract_listing_id_from_url(url)
        if not listing_id:
            return None
        
        # Cena
        price = None
        price_elem = item.find('span', class_='cena')
        if price_elem:
            price_text = re.sub(r'[^\d]', '', price_elem.text.strip())
            if price_text:
                price = float(price_text)
        
        # Popis
        description = ""
        desc_elem = item.find('span', class_='popis')
        if desc_elem:
            description = desc_elem.text.strip()
        
        # Fotka
        image_url = None
        img_elem = item.find('img')
        if img_elem:
            image_url = img_elem.get('src', '')
        
        # Parametry
        text = f"{title} {description}".lower()
        params = {}
        
        brands = ['bmw', 'škoda', 'mercedes', 'audi', 'volkswagen', 'ford', 'opel', 'toyota']
        for brand in brands:
            if brand in text:
                params['brand'] = brand.capitalize()
                break
        
        if 'nafta' in text or 'diesel' in text:
            params['fuel'] = 'nafta'
        elif 'benzín' in text:
            params['fuel'] = 'benzín'
        elif 'hybrid' in text:
            params['fuel'] = 'hybrid'
        
        if 'automat' in text:
            params['transmission'] = 'automat'
        elif 'manuál' in text:
            params['transmission'] = 'manuál'
        
        year_match = re.search(r'\b(19|20)\d{2}\b', title)
        if year_match:
            params['year'] = int(year_match.group(0))
        
        return {
            'bazos_id': listing_id,
            'url': url,
            'title': title,
            'description': description,
            'price': price,
            'params': params,
            'image_url': image_url,
            'published_at': datetime.utcnow(),
            'source': 'bazos'
        }
    except Exception as e:
        logger.error(f"Chyba při parsování: {e}")
        return None


def scrape_bazos(page: int = 1) -> list:
    """Stahuje ze Bazoše"""
    try:
        url = f"{BASE_URL}?page={page}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        listings = []
        
        for item in soup.find_all('div', class_='nabidka'):
            listing = parse_listing(item)
            if listing:
                listings.append(listing)
        
        logger.info(f"Staženo {len(listings)} inzerátů (strana {page})")
        return listings
    except Exception as e:
        logger.error(f"Chyba scraperu: {e}")
        return []


def save_listings(listings: list, db: Session) -> int:
    """Uloží nové inzeráty"""
    saved = 0
    
    for listing_data in listings:
        try:
            existing = db.query(Listing).filter(Listing.bazos_id == listing_data['bazos_id']).first()
            if existing:
                continue
            
            new_listing = Listing(
                bazos_id=listing_data['bazos_id'],
                url=listing_data['url'],
                title=listing_data['title'],
                description=listing_data['description'],
                price=listing_data['price'],
                params=listing_data['params'],
                image_url=listing_data['image_url'],
                published_at=listing_data['published_at'],
                source=listing_data['source'],
                is_processed=False
            )
            db.add(new_listing)
            db.commit()
            saved += 1
        except Exception as e:
            logger.error(f"Chyba při ukládání: {e}")
            db.rollback()
    
    return saved


def run_scraper():
    """Scraper job"""
    logger.info(">>> SPOUŠTĚNÍ SCRAPERU")
    db = SessionLocal()
    try:
        total_new = 0
        for page in range(1, MAX_PAGES + 1):
            listings = scrape_bazos(page)
            saved = save_listings(listings, db)
            total_new += saved
        
        logger.info(f"✅ Scraper hotov. Nalezeno {total_new} nových inzerátů")
        log_to_db(f"Scraper: {total_new} nových inzerátů", "INFO", "scraper")
        return total_new
    finally:
        db.close()


# ============================================================================
# MATCHER
# ============================================================================

def matches_filter(listing: Listing, alert: Alert) -> bool:
    """Kontroluje, zda inzerát odpovídá alertu"""
    if not listing.params:
        listing.params = {}
    
    filters = alert.filters or {}
    params = listing.params
    
    # Brand
    if 'brand' in filters and filters['brand']:
        if params.get('brand', '').lower() != filters['brand'].lower():
            return False
    
    # Model
    if 'model' in filters and filters['model']:
        if filters['model'].lower() not in listing.title.lower():
            return False
    
    # Cena
    if 'price_from' in filters and filters['price_from']:
        if not listing.price or listing.price < filters['price_from']:
            return False
    
    if 'price_to' in filters and filters['price_to']:
        if not listing.price or listing.price > filters['price_to']:
            return False
    
    # Rok
    if 'year_from' in filters and filters['year_from']:
        year = params.get('year')
        if not year or year < filters['year_from']:
            return False
    
    if 'year_to' in filters and filters['year_to']:
        year = params.get('year')
        if not year or year > filters['year_to']:
            return False
    
    # Palivo
    if 'fuel' in filters and filters['fuel']:
        if params.get('fuel', '').lower() != filters['fuel'].lower():
            return False
    
    # Převodovka
    if 'transmission' in filters and filters['transmission']:
        if params.get('transmission', '').lower() != filters['transmission'].lower():
            return False
    
    return True


def find_matching_alerts(listing: Listing, db: Session) -> list:
    """Najde alerty pro inzerát"""
    matching = []
    
    for alert in db.query(Alert).filter(Alert.is_active == True).all():
        if matches_filter(listing, alert):
            matching.append(alert)
    
    return matching


def run_matcher():
    """Matcher job"""
    logger.info(">>> SPOUŠTĚNÍ MATCHERU")
    db = SessionLocal()
    try:
        unprocessed = db.query(Listing).filter(Listing.is_processed == False).all()
        total_matches = 0
        
        for listing in unprocessed:
            try:
                alerts = find_matching_alerts(listing, db)
                
                for alert in alerts:
                    existing = db.query(AlertMatch).filter(
                        AlertMatch.listing_id == listing.id,
                        AlertMatch.alert_id == alert.id
                    ).first()
                    
                    if not existing:
                        match = AlertMatch(
                            alert_id=alert.id,
                            listing_id=listing.id,
                            matched_at=datetime.utcnow(),
                            sent_to_telegram=False
                        )
                        db.add(match)
                        db.commit()
                        total_matches += 1
                
                listing.is_processed = True
                db.commit()
            except Exception as e:
                logger.error(f"Chyba v matcheru: {e}")
                db.rollback()
        
        logger.info(f"✅ Matcher hotov. Vytvořeno {total_matches} matchů")
        log_to_db(f"Matcher: {total_matches} matchů", "INFO", "matcher")
        return total_matches
    finally:
        db.close()


# ============================================================================
# TELEGRAM BOT
# ============================================================================

# Conversation states
CREATE_ALERT_BRAND, CREATE_ALERT_MODEL, CREATE_ALERT_PRICE_FROM, CREATE_ALERT_PRICE_TO = range(4)


def format_listing(listing: Listing) -> str:
    """Formátuje inzerát pro Telegram"""
    text = f"🚗 <b>{listing.title}</b>\n\n"
    
    if listing.price:
        text += f"💰 Cena: <b>{listing.price:,.0f} Kč</b>\n"
    
    params = listing.params or {}
    
    if params.get('year'):
        text += f"📅 Rok: <b>{params['year']}</b>\n"
    
    if params.get('fuel'):
        text += f"⛽ Palivo: <b>{params['fuel']}</b>\n"
    
    if params.get('transmission'):
        text += f"⚙️ Převodovka: <b>{params['transmission']}</b>\n"
    
    text += f"\n<a href='{listing.url}'>🔗 ZOBRAZIT INZERÁT</a>"
    
    return text


async def send_listing_to_topic(context: ContextTypes.DEFAULT_TYPE, listing: Listing, alert: Alert):
    """Odešle inzerát do topicu"""
    try:
        if not alert.telegram_topic_id or not alert.telegram_chat_id:
            return False
        
        message_text = format_listing(listing)
        
        if listing.image_url:
            try:
                await context.bot.send_photo(
                    chat_id=alert.telegram_chat_id,
                    photo=listing.image_url,
                    caption=message_text,
                    parse_mode='HTML',
                    message_thread_id=alert.telegram_topic_id
                )
            except:
                await context.bot.send_message(
                    chat_id=alert.telegram_chat_id,
                    text=message_text,
                    parse_mode='HTML',
                    message_thread_id=alert.telegram_topic_id
                )
        else:
            await context.bot.send_message(
                chat_id=alert.telegram_chat_id,
                text=message_text,
                parse_mode='HTML',
                message_thread_id=alert.telegram_topic_id
            )
        
        return True
    except Exception as e:
        logger.error(f"Chyba při odesílání: {e}")
        return False


async def send_pending_listings(application: Application):
    """Odesílá pending inzeráty"""
    db = SessionLocal()
    try:
        pending = db.query(AlertMatch).filter(AlertMatch.sent_to_telegram == False).all()
        sent_count = 0
        
        for match in pending:
            try:
                alert = match.alert
                listing = match.listing
                
                if not alert.is_active or not alert.telegram_topic_id:
                    continue
                
                success = await send_listing_to_topic(application, listing, alert)
                
                if success:
                    match.sent_to_telegram = True
                    match.sent_at = datetime.utcnow()
                    db.commit()
                    sent_count += 1
            except Exception as e:
                logger.error(f"Chyba: {e}")
                db.rollback()
        
        if sent_count > 0:
            logger.info(f"✅ Odesláno {sent_count} inzerátů")
    finally:
        db.close()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /start"""
    db = SessionLocal()
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user:
            user = User(telegram_id=user_id, username=username)
            db.add(user)
            db.commit()
        
        keyboard = [
            [InlineKeyboardButton("➕ Nový alert", callback_data="create_alert")],
            [InlineKeyboardButton("⚙️ Správa alertů", callback_data="manage_alerts")],
            [InlineKeyboardButton("📊 Statistika", callback_data="stats")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "👋 Vítej v Auto Alert Botu!\n\n"
            "Sleduj nové inzeráty na Bazoši automaticky.",
            reply_markup=reply_markup
        )
    finally:
        db.close()


async def create_alert_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vytváření alertu - značka"""
    query = update.callback_query
    await query.answer()
    
    brands = ['BMW', 'Škoda', 'Mercedes', 'Audi', 'Volkswagen', 'Ford', 'Jiná']
    keyboard = [[InlineKeyboardButton(b, callback_data=f"brand_{b}")] for b in brands]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("Vyber značku:", reply_markup=reply_markup)
    return CREATE_ALERT_BRAND


async def select_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Výběr značky"""
    query = update.callback_query
    await query.answer()
    
    brand = query.data.replace("brand_", "")
    context.user_data['alert_brand'] = brand
    
    await query.edit_message_text(
        f"Značka: <b>{brand}</b>\n\n"
        f"Zadej model (nebo SKIP):",
        parse_mode='HTML'
    )
    
    return CREATE_ALERT_MODEL


async def receive_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Příjem modelu"""
    model = update.message.text.strip()
    
    if model.upper() != 'SKIP':
        context.user_data['alert_model'] = model
    
    await update.message.reply_text("Cena od (nebo SKIP):")
    return CREATE_ALERT_PRICE_FROM


async def receive_price_from(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Příjem ceny OD"""
    try:
        price = int(update.message.text.strip())
        context.user_data['alert_price_from'] = price
    except:
        await update.message.reply_text("Zadej číslo!")
        return CREATE_ALERT_PRICE_FROM
    
    await update.message.reply_text("Cena do (nebo SKIP):")
    return CREATE_ALERT_PRICE_TO


async def receive_price_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Příjem ceny DO a uložení"""
    try:
        price = int(update.message.text.strip())
        context.user_data['alert_price_to'] = price
    except:
        pass
    
    # Uložení alertu
    db = SessionLocal()
    try:
        user_id = update.effective_user.id
        user = db.query(User).filter(User.telegram_id == user_id).first()
        
        if not user:
            await update.message.reply_text("❌ Chyba")
            return
        
        alert_name = context.user_data.get('alert_brand', 'Alert')
        if context.user_data.get('alert_model'):
            alert_name += f" {context.user_data['alert_model']}"
        
        filters = {
            'brand': context.user_data.get('alert_brand'),
            'model': context.user_data.get('alert_model'),
            'price_from': context.user_data.get('alert_price_from'),
            'price_to': context.user_data.get('alert_price_to'),
        }
        
        # Vytvoř topic
        try:
            topic = await update.message.bot.create_forum_topic(
                chat_id=TELEGRAM_GROUP_ID,
                name=alert_name
            )
            topic_id = topic.message_thread_id
        except Exception as e:
            await update.message.reply_text(f"❌ Chyba při vytváření topicu:\n{str(e)}")
            logger.error(f"Topic error: {e}")
            return
        
        # Ulož alert
        alert = Alert(
            user_id=user.id,
            name=alert_name,
            filters=filters,
            is_active=True,
            telegram_topic_id=topic_id,
            telegram_chat_id=TELEGRAM_GROUP_ID
        )
        db.add(alert)
        db.commit()
        
        await update.message.reply_text(
            f"✅ <b>Alert vytvořen!</b>\n\n"
            f"<b>{alert_name}</b>\n"
            f"Cena: {filters.get('price_from', '—')} - {filters.get('price_to', '—')} Kč\n\n"
            f"Nové inzeráty ti budou posílány automaticky.",
            parse_mode='HTML'
        )
        
        log_to_db(f"Nový alert: {alert_name}", "INFO", "telegram")
    except Exception as e:
        logger.error(f"Alert save error: {e}")
        await update.message.reply_text(f"❌ Chyba: {str(e)}")
    finally:
        db.close()
        context.user_data.clear()


async def manage_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Správa alertů"""
    query = update.callback_query
    await query.answer()
    
    db = SessionLocal()
    try:
        user_id = update.effective_user.id
        user = db.query(User).filter(User.telegram_id == user_id).first()
        
        if not user:
            await query.edit_message_text("❌ Chyba")
            return
        
        alerts = db.query(Alert).filter(Alert.user_id == user.id).all()
        
        if not alerts:
            await query.edit_message_text("Nemáš žádné alerty.")
            return
        
        text = "Tvoje alerty:\n\n"
        for alert in alerts:
            status = "🟢" if alert.is_active else "🔴"
            text += f"{status} <b>{alert.name}</b>\n"
        
        await query.edit_message_text(text, parse_mode='HTML')
    finally:
        db.close()


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Statistika"""
    query = update.callback_query
    await query.answer()
    
    db = SessionLocal()
    try:
        users = db.query(User).count()
        alerts = db.query(Alert).count()
        listings = db.query(Listing).count()
        sent = db.query(AlertMatch).filter(AlertMatch.sent_to_telegram == True).count()
        
        await query.edit_message_text(
            f"📊 <b>Statistika</b>\n\n"
            f"👥 Uživatelé: {users}\n"
            f"🔔 Alerty: {alerts}\n"
            f"🚗 Inzeráty: {listings}\n"
            f"✅ Odesláno: {sent}",
            parse_mode='HTML'
        )
    finally:
        db.close()


def setup_handlers(application: Application):
    """Registruj handlery"""
    
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_alert_start, pattern="^create_alert$")],
        states={
            CREATE_ALERT_BRAND: [CallbackQueryHandler(select_brand, pattern="^brand_")],
            CREATE_ALERT_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_model)],
            CREATE_ALERT_PRICE_FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_price_from)],
            CREATE_ALERT_PRICE_TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_price_to)],
        },
        fallbacks=[]
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(manage_alerts, pattern="^manage_alerts$"))
    application.add_handler(CallbackQueryHandler(stats, pattern="^stats$"))


def run_telegram_bot():
    """Spusť Telegram bot"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    setup_handlers(application)
    
    # Job pro odesílání inzerátů
    application.job_queue.run_repeating(
        send_pending_listings,
        interval=60,
        first=10
    )
    
    logger.info("✅ Telegram bot spuštěn")
    application.run_polling()


# ============================================================================
# SCHEDULER
# ============================================================================

def start_scheduler():
    """Spusť scheduler"""
    logger.info("Spouštění scheduleru...")
    
    scheduler = BackgroundScheduler()
    
    scheduler.add_job(
        run_scraper,
        trigger=IntervalTrigger(minutes=SCRAPER_INTERVAL),
        id='scraper_job',
        replace_existing=True
    )
    
    scheduler.add_job(
        run_matcher,
        trigger=IntervalTrigger(minutes=1),
        id='matcher_job',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("✅ Scheduler běží")
    
    return scheduler


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Hlavní funkce"""
    
    print("\n" + "="*60)
    print("🤖 TELEGRAM AUTO ALERT BOT - ALL IN ONE")
    print("="*60 + "\n")
    
    # Kontrola ENV
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_ID or not TELEGRAM_GROUP_ID:
        print("❌ CHYBA: Vyplň .env soubor!")
        print("\nVytvořené soubory:")
        print("  1. Vytvoř nový .env soubor")
        print("  2. Vyplň tyto hodnoty:")
        print("     TELEGRAM_BOT_TOKEN=tvuj_token")
        print("     TELEGRAM_ADMIN_ID=tvoje_id")
        print("     TELEGRAM_GROUP_ID=id_skupiny")
        print("     DATABASE_URL=sqlite:///bazos_bot.db  (nebo postgresql://...)")
        sys.exit(1)
    
    print("✅ Konfigurace OK")
    
    # Init DB
    print("Inicializuji databázi...")
    init_db()
    
    # Scheduler v backgrounds vlákně
    print("Spouštění scheduleru...")
    scheduler = start_scheduler()
    
    # Telegram bot v hlavním vlákně
    print("="*60)
    print("✅ BOT JE PŘIPRAVEN")
    print("="*60 + "\n")
    
    try:
        run_telegram_bot()
    except KeyboardInterrupt:
        print("\n\nZastavuji bot...")
        scheduler.shutdown()
        print("Bot zastaven.")
    except Exception as e:
        print(f"\n❌ Kritická chyba: {e}")
        scheduler.shutdown()
        sys.exit(1)


if __name__ == "__main__":
    main()
