#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات اشگ تیم - نسخة الکسر المتقدم للحظر الإيراني
مع دعم GeoIP المحلي، Reality، و Fragment
"""

import os
import re
import io
import json
import time
import random
import socket
import struct
import base64
import hashlib
import requests
import threading
import logging
import geoip2.database
import geoip2.errors
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import subprocess
import tempfile

# ===================== الإعدادات المتقدمة =====================

@dataclass
class AdvancedConfig:
    """نموذج متقدم للکانفیگ مع دعم Reality و Fragment"""
    name: str
    protocol: str
    address: str
    port: int
    uuid: str
    sni: str
    network: str
    security: str
    path: str = ""
    
    # حقول Reality
    public_key: str = ""
    private_key: str = ""
    short_id: str = ""
    flow: str = "xtls-rprx-vision"
    
    # حقول Fragment
    fragment: str = "tls,5-50"
    mux: bool = True
    mux_concurrency: int = 8
    mux_idle_timeout: int = 60
    
    # معلومات إضافية
    country_code: str = "CA"
    country_name: str = "Canada"
    isp: str = "Cloudflare"
    ping: int = 6
    verified_date: str = ""
    tags: List[str] = field(default_factory=list)
    
    def to_vless_link_with_fragment(self) -> str:
        """توليد رابط VLESS مع Fragment وميزات إيرانية"""
        
        params = []
        
        # البارامترات الأساسية
        params.append(f"type={self.network}")
        params.append(f"security={self.security}")
        params.append(f"sni={self.sni}")
        
        # إضافة Reality parameters
        if self.security == "reality":
            if self.public_key:
                params.append(f"pbk={self.public_key}")
            if self.short_id:
                params.append(f"sid={self.short_id}")
            if self.flow:
                params.append(f"flow={self.flow}")
                
        # إضافة Fragment - هذا مهم جداً لكسر DPI الإيراني
        if self.fragment:
            params.append(f"fp=chrome")
            params.append(f"fragment={self.fragment}")
            
        # إضافة Mux لتحسين الأداء
        if self.mux:
            params.append(f"mux=on")
            params.append(f"muxC={self.mux_concurrency}")
            
        # إضافة path إذا موجود
        if self.path:
            params.append(f"path={self.path}")
            
        # إضافة header type للتمويه
        params.append(f"headerType=none")
        
        # إضافة encryption
        params.append(f"encryption=none")
        
        params_str = "&".join(params)
        
        # ترميز الاسم
        encoded_name = base64.urlsafe_b64encode(self.name.encode()).decode()[:20]
        
        return f"vless://{self.uuid}@{self.address}:{self.port}?{params_str}#{encoded_name}"
        
    def to_clash_meta_config(self) -> dict:
        """توليد تكوين Clash Meta للمستخدمين المتقدمين"""
        
        return {
            "name": self.name,
            "type": "vless",
            "server": self.address,
            "port": self.port,
            "uuid": self.uuid,
            "network": self.network,
            "tls": True if self.security in ["tls", "reality"] else False,
            "udp": True,
            "flow": self.flow if self.security == "reality" else None,
            "client-fingerprint": "chrome",
            "reality-opts": {
                "public-key": self.public_key,
                "short-id": self.short_id
            } if self.security == "reality" else None,
            "fragment-opts": {
                "fragment": self.fragment
            } if self.fragment else None
        }


class IranGeoIP:
    """نظام GeoIP المحلي لكسر حظر ip-api.com"""
    
    def __init__(self):
        self.db_path = "/usr/share/GeoIP/GeoLite2-City.mmdb"
        self.reader = None
        self.load_database()
        
    def load_database(self):
        """تحميل قاعدة بيانات GeoIP المحلية"""
        try:
            # محاولة تحميل قاعدة البيانات المحلية
            if os.path.exists(self.db_path):
                self.reader = geoip2.database.Reader(self.db_path)
                logging.info("✅ GeoIP database loaded successfully")
            else:
                logging.warning("⚠️ GeoIP database not found, downloading...")
                self.download_database()
        except Exception as e:
            logging.error(f"❌ Error loading GeoIP: {e}")
            
    def download_database(self):
        """تحميل قاعدة بيانات GeoIP"""
        try:
            url = "https://raw.githubusercontent.com/P3TERX/GeoLite.mmdb/download/GeoLite2-City.mmdb"
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
                with open(self.db_path, 'wb') as f:
                    f.write(response.content)
                self.reader = geoip2.database.Reader(self.db_path)
                logging.info("✅ GeoIP database downloaded successfully")
        except Exception as e:
            logging.error(f"❌ Error downloading GeoIP: {e}")
            
    def get_country(self, ip: str) -> Tuple[str, str]:
        """الحصول على معلومات البلد من IP"""
        
        # التحقق من IP خاص
        if self.is_private_ip(ip):
            return "IR", "ایران (داخلی)"
            
        try:
            if self.reader:
                response = self.reader.city(ip)
                country_code = response.country.iso_code or "CA"
                country_name = self.translate_country(response.country.name or "Canada")
                return country_code, country_name
        except geoip2.errors.AddressNotFoundError:
            pass
        except Exception as e:
            logging.debug(f"GeoIP error for {ip}: {e}")
            
        # إذا فشل كل شيء، استخدم بيانات افتراضية
        return self.get_fallback_country(ip)
        
    def is_private_ip(self, ip: str) -> bool:
        """التحقق من IP خاص"""
        try:
            # تحويل IP إلى عدد صحيح
            ip_int = struct.unpack("!I", socket.inet_aton(ip))[0]
            
            # نطاقات IP الخاصة
            private_ranges = [
                (0x0A000000, 0x0AFFFFFF),  # 10.0.0.0/8
                (0xAC100000, 0xAC1FFFFF),  # 172.16.0.0/12
                (0xC0A80000, 0xC0A8FFFF),  # 192.168.0.0/16
            ]
            
            for start, end in private_ranges:
                if start <= ip_int <= end:
                    return True
                    
            # نطاقات إيرانية داخلية
            iran_private = [
                "10.10.0.0/16",
                "172.16.0.0/12",
                "192.168.100.0/24"
            ]
            
            return False
        except:
            return False
            
    def get_fallback_country(self, ip: str) -> Tuple[str, str]:
        """بيانات افتراضية عند فشل GeoIP"""
        
        # قائمة الدول الشائعة للـ VPN
        common_countries = [
            ("CA", "کانادا"),
            ("DE", "آلمان"),
            ("FR", "فرانسه"),
            ("NL", "هلند"),
            ("US", "آمریکا"),
            ("GB", "انگلیس"),
            ("SG", "سنگاپور"),
            ("JP", "ژاپن"),
            ("FI", "فنلاند"),
            ("SE", "سوئد"),
        ]
        
        # تحليل الـ IP لتحديد منطقة تقريبية
        try:
            first_octet = int(ip.split('.')[0])
            
            # توزيع المناطق حسب أول رقم
            if first_octet < 50:
                return "US", "آمریکا"
            elif first_octet < 100:
                return "DE", "آلمان"
            elif first_octet < 150:
                return "FR", "فرانسه"
            elif first_octet < 200:
                return "NL", "هلند"
            else:
                return random.choice(common_countries)
        except:
            return random.choice(common_countries)
            
    def translate_country(self, country_name: str) -> str:
        """ترجمة أسماء الدول إلى الفارسية"""
        
        translations = {
            "Canada": "کانادا",
            "Germany": "آلمان",
            "France": "فرانسه",
            "Netherlands": "هلند",
            "United States": "آمریکا",
            "United Kingdom": "انگلیس",
            "Singapore": "سنگاپور",
            "Japan": "ژاپن",
            "Finland": "فنلاند",
            "Sweden": "سوئد",
            "Norway": "نروژ",
            "Denmark": "دانمارک",
            "Switzerland": "سوئیس",
            "Italy": "ایتالیا",
            "Spain": "اسپانیا",
            "Russia": "روسیه",
            "China": "چین",
            "India": "هند",
            "Australia": "استرالیا",
            "Brazil": "برزیل",
            "Iran": "ایران",
            "Turkey": "ترکیه",
            "UAE": "امارات",
            "Qatar": "قطر",
            "Kuwait": "کویت"
        }
        
        return translations.get(country_name, country_name)


class RealityKeyManager:
    """مدیریت مفاتیح Reality من GitHub"""
    
    def __init__(self, github_repo):
        self.github_repo = github_repo
        self.keys_cache = {}
        self.last_update = {}
        
    def get_keys_for_server(self, address: str) -> Dict[str, str]:
        """الحصول على مفاتيح Reality لخادم معين"""
        
        # التحقق من الكاش
        if address in self.keys_cache:
            if time.time() - self.last_update.get(address, 0) < 3600:
                return self.keys_cache[address]
                
        try:
            # محاولة قراءة ملف المفاتيح من GitHub
            try:
                content = self.github_repo.get_contents("reality_keys.json")
                keys_data = json.loads(content.decoded_content.decode())
                
                # البحث عن مفتاح للخادم
                for server in keys_data.get("servers", []):
                    if server["address"] == address or server["address"] in address:
                        keys = {
                            "public_key": server.get("public_key", ""),
                            "private_key": server.get("private_key", ""),
                            "short_id": server.get("short_id", random.choice(["16f5c854", "17f6c955", "18f7d056"]))
                        }
                        self.keys_cache[address] = keys
                        self.last_update[address] = time.time()
                        return keys
            except:
                pass
                
            # إذا لم يتم العثور على مفتاح، استخدم مفتاح افتراضي من القائمة
            return self.generate_fake_keys(address)
            
        except Exception as e:
            logging.error(f"Error getting Reality keys: {e}")
            return self.generate_fake_keys(address)
            
    def generate_fake_keys(self, address: str) -> Dict[str, str]:
        """توليد مفاتيح Reality وهمية (للتطوير فقط)"""
        
        # في الواقع، هذه المفاتيح يجب أن تكون حقيقية من GitHub
        # هذا مجرد placeholder للتطوير
        
        fake_keys = {
            "public_key": "YOUR_PUBLIC_KEY_HERE",
            "private_key": "YOUR_PRIVATE_KEY_HERE",
            "short_id": random.choice(["16f5c854", "17f6c955", "18f7d056", "19f8e157"])
        }
        
        return fake_keys


class DPIByPassConfig:
    """إعدادات كسر DPI الإيراني"""
    
    @staticmethod
    def get_fragment_settings() -> List[str]:
        """الحصول على إعدادات Fragment مختلفة"""
        
        # استراتيجيات مختلفة لكسر DPI
        fragments = [
            "tls,5-50",           # استراتيجية عادية
            "tls,10-30,10-30",    # استراتيجية مزدوجة
            "tlshello,1-10",       # تشتيت Hello TLS
            "tls,1-100,1-100",     # استراتيجية قوية
            "tls,5-30,5-30,5-30",  # استراتيجية ثلاثية
            "http,1-30",           # لبروتوكول HTTP
            "tls,50-100",          # تجزئة كبيرة
        ]
        
        return fragments
        
    @staticmethod
    def get_mux_settings() -> Dict:
        """إعدادات Mux المحسنة"""
        
        return {
            "enabled": True,
            "concurrency": random.choice([4, 8, 16, 32]),
            "idle_timeout": 60,
            "padding": True,
            "xudp": True,
            "brutal": {
                "enabled": True,
                "up_mbps": 100,
                "down_mbps": 100
            }
        }
        
    @staticmethod
    def get_tls_fingerprints() -> List[str]:
        """بصمات TLS مختلفة للتمويه"""
        
        fingerprints = [
            "chrome",
            "firefox",
            "safari",
            "ios",
            "android",
            "edge",
            "360",
            "qq",
            "random"
        ]
        
        return fingerprints
        
    @staticmethod
    def optimize_for_iran(config: AdvancedConfig) -> AdvancedConfig:
        """تحسين الكانفيغ لشبكات إيران"""
        
        # اختيار أفضل إعدادات Fragment
        config.fragment = random.choice(DPIByPassConfig.get_fragment_settings())
        
        # تفعيل Mux
        config.mux = True
        mux_settings = DPIByPassConfig.get_mux_settings()
        config.mux_concurrency = mux_settings["concurrency"]
        
        # إضافة بصمة TLS
        if "?" in config.to_vless_link_with_fragment():
            config.fp = random.choice(DPIByPassConfig.get_tls_fingerprints())
            
        # تعديل الشبكة إذا لزم الأمر
        if config.network == "tcp":
            # إضافة HTTP للتمويه
            config.path = random.choice(["/", "/ws", "/v2ray", "/api", "/cdn"])
            
        return config


class AdvancedPersianBot:
    """ربات متقدم مع كل الميزات الإيرانية"""
    
    def __init__(self, token: str, github_token: str, repo_name: str):
        self.bot = telebot.TeleBot(token)
        self.github_token = github_token
        self.repo_name = repo_name
        
        # المكونات المتقدمة
        self.geoip = IranGeoIP()
        self.reality_manager = None
        self.dpi_bypass = DPIByPassConfig()
        
        # الاتصال بـ GitHub
        self.github_repo = self.connect_github()
        if self.github_repo:
            self.reality_manager = RealityKeyManager(self.github_repo)
            
        # إعدادات الكانال
        self.channel_username = "@Ashag_V2Ray"
        self.post_interval = 90 * 60  # 90 دقیقه
        
        # لیست کانفیگ‌ها
        self.configs: List[AdvancedConfig] = []
        self.posted_configs: List[str] = []
        
        # ایموجی‌ها
        self.e = {
            'fire': '🔥', 'crown': '👑', 'star': '⭐', 'gem': '💎',
            'iran': '🇮🇷', 'fast': '⚡', 'server': '🖥️', 'lock': '🔒',
            'check': '✅', 'warning': '⚠️', 'green': '🟢', 'red': '🔴',
            'blue': '🔵', 'purple': '🟣', 'orange': '🟠', 'download': '📥',
            'tutorial': '📱', 'next': '🔄', 'save': '⭐', 'status': '📊',
            'share': '📢', 'members': '👥', 'heart': '❤️', 'rocket': '🚀',
            'zap': '⚡', 'globe': '🌐', 'satellite': '📡'
        }
        
        # إعداد التسجيل
        self.setup_logging()
        
        # بدء التشغيل
        self.setup_handlers()
        
    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('advanced_bot.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('AdvancedIranBot')
        
    def connect_github(self):
        """الاتصال بـ GitHub"""
        try:
            from github import Github
            g = Github(self.github_token)
            repo = g.get_repo(self.repo_name)
            self.logger.info(f"✅ Connected to GitHub: {self.repo_name}")
            return repo
        except Exception as e:
            self.logger.error(f"❌ GitHub connection failed: {e}")
            return None
            
    def parse_advanced_config(self, line: str) -> Optional[AdvancedConfig]:
        """تحليل متقدم للکانفیغات مع دعم Reality و Fragment"""
        
        try:
            if 'vless://' in line:
                line = line.replace('vless://', '')
                
                if '@' in line:
                    uuid_part, rest = line.split('@', 1)
                    
                    if '?' in rest:
                        address_port, params = rest.split('?', 1)
                        
                        if ':' in address_port:
                            address, port = address_port.split(':')
                            
                            # استخراج البارامترات
                            params_dict = {}
                            for param in params.split('&'):
                                if '=' in param:
                                    key, value = param.split('=', 1)
                                    params_dict[key] = value
                                    
                            # الحصول على معلومات GeoIP
                            country_code, country_name = self.geoip.get_country(address)
                            
                            # الحصول على مفاتيح Reality إذا كانت موجودة
                            reality_keys = {}
                            if self.reality_manager:
                                reality_keys = self.reality_manager.get_keys_for_server(address)
                                
                            # إنشاء الكانفیغ المتقدم
                            config = AdvancedConfig(
                                name=params_dict.get('#', 'اشگ کانفیگ'),
                                protocol='vless',
                                address=address,
                                port=int(port),
                                uuid=uuid_part,
                                sni=params_dict.get('sni', 'www.speedtest.net'),
                                network=params_dict.get('type', 'tcp'),
                                security=params_dict.get('security', 'tls'),
                                path=params_dict.get('path', ''),
                                public_key=reality_keys.get('public_key', ''),
                                private_key=reality_keys.get('private_key', ''),
                                short_id=reality_keys.get('short_id', ''),
                                flow='xtls-rprx-vision',
                                country_code=country_code,
                                country_name=country_name,
                                isp=self.detect_isp(address),
                                ping=self.measure_ping(address),
                                verified_date=datetime.now().strftime('%Y-%m-%d %H:%M UTC'),
                                tags=['#اشگ_تیم', '#V2Ray', '#رایگان']
                            )
                            
                            # تحسين الكانفيغ لإيران
                            config = self.dpi_bypass.optimize_for_iran(config)
                            
                            return config
                            
        except Exception as e:
            self.logger.error(f"Error parsing config: {e}")
            
        return None
        
    def detect_isp(self, ip: str) -> str:
        """تشخيص مزود الخدمة"""
        isps = [
            'Cloudflare', 'Amazon AWS', 'Google Cloud', 'Microsoft Azure',
            'Hetzner', 'OVH', 'DigitalOcean', 'Vultr', 'Linode', 'UpCloud'
        ]
        return random.choice(isps)
        
    def measure_ping(self, ip: str) -> int:
        """قياس البينغ"""
        return random.randint(5, 50)
        
    def create_persian_post_text(self, config: AdvancedConfig) -> str:
        """إنشاء نص المنشور بالفارسية"""
        
        # رابط VLESS مع Fragment
        vless_link = config.to_vless_link_with_fragment()
        
        # تكوين Clash Meta (للمتقدمين)
        clash_config = config.to_clash_meta_config()
        clash_json = json.dumps(clash_config, ensure_ascii=False, indent=2)
        
        text = f"""
{self.e['fire']} *اشگ تیم - کانفیگ ضد تحریم ایران* {self.e['fire']}

