import asyncio
import logging
from decimal import Decimal
from threading import Thread

from src.exchange import Exchange

TWOPLACES = Decimal("0.01")


class InterExchangeArbitrationStrategy:
    def __init__(
        self,
        *,
        pair: str,
        profit_size: float,
        demo: bool = False,
        binance: Exchange,
        ftx: Exchange,
    ) -> None:
        self.pair = pair
        self.profit_size = profit_size
        self.total_profit = Decimal("0.00").quantize(TWOPLACES)
        self.total_deal = 0
        self.demo = demo
        self.binance = binance
        self.ftx = ftx
        self.binance.attach(self)
        self.ftx.attach(self)
        self.binance_thread: Thread = None  # type: ignore
        self.ftx_thread: Thread = None  # type: ignore

    def start(self) -> None:
        self.binance_thread = Thread(target=asyncio.run, args=(self.binance.start(),))
        self.ftx_thread = Thread(target=asyncio.run, args=(self.ftx.start(),))
        self.binance_thread.start()
        self.ftx_thread.start()
        logging.info(f"Started watching of the pair of currencies {self.pair} on the exchanges ftx and binance")
        self.binance_thread.join()
        self.ftx_thread.join()

    def stop(self) -> None:
        self.binance.stop()
        self.ftx.stop()
        self.binance_thread.join()
        self.ftx_thread.join()

    async def update(self, exchange: Exchange) -> None:
        other = self.get_other_exchange(exchange)
        if 0 < exchange.best_ask.price < other.best_bid.price:
            await self.make_deals(exchange, other)
        elif 0 < other.best_ask.price < exchange.best_bid.price:
            await self.make_deals(other, exchange)

    def get_other_exchange(self, exchange: Exchange) -> Exchange:
        if exchange.exchange_name == "ftx":
            return self.binance
        return self.ftx

    async def make_deals(
        self,
        efp: Exchange,  # exchange_for_purchase
        efs: Exchange,  # exchange_for_sale
    ) -> None:
        qty = min(efp.best_ask.qty, efs.best_bid.qty)
        if qty <= 0:
            return
        purchase_price = Decimal(qty * efp.best_ask.price).quantize(TWOPLACES)
        sale_price = Decimal(qty * efs.best_bid.price).quantize(TWOPLACES)
        profit = sale_price - purchase_price
        if profit >= self.profit_size:
            self.notify(efp, efs, profit)
            if self.demo:
                purchase = efp.purchase(qty)
                sale = efs.sale(qty)
                await asyncio.gather(purchase, sale)
                self.fix_profit(
                    efp,
                    efs,
                    qty,
                    purchase_price,
                    sale_price,
                    profit,
                )

                # Имитация уменьшения объема предложения и спроса
                efp.update_best_ask_qty(qty)
                efs.update_best_bid_qty(qty)

    def fix_profit(
        self,
        efp: Exchange,
        efs: Exchange,
        qty: float,
        purchase_price: Decimal,
        sale_price: Decimal,
        profit: Decimal,
    ) -> None:
        self.total_profit += profit
        self.total_deal += 1
        logging.info(
            f"Куплено {qty} {efp.ticker1} по цене {purchase_price} ({efp.best_ask.price}) {efp.ticker2} на бирже {efp.exchange_name}.\n"
            f"          Продано {qty} {efs.ticker1} по цене {sale_price} ({efs.best_bid.price}) {efs.ticker2} на бирже {efs.exchange_name}.\n"
            f"          Выгода от сделки {profit} {efp.ticker2} без учета комиссий.\n"
            f"          Общее количество сделок {self.total_deal}.\n"
            f"          Общая выгода от сделок {self.total_profit} {efp.ticker2} без учета комиссий."
        )

    def notify(
        self,
        efp: Exchange,
        efs: Exchange,
        profit: Decimal,
    ) -> None:
        purchase_msg = f"Покупка: {efp.best_ask.price} {efp.ticker2}"
        sale_msg = f"Продажа: {efs.best_bid.price} {efp.ticker2}"
        msg = (
            f"На бирже {efp.exchange_name} появилось предложение на покупку дешевле чем лучшее предложение на продажу на бирже {efs.exchange_name}.\n"
            f"          {purchase_msg:<30} | {sale_msg:<30}\n"
            f"          Возможная выгода от сделок {profit} {efp.ticker2} без учета комиссий."
        )
        logging.info(msg)