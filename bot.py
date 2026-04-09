#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت AliExpress Twitter - ينشر تغريدة واحدة عند كل تشغيل
يُشغَّل 15 مرة يومياً عبر GitHub Actions
"""

import hashlib
import time
import requests
import os
import logging
import random
import tweepy
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== إعدادات API ====================
# AliExpress
AE_APP_KEY = os.environ.get('AE_APP_KEY', '531672')
AE_APP_SECRET = os.environ.get('AE_APP_SECRET', 'kr2XqMjkaEbsUvAXLEGXOP6PLdUXjGEL')
AE_API_URL = 'https://api-sg.aliexpress.com/sync'
AE_TRACKING_ID = 'default'

# Twitter
TW_CONSUMER_KEY = os.environ.get('TW_CONSUMER_KEY', 'k7Gr5I4nnp2GNIoVuGcUpx85X')
TW_CONSUMER_SECRET = os.environ.get('TW_CONSUMER_SECRET', 'HaaHWrcsFEnhJgS4gGJoVaZ1hTyaI511VQICcCjtDgo5g5wtBR')
TW_ACCESS_TOKEN = os.environ.get('TW_ACCESS_TOKEN', '1676288058671374339-OF8cltNe5JbUPshBtEEclNfr5fjNGJ')
TW_ACCESS_TOKEN_SECRET = os.environ.get('TW_ACCESS_TOKEN_SECRET', 'jLjqp91seV0GdhFdvVuWwwh8nLBBFfcX14QOEEVXD6lsh')

# OpenAI
openai_client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

# فئات المنتجات
CATEGORIES = [
    {'keywords': 'wireless earbuds bluetooth headphones', 'emoji': '🎧'},
    {'keywords': 'smart watch fitness tracker', 'emoji': '⌚'},
    {'keywords': 'phone case cover accessories', 'emoji': '📱'},
    {'keywords': 'LED light strip RGB smart', 'emoji': '💡'},
    {'keywords': 'portable charger power bank', 'emoji': '🔋'},
    {'keywords': 'kitchen gadgets tools cooking', 'emoji': '🍳'},
    {'keywords': 'home storage organizer box', 'emoji': '🏠'},
    {'keywords': 'bluetooth speaker portable', 'emoji': '🔊'},
    {'keywords': 'security camera wifi outdoor', 'emoji': '📹'},
    {'keywords': 'car accessories gadgets usb', 'emoji': '🚗'},
    {'keywords': 'skincare beauty face serum', 'emoji': '✨'},
    {'keywords': 'electric toothbrush oral care', 'emoji': '🦷'},
    {'keywords': 'mini fan portable usb cooling', 'emoji': '💨'},
    {'keywords': 'backpack travel bag waterproof', 'emoji': '🎒'},
    {'keywords': 'smart home automation switch', 'emoji': '🏡'},
]

TWEET_TYPES = ['deal', 'deal', 'deal', 'review', 'list']  # deal أكثر شيوعاً


# ==================== AliExpress API ====================

def ae_sign(params):
    sorted_params = sorted(params.items())
    sign_str = AE_APP_SECRET + ''.join([f'{k}{v}' for k, v in sorted_params]) + AE_APP_SECRET
    return hashlib.md5(sign_str.encode('utf-8')).hexdigest().upper()


def ae_call(method, extra={}):
    params = {
        'app_key': AE_APP_KEY,
        'method': method,
        'sign_method': 'md5',
        'timestamp': str(int(time.time() * 1000)),
        'v': '2.0',
        'format': 'json',
    }
    params.update(extra)
    params['sign'] = ae_sign(params)
    try:
        r = requests.get(AE_API_URL, params=params, timeout=20)
        return r.json()
    except Exception as e:
        logger.error(f"AliExpress API error: {e}")
        return {}


def get_affiliate_link(product_url):
    result = ae_call('aliexpress.affiliate.link.generate', {
        'promotion_link_type': '0',
        'source_values': product_url,
        'tracking_id': AE_TRACKING_ID,
    })
    try:
        links = (result
                 .get('aliexpress_affiliate_link_generate_response', {})
                 .get('resp_result', {})
                 .get('result', {})
                 .get('promotion_links', {})
                 .get('promotion_link', []))
        if links:
            return links[0].get('promotion_link', product_url)
    except Exception:
        pass
    return product_url


def fetch_products(keyword=None, page_size=10):
    """جلب منتجات من AliExpress"""
    extra = {
        'sort': 'LAST_VOLUME_DESC',
        'page_no': '1',
        'page_size': str(page_size),
        'min_sale_price': '5',
        'fields': ','.join([
            'product_id', 'product_title', 'sale_price', 'original_price',
            'discount', 'product_main_image_url', 'promotion_link',
            'coupon_amount', 'evaluate_rate', 'lastest_volume',
            'target_sale_price', 'target_original_price',
            'first_level_category_name'
        ]),
        'target_currency': 'SAR',
        'target_language': 'EN',
    }
    if keyword:
        extra['keywords'] = keyword

    result = ae_call('aliexpress.affiliate.product.query', extra)
    products = (result
                .get('aliexpress_affiliate_product_query_response', {})
                .get('resp_result', {})
                .get('result', {})
                .get('products', {})
                .get('product', []))

    # فلترة بخصم 35%+
    filtered = []
    for p in products:
        disc = p.get('discount', '0%').replace('%', '').strip()
        try:
            if int(disc) >= 35:
                filtered.append(p)
        except ValueError:
            pass
    return filtered


def download_image(url, product_id):
    """تحميل صورة المنتج"""
    path = f"/tmp/{product_id}.jpg"
    if os.path.exists(path) and os.path.getsize(path) > 5000:
        return path
    try:
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.aliexpress.com/'}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200 and len(r.content) > 5000:
            with open(path, 'wb') as f:
                f.write(r.content)
            return path
    except Exception as e:
        logger.warning(f"Image download failed: {e}")
    return None


def get_emoji(title, category=''):
    title_lower = title.lower()
    cat_lower = category.lower()
    checks = [
        (['earbuds', 'headphone', 'earphone'], '🎧'),
        (['watch', 'smartwatch'], '⌚'),
        (['phone', 'case', 'cover'], '📱'),
        (['light', 'led', 'lamp'], '💡'),
        (['charger', 'power bank', 'battery'], '🔋'),
        (['kitchen', 'cooking'], '🍳'),
        (['storage', 'organizer'], '🏠'),
        (['speaker', 'audio'], '🔊'),
        (['camera', 'security'], '📹'),
        (['car', 'auto'], '🚗'),
        (['skin', 'beauty', 'cream'], '✨'),
        (['tooth', 'dental'], '🦷'),
        (['fan', 'cooling'], '💨'),
        (['bag', 'backpack'], '🎒'),
    ]
    for keywords, emoji in checks:
        if any(kw in title_lower or kw in cat_lower for kw in keywords):
            return emoji
    return '🛒'


# ==================== توليد التغريدات ====================

def generate_tweet_text(product, tweet_type, all_products=None):
    """توليد نص التغريدة بالعربية السعودية"""
    name = product['name']
    sale = product['sale_price']
    original = product['original_price']
    discount = product['discount']
    emoji = product['emoji']
    coupon = product.get('coupon_amount')

    if tweet_type == 'deal':
        prompt = f"""اكتب تغريدة قصيرة جداً بالعربية السعودية البسيطة عن عرض من علي اكسبريس.

المنتج (بالإنجليزية): {name[:80]}
السعر الأصلي: {original}
سعر العرض: {sale}
الخصم: {discount}
{f'كوبون خصم إضافي: {coupon} ريال' if coupon else ''}

الشروط:
- ترجم اسم المنتج للعربية (3-4 كلمات فقط)
- لهجة سعودية عامية بسيطة (والله، ما يطيح، جرب، يستاهل، حلو)
- سطرين أو ثلاثة فقط
- لا تكتب هاشتاقات ولا روابط
- ابدأ بالإيموجي {emoji}
{f'- اذكر الكوبون بشكل مثير' if coupon else ''}

مثال:
"{emoji} [اسم المنتج]
كان {original} وصار {sale} 😱
خصم {discount} والله ما يطيح!"
"""

    elif tweet_type == 'review':
        prompt = f"""اكتب تغريدة قصيرة بالعربية السعودية كأنك اشتريت المنتج وتشارك تجربتك.

المنتج: {name[:80]}
السعر: {sale}

الشروط:
- ترجم اسم المنتج للعربية (3-4 كلمات)
- لهجة سعودية عامية بسيطة وصادقة
- سطرين أو ثلاثة فقط
- لا تكتب هاشتاقات ولا روابط
- ابدأ بإيموجي