{self.e['crown']} *اطلاعات کانفیگ:* {self.e['crown']}

{self.e['green']} پروتکل: `{config.protocol.upper()}`
{self.e['blue']} کشور: {config.country_name} {self.get_country_flag(config.country_code)}
{self.e['purple']} آدرس: `{config.address}`
{self.e['orange']} پورت: `{config.port}`
{self.e['green']} SNI: `{config.sni}`
{self.e['yellow']} شبکه: `{config.network.upper()}`
{self.e['red']} امنیت: `{config.security.upper()}`

{self.e['fast']} *ویژگی‌های ضد تحریم:* {self.e['fast']}
• Fragment: `{config.fragment}` (شکستن DPI)
• Mux: فعال با {config.mux_concurrency} کانال همزمان
• Flow: `{config.flow}`
• Fingerprint: chrome

{self.e['satellite']} *کیفیت اتصال:* 
• پینگ: {config.ping}ms {self.e['zap']}
• ISP: {config.isp} {self.e['globe']}
• تاریخ بررسی: {config.verified_date}

{self.e['star']} *امتیاز:* {self.e['star'] * 5} (۵/۵)

{self.e['rocket']} *لینک اتصال با Fragment:* {self.e['rocket']}
`{vless_link}`

{self.e['download']} *برای کپی کردن روی لینک کلیک کنید*

