import atexit
import fcntl

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.mongodb import MongoDBJobStore
from pymongo import MongoClient

from config import MONGO_DB, MONGO_HOST, MONGO_PORT, FLASK_HOST, FLASK_PORT
from db.manager import db_manager


class Scheduler(object):
    mongo = MongoClient(host=MONGO_HOST, port=MONGO_PORT, connect=False)
    task_col = 'apscheduler_jobs'

    # scheduler jobstore
    jobstores = {
        'mongo': MongoDBJobStore(database=MONGO_DB,
                                 collection=task_col,
                                 client=mongo)
    }

    # scheduler instance
    scheduler = BackgroundScheduler(jobstores=jobstores)

    def execute_spider(self, id: str, params: str = None):
        print(f'executing spider {id}')
        print(f'params: {params}')
        self.scheduler.print_jobs(jobstore='mongo')
        query = {}
        if params is not None:
            query['params'] = params
        r = requests.get('http://%s:%s/api/spiders/%s/on_crawl' % (
            FLASK_HOST,
            FLASK_PORT,
            id
        ), query)

    def update(self):
        print('updating...')
        # remove all existing periodic jobs
        self.scheduler.remove_all_jobs()
        self.mongo[MONGO_DB][self.task_col].remove()

        periodical_tasks = db_manager.list('schedules', {})
        for task in periodical_tasks:
            cron = task.get('cron')
            cron_arr = cron.split(' ')
            second = cron_arr[0]
            minute = cron_arr[1]
            hour = cron_arr[2]
            day = cron_arr[3]
            month = cron_arr[4]
            day_of_week = cron_arr[5]
            self.scheduler.add_job(func=self.execute_spider,
                                   args=(str(task['spider_id']), task.get('params'),),
                                   trigger='cron',
                                   jobstore='mongo',
                                   day_of_week=day_of_week,
                                   month=month,
                                   day=day,
                                   hour=hour,
                                   minute=minute,
                                   second=second)
        self.scheduler.print_jobs(jobstore='mongo')
        print(f'state: {self.scheduler.state}')
        print(f'running: {self.scheduler.running}')

    def run(self):
        f = open("scheduler.lock", "wb")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.update()
            self.scheduler.start()
        except:
            pass

        def unlock():
            fcntl.flock(f, fcntl.LOCK_UN)
            f.close()

        atexit.register(unlock)


scheduler = Scheduler()

if __name__ == '__main__':
    scheduler.run()
