import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from trading.models import Candle
from django.utils import timezone
symbol = 'ERAA'
candles = list(Candle.objects.filter(instrument__symbol=symbol, interval="1d").order_by("-timestamp")[:2])
print("Candle 0 timestamp:", candles[0].timestamp)
print("Candle 1 timestamp:", candles[1].timestamp)
today = timezone.localdate()
latest_date = timezone.localtime(candles[0].timestamp).date()
print("Today:", today)
print("Latest date:", latest_date)
if latest_date >= today and len(candles) > 1:
    print("Previous close:", float(candles[1].close))
else:
    print("Previous close:", float(candles[0].close))