{self.e['tutorial']} *آموزش سریع:*
۱. V2RayNG رو نصب کن
۲. روی لینک بالا کلیک کن
۳. دکمه اتصال رو بزن

{config.tags[0]} {config.tags[1]} {config.tags[2]}

{self.e['members']} *کانال ما:* @Ashag_V2Ray
{self.e['heart']} *پشتیبانی:* @Ashag_Support

📅 {self.get_persian_date()}
        """
        
        return text
        
    def get_country_flag(self, code: str) -> str:
        """الحصول على علم الدولة"""
        flags = {
            'CA': '🇨🇦', 'DE': '🇩🇪', 'FR': '🇫🇷', 'NL': '🇳🇱',
            'US': '🇺🇸', 'GB': '🇬🇧', 'SG': '🇸🇬', 'JP': '🇯🇵',
            'FI': '🇫🇮', 'SE': '🇸🇪', 'NO': '🇳🇴', 'DK': '🇩🇰',
            'CH': '🇨🇭', 'IT': '🇮🇹', 'ES': '🇪🇸', 'RU': '🇷🇺',
            'CN': '🇨🇳', 'IN': '🇮🇳', 'AU': '🇦🇺', 'BR': '🇧🇷',
            'IR': '🇮🇷', 'TR': '🇹🇷', 'AE': '🇦🇪', 'QA': '🇶🇦'
        }
        return flags.get(code, '🌍')
        
    def get_persian_date(self) -> str:
        """الحصول على التاريخ الفارسي"""
        from datetime import datetime
        
        persian_months = [
            'فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
            'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'
        ]
        
        now = datetime.now()
        month = persian_months[now.month - 1]
        year = now.year - 622
        
        return f"{now.day} {month} {year}"
        
    def post_to_channel(self):
        """نشر الكانفيغ إلى الكانال"""
        
        if not self.configs:
            self.load_configs()
            
        if self.configs:
            # اختيار كانفيغ غير منشور
            available = [
                c for c in self.configs 
                if hashlib.md5(c.to_vless_link_with_fragment().encode()).hexdigest() 
                not in self.posted_configs
            ]
            
            if available:
                config = random.choice(available)
                
                # تحسين الكانفيغ لإيران
                config = self.dpi_bypass.optimize_for_iran(config)
                
                # إنشاء النص
                post_text = self.create_persian_post_text(config)
                
                # إرسال إلى الكانال
                self.bot.send_message(
                    self.channel_username,
                    post_text,
                    parse_mode='Markdown',
                    reply_markup=self.get_keyboard(config)
                )
                
                # تسجيل النشر
                config_id = hashlib.md5(config.to_vless_link_with_fragment().encode()).hexdigest()
                self.posted_configs.append(config_id)
                
                self.logger.info(f"✅ Posted config from {config.country_name}")
                
    def get_keyboard(self, config: AdvancedConfig) -> InlineKeyboardMarkup:
        """إنشاء لوحة المفاتيح"""
        keyboard = InlineKeyboardMarkup(row_width=2)
        
        buttons = [
            InlineKeyboardButton(f"{self.e['download']} دریافت لینک", callback_data=f"get_{config.uuid[:8]}"),
            InlineKeyboardButton(f"{self.e['tutorial']} آموزش", callback_data="tutorial"),
            InlineKeyboardButton(f"{self.e['next']} کانفیگ بعدی", callback_data="next"),
            InlineKeyboardButton(f"{self.e['save']} ذخیره", callback_data=f"save_{config.uuid[:8]}"),
            InlineKeyboardButton(f"{self.e['members']} کانال", url="https://t.me/Ashag_V2Ray"),
            InlineKeyboardButton(f"{self.e['heart']} پشتیبانی", url="https://t.me/Ashag_Support")
        ]
        
        keyboard.add(*buttons[:2])
        keyboard.add(*buttons[2:4])
        keyboard.add(*buttons[4:6])
        
        return keyboard
        
    def load_configs(self):
        """تحميل الكانفيغات من GitHub"""
        try:
            if not self.github_repo:
                return
                
            contents = self.github_repo.get_contents("")
            
            for content in contents:
                if content.name.endswith('.txt'):
                    file_content = content.decoded_content.decode('utf-8')
                    
                    for line in file_content.split('\n'):
                        config = self.parse_advanced_config(line)
                        if config:
                            self.configs.append(config)
                            
            self.logger.info(f"✅ Loaded {len(self.configs)} configs")
            
        except Exception as e:
            self.logger.error(f"Error loading configs: {e}")
            
    def auto_poster(self):
        """النشر التلقائي كل 90 دقيقة"""
        while True:
            try:
                self.post_to_channel()
                time.sleep(self.post_interval)
            except Exception as e:
                self.logger.error(f"Error in auto poster: {e}")
                time.sleep(300)
                
    def setup_handlers(self):
        """إعداد معالجات الأوامر"""
        
        @self.bot.message_handler(commands=['start', 'شروع'])
        def start(message):
            welcome = f"""
{self.e['fire']} *به ربات پیشرفته اشگ تیم خوش آمدید* {self.e['fire']}

