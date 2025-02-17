# -*- coding: utf-8 -*-
import os
import re
from datetime import datetime

import scrapy
from pymongo import MongoClient
import pytz

from sinastock.items import NewsItem

# 时区
tz = pytz.timezone('Asia/Shanghai')


class SinastockSpiderSpider(scrapy.Spider):
    name = 'sinastock_spider'
    allowed_domains = ['finance.sina.com.cn']
    mongo = MongoClient(
        host=os.environ.get('MONGO_HOST') or 'localhost',
        port=int(os.environ.get('MONGO_PORT') or 27017)
    )
    db = mongo[os.environ.get('MONGO_DB') or 'crawlab_test']
    col = db.get_collection(os.environ.get('CRAWLAB_COLLECTION') or 'stock_news')
    page_num = int(os.environ.get('PAGE_NUM')) or 3

    def start_requests(self):
        col = self.db['stocks']
        for s in col.find({}):
            code, ex = s['ts_code'].split('.')
            for i in range(self.page_num):
                url = f'http://vip.stock.finance.sina.com.cn/corp/view/vCB_AllNewsStock.php?symbol={ex.lower()}{code}&Page={i + 1}'
                yield scrapy.Request(
                    url=url,
                    callback=self.parse,
                    meta={'ts_code': s['ts_code']}
                )

    def parse(self, response):
        for a in response.css('.datelist > ul > a'):
            url = a.css('a::attr("href")').extract_first()
            item = NewsItem(
                title=a.css('a::text').extract_first(),
                url=url,
                source='sina',
                stocks=[response.meta['ts_code']]
            )
            yield scrapy.Request(
                url=url,
                callback=self.parse_detail,
                meta={'item': item}
            )

    def parse_detail(self, response):
        item = response.meta['item']
        text = response.css('#artibody').extract_first()
        pre = re.compile('>(.*?)<')
        text = ''.join(pre.findall(text))
        item['text'] = text.replace('\u3000', '')
        item['ts_str'] = response.css('.date::text').extract_first()
        if item['text'] is None or item['ts_str'] is None:
            pass
        else:
            ts = datetime.strptime(item['ts_str'], '%Y年%m月%d日 %H:%M')
            ts = tz.localize(ts)
            item['ts'] = ts
            yield item