مثال:
"✅ اشتريت [اسم المنتج] من علي اكسبريس
بـ {sale} وما ندمت {emoji}
يستاهل والله!"
"""

    else:  # list
        items = (all_products or [product])[:3]
        items_text = '\n'.join([
            f"{p['emoji']} {p['name'][:50]} - {p['sale_price']} (خصم {p['discount']})"
            for p in items
        ])
        prompt = f"""اكتب تغريدة قصيرة بالعربية السعودية عن أفضل عروض اليوم من علي اكسبريس.

المنتجات:
{items_text}

الشروط:
- ترجم أسماء المنتجات للعربية
- لهجة سعودية عامية بسيطة
- 4-5 أسطر فقط
- لا تكتب هاشتاقات ولا روابط
- ابدأ بعنوان جذاب
"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "اكتب فقط نص التغريدة بدون أي شرح. لهجة سعودية بسيطة ومختصرة."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.9
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        return f"{emoji} منتج مميز من علي اكسبريس\nكان {original} وصار {sale} 😱\nخصم {discount} والله يستاهل!"


# ==================== Twitter API ====================

def post_to_twitter(text, image_path=None):
    """نشر التغريدة عبر Twitter API"""
    # اقتصار النص على 270 حرف
    if len(text) > 270:
        lines = text.split('\n')
        while len('\n'.join(lines)) > 270 and len(lines) > 1:
            lines.pop(-2) if len(lines) > 2 else lines.pop(0)
        text = '\n'.join(lines)
        if len(text) > 270:
            text = text[:267] + '…'

    logger.info(f"📤 نشر التغريدة ({len(text)} حرف)...")

    # v1.1 لرفع الوسائط
    auth = tweepy.OAuth1UserHandler(TW_CONSUMER_KEY, TW_CONSUMER_SECRET, TW_ACCESS_TOKEN, TW_ACCESS_TOKEN_SECRET)
    api_v1 = tweepy.API(auth)

    # v2 للنشر
    client_v2 = tweepy.Client(
        consumer_key=TW_CONSUMER_KEY,
        consumer_secret=TW_CONSUMER_SECRET,
        access_token=TW_ACCESS_TOKEN,
        access_token_secret=TW_ACCESS_TOKEN_SECRET
    )

    media_ids = []
    if image_path and os.path.exists(image_path) and os.path.getsize(image_path) > 1000:
        try:
            media = api_v1.media_upload(filename=image_path)
            media_ids.append(media.media_id)
            logger.info(f"✅ تم رفع الصورة: {media.media_id}")
        except Exception as e:
            logger.warning(f"⚠️ فشل رفع الصورة: {e}")

    try:
        if media_ids:
            response = client_v2.create_tweet(text=text, media_ids=media_ids)
        else:
            response = client_v2.create_tweet(text=text)

        if response.data:
            tweet_id = response.data['id']
            logger.info(f"✅ تم النشر! ID: {tweet_id}")
            logger.info(f"   رابط: https://x.com/AbdulazizA6933/status/{tweet_id}")
            return True
    except tweepy.TweepyException as e:
        logger.error(f"❌ Twitter API error: {e}")

    return False


