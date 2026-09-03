import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from trading.models import Candle
from django.utils import timezone
import datetime

symbol = "ERAA"
candles = list(Candle.objects.filter(instrument__symbol=symbol, interval="1d").order_by("-timestamp")[:1])
print("Candle 0:", candles[0].timestamp)

today_midnight = timezone.make_aware(datetime.datetime.combine(timezone.localdate(), datetime.time.min))
print("Today Midnight:", today_midnight)

prev_candle = Candle.objects.filter(instrument__symbol=symbol, interval="1d", timestamp__lt=today_midnight).order_by("-timestamp").first()

print("Prev Candle:", prev_candle.timestamp if prev_candle else None)
print("Previous Close:", prev_candle.close if prev_candle else None)

