import asyncio
import json
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from .models import Candle, Instrument


def _market_active():
    now = timezone.localtime()
    if now.weekday() >= 5:
        return False
    minute = now.hour * 60 + now.minute
    first_end = 11 * 60 + 30 if now.weekday() == 4 else 12 * 60
    second_start = 14 * 60 if now.weekday() == 4 else 13 * 60 + 30
    return (8 * 60 + 57 <= minute <= first_end) or (second_start - 3 <= minute <= 15 * 60 + 49)


@database_sync_to_async
def _price_snapshot(symbols, live_symbol):
    requested = list(dict.fromkeys([live_symbol.upper() if live_symbol else "", *(symbol.upper() for symbol in symbols)]))
    requested = [symbol for symbol in requested if symbol][:40]
    five = Candle.objects.filter(instrument=OuterRef("pk"), interval="5m").order_by("-timestamp")
    daily = Candle.objects.filter(instrument=OuterRef("pk"), interval="1d").order_by("-timestamp")
    rows = Instrument.objects.filter(symbol__in=requested).annotate(
        five_close=Subquery(five.values("close")[:1]), five_high=Subquery(five.values("high")[:1]),
        five_low=Subquery(five.values("low")[:1]), five_volume=Subquery(five.values("volume")[:1]),
        five_time=Subquery(five.values("timestamp")[:1]), daily_close=Subquery(daily.values("close")[:1]),
        daily_high=Subquery(daily.values("high")[:1]), daily_low=Subquery(daily.values("low")[:1]),
        daily_volume=Subquery(daily.values("volume")[:1]), daily_time=Subquery(daily.values("timestamp")[:1]),
        previous_close=Subquery(daily.values("close")[1:2]),
    )
    prices = {}
    for row in rows:
        use_five = row.five_time and (not row.daily_time or row.five_time >= row.daily_time)
        price = row.five_close if use_five else row.daily_close
        if price is None:
            continue
        prices[row.symbol] = {
            "price": float(price), "high": float(row.five_high if use_five else row.daily_high),
            "low": float(row.five_low if use_five else row.daily_low),
            "volume": int(row.five_volume if use_five else row.daily_volume),
            "market_time": (row.five_time if use_five else row.daily_time).isoformat(),
            "previous_close": float(row.previous_close or row.daily_close or price),
            "interval": "5m" if use_five else "1d",
        }
    return {"event": "market.snapshot", "market_active": _market_active(), "prices": prices,
            "server_time": timezone.now().isoformat()}


class MarketConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.symbols = []
        self.live_symbol = ""
        self.last_snapshot = None
        await self.channel_layer.group_add("market", self.channel_name)
        await self.accept()
        self.stream_task = asyncio.create_task(self._stream())

    async def disconnect(self, close_code):
        if hasattr(self, "stream_task"):
            self.stream_task.cancel()
        await self.channel_layer.group_discard("market", self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            return
        if data.get("action") == "subscribe":
            self.symbols = [str(value) for value in data.get("symbols", [])][:30]
            self.live_symbol = str(data.get("live_symbol", ""))[:16]
            self.last_snapshot = None

    async def _stream(self):
        try:
            while True:
                payload = await _price_snapshot(self.symbols, self.live_symbol)
                encoded = json.dumps(payload, sort_keys=True)
                if encoded != self.last_snapshot:
                    await self.send(encoded)
                    self.last_snapshot = encoded
                # Active feed checks stored collector output frequently but emits
                # only on change. Closed market sends one final snapshot, then idles.
                await asyncio.sleep(3 if payload["market_active"] else 60)
        except asyncio.CancelledError:
            pass

    async def market_update(self, event):
        await self.send(json.dumps(event["payload"]))