# ==================== البوت الرئيسي ====================

def run_bot():
    """تشغيل البوت - ينشر تغريدة واحدة"""
    logger.info("🚀 تشغيل بوت AliExpress Twitter...")

    # اختيار فئة عشوائية
    cat = random.choice(CATEGORIES)
    logger.info(f"📦 الفئة: {cat['keywords']}")

    # جلب المنتجات
    products_raw = fetch_products(keyword=cat['keywords'], page_size=10)

    # إذا لم تجد منتجات بكلمة مفتاحية، جلب عامة
    if not products_raw:
        logger.info("🔄 جلب منتجات عامة...")
        products_raw = fetch_products(page_size=20)

    if not products_raw:
        logger.error("❌ لم يتم جلب أي منتجات!")
        return False

    # تنسيق المنتجات
    formatted = []
    for raw in products_raw[:8]:
        pid = str(raw.get('product_id', ''))
        title = raw.get('product_title', '')
        sale = raw.get('target_sale_price', raw.get('sale_price', '0'))
        original = raw.get('target_original_price', raw.get('original_price', '0'))
        discount = raw.get('discount', '0%')
        image_url = raw.get('product_main_image_url', '')
        promo_link = raw.get('promotion_link', '')
        coupon = raw.get('coupon_amount')
        category = raw.get('first_level_category_name', '')

        try:
            sale_fmt = f"{float(sale):.0f} ريال"
            orig_fmt = f"{float(original):.0f} ريال"
        except (ValueError, TypeError):
            sale_fmt = f"{sale} ريال"
            orig_fmt = f"{original} ريال"

        # رابط الأفلييت
        if not promo_link or 's.click.aliexpress.com' not in promo_link:
            promo_link = get_affiliate_link(f"https://www.aliexpress.com/item/{pid}.html")

        # تحميل الصورة
        img_path = download_image(image_url, pid) if image_url else None

        if img_path:
            formatted.append({
                'id': pid,
                'name': title,
                'sale_price': sale_fmt,
                'original_price': orig_fmt,
                'discount': discount,
                'emoji': get_emoji(title, category),
                'url': promo_link,
                'coupon_amount': coupon,
                'image': img_path,
            })

    if not formatted:
        logger.error("❌ لم يتم تحميل أي صورة منتج!")
        return False

    logger.info(f"✅ {len(formatted)} منتج جاهز")

    # اختيار نوع التغريدة والمنتج
    tweet_type = random.choice(TWEET_TYPES)
    product = random.choice(formatted)

    logger.info(f"📝 نوع التغريدة: {tweet_type}")
    logger.info(f"🛒 المنتج: {product['name'][:60]}")
    logger.info(f"💰 السعر: {product['sale_price']} (أصلي: {product['original_price']}) | خصم: {product['discount']}")

    # توليد نص التغريدة
    body = generate_tweet_text(product, tweet_type, formatted if tweet_type == 'list' else None)

    # تجميع التغريدة الكاملة
    hashtags = "#AliExpress #عروض #تخفيضات"
    full_tweet = f"{body}\n\n{hashtags}\n{product['url']}"

    logger.info(f"\n{'='*50}")
    logger.info(f"التغريدة:\n{full_tweet}")
    logger.info(f"{'='*50}\n")

    # النشر
    success = post_to_twitter(full_tweet, product['image'])

    if success:
        logger.info("✅ تم النشر بنجاح!")
    else:
        logger.error("❌ فشل النشر!")

    return success


if __name__ == "__main__":
    import sys
    success = run_bot()
    sys.exit(0 if success else 1)