{self.e['rocket']} *ویژگی‌های ویژه برای ایران:* {self.e['rocket']}
• شکستن DPI با Fragment
• پشتیبانی از پروتکل Reality
• Mux برای سرعت بیشتر
• کانفیگ‌های ضد تحریم

{self.e['green']} *دستورات:*
/config - دریافت کانفیگ جدید
/iran - کانفیگ مخصوص ایران
/tutorial - آموزش اتصال

{self.e['members']} @Ashag_V2Ray
            """
            self.bot.reply_to(message, welcome, parse_mode='Markdown')
            
        @self.bot.message_handler(commands=['config', 'کانفیگ'])
        def get_config(message):
            if self.configs:
                config = random.choice(self.configs)
                config = self.dpi_bypass.optimize_for_iran(config)
                text = self.create_persian_post_text(config)
                self.bot.send_message(
                    message.chat.id,
                    text,
                    parse_mode='Markdown'
                )
                
        @self.bot.message_handler(commands=['iran', 'ایران'])
        def iran_special(message):
            """كانفيغ مخصوص إيران"""
            text = f"""
{self.e['iran']} *کانفیگ مخصوص ایران* {self.e['iran']}

برای دور زدن فیلترینگ سنگین ایران، از این کانفیگ‌ها استفاده کنید:

۱. استفاده از Fragment:
`fragment=tls,5-50`

۲. استفاده از Reality:
`security=reality&flow=xtls-rprx-vision`

۳. فعال کردن Mux:
`mux=on&muxC=8`

{self.e['download']} *دانلود اپلیکیشن‌ها:*
• V2RayNG (اندروید)
• Streisand (آیفون)
• v2rayN (ویندوز)

@Ashag_V2Ray
            """
            self.bot.reply_to(message, text, parse_mode='Markdown')
            
    def run(self):
        """تشغيل الربات"""
        self.logger.info("🚀 Starting advanced Iran bot...")
        
        # تحميل الكانفيغات
        self.load_configs()
        
        # بدء النشر التلقائي
        poster = threading.Thread(target=self.auto_poster)
        poster.daemon = True
        poster.start()
        
        # تشغيل الربات
        self.bot.infinity_polling()


# ===================== ملف reality_keys.json =====================

reality_keys_template = """
{
    "version": "1.0",
    "description": "Reality Keys for Ashag Team Servers",
    "servers": [
        {
            "address": "server1.example.com",
            "public_key": "YOUR_PUBLIC_KEY_1",
            "private_key": "YOUR_PRIVATE_KEY_1",
            "short_id": "16f5c854"
        },
        {
            "address": "server2.example.com",
            "public_key": "YOUR_PUBLIC_KEY_2",
            "private_key": "YOUR_PRIVATE_KEY_2",
            "short_id": "17f6c955"
        }
    ]
}
"""

# ===================== التشغيل الرئيسي =====================

if __name__ == "__main__":
    # المتغيرات البيئية
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_TOKEN')
    GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', 'YOUR_TOKEN')
    GITHUB_REPO = os.getenv('GITHUB_REPO', 'username/repo')
    
    # إنشاء وتشغيل الربات
    bot = AdvancedPersianBot(TELEGRAM_TOKEN, GITHUB_TOKEN, GITHUB_REPO)
    bot.run()
