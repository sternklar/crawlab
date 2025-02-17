import json
import os
import sys
from time import time

from flask_csv import send_csv

try:
    from _signal import SIGKILL
except ImportError:
    pass

import requests
from bson import ObjectId
from tasks.celery import celery_app

from constants.task import TaskStatus
from db.manager import db_manager
from routes.base import BaseApi
from utils import jsonify
from utils.spider import get_spider_col_fields


class TaskApi(BaseApi):
    # collection name
    col_name = 'tasks'

    arguments = (
        ('deploy_id', str),
        ('file_path', str)
    )

    def get(self, id: str = None, action: str = None):
        """
        GET method of TaskAPI.
        :param id: item id
        :param action: action
        """
        # action by id
        if action is not None:
            if not hasattr(self, action):
                return {
                           'status': 'ok',
                           'code': 400,
                           'error': 'action "%s" invalid' % action
                       }, 400
            return getattr(self, action)(id)

        elif id is not None:
            task = db_manager.get(col_name=self.col_name, id=id)
            spider = db_manager.get(col_name='spiders', id=str(task['spider_id']))

            # spider
            task['num_results'] = 0
            if spider:
                task['spider_name'] = spider['name']
                if spider.get('col'):
                    col = spider.get('col')
                    num_results = db_manager.count(col, {'task_id': task['_id']})
                    task['num_results'] = num_results

            # duration
            if task.get('finish_ts') is not None:
                task['duration'] = (task['finish_ts'] - task['create_ts']).total_seconds()
                task['avg_num_results'] = round(task['num_results'] / task['duration'], 1)

            try:
                with open(task['log_file_path']) as f:
                    task['log'] = f.read()
            except Exception as err:
                task['log'] = ''
            return jsonify(task)

        # list tasks
        args = self.parser.parse_args()
        page_size = args.get('page_size') or 10
        page_num = args.get('page_num') or 1
        filter_str = args.get('filter')
        filter_ = {}
        if filter_str is not None:
            filter_ = json.loads(filter_str)
            if filter_.get('spider_id'):
                filter_['spider_id'] = ObjectId(filter_['spider_id'])
        tasks = db_manager.list(col_name=self.col_name, cond=filter_, limit=page_size, skip=page_size * (page_num - 1),
                                sort_key='create_ts')
        items = []
        for task in tasks:
            # get spider
            _spider = db_manager.get(col_name='spiders', id=str(task['spider_id']))

            # status
            if task.get('status') is None:
                task['status'] = TaskStatus.UNAVAILABLE

            # spider
            task['num_results'] = 0
            if _spider:
                # spider name
                task['spider_name'] = _spider['name']

                # number of results
                if _spider.get('col'):
                    col = _spider.get('col')
                    num_results = db_manager.count(col, {'task_id': task['_id']})
                    task['num_results'] = num_results

            # duration
            if task.get('finish_ts') is not None:
                task['duration'] = (task['finish_ts'] - task['create_ts']).total_seconds()
                task['avg_num_results'] = round(task['num_results'] / task['duration'], 1)

            items.append(task)

        return {
            'status': 'ok',
            'total_count': db_manager.count('tasks', filter_),
            'page_num': page_num,
            'page_size': page_size,
            'items': jsonify(items)
        }

    def on_get_log(self, id: (str, ObjectId)) -> (dict, tuple):
        """
        Get the log of given task_id
        :param id: task_id
        """
        try:
            task = db_manager.get(col_name=self.col_name, id=id)
            with open(task['log_file_path']) as f:
                log = f.read()
                return {
                    'status': 'ok',
                    'log': log
                }
        except Exception as err:
            return {
                       'code': 500,
                       'status': 'ok',
                       'error': str(err)
                   }, 500

    def get_log(self, id: (str, ObjectId)) -> (dict, tuple):
        """
        Submit an HTTP request to fetch log from the node of a given task.
        :param id: task_id
        :return:
        """
        task = db_manager.get(col_name=self.col_name, id=id)
        node = db_manager.get(col_name='nodes', id=task['node_id'])
        r = requests.get('http://%s:%s/api/tasks/%s/on_get_log' % (
            node['ip'],
            node['port'],
            id
        ))
        if r.status_code == 200:
            data = json.loads(r.content.decode('utf-8'))
            return {
                'status': 'ok',
                'log': data.get('log')
            }
        else:
            data = json.loads(r.content)
            return {
                       'code': 500,
                       'status': 'ok',
                       'error': data['error']
                   }, 500

    def get_results(self, id: str) -> (dict, tuple):
        """
        Get a list of results crawled in a given task.
        :param id: task_id
        """
        args = self.parser.parse_args()
        page_size = args.get('page_size') or 10
        page_num = args.get('page_num') or 1

        task = db_manager.get('tasks', id=id)
        spider = db_manager.get('spiders', id=task['spider_id'])
        col_name = spider.get('col')
        if not col_name:
            return []
        fields = get_spider_col_fields(col_name)
        items = db_manager.list(col_name, {'task_id': id}, skip=page_size * (page_num - 1), limit=page_size)
        return {
            'status': 'ok',
            'fields': jsonify(fields),
            'total_count': db_manager.count(col_name, {'task_id': id}),
            'page_num': page_num,
            'page_size': page_size,
            'items': jsonify(items)
        }

    def stop(self, id):
        """
        Send stop signal to a specific node
        :param id: task_id
        """
        task = db_manager.get('tasks', id=id)
        node = db_manager.get('nodes', id=task['node_id'])
        r = requests.get('http://%s:%s/api/tasks/%s/on_stop' % (
            node['ip'],
            node['port'],
            id
        ))
        if r.status_code == 200:
            return {
                'status': 'ok',
                'message': 'success'
            }
        else:
            data = json.loads(r.content)
            return {
                       'code': 500,
                       'status': 'ok',
                       'error': data['error']
                   }, 500

    def on_stop(self, id):
        """
        Stop the task in progress.
        :param id:
        :return:
        """
        task = db_manager.get('tasks', id=id)
        celery_app.control.revoke(id, terminate=True)
        db_manager.update_one('tasks', id=id, values={
            'status': TaskStatus.REVOKED
        })

        # kill process
        if task.get('pid'):
            pid = task.get('pid')
            if 'win32' in sys.platform:
                os.popen('taskkill /pid:' + str(pid))
            else:
                # unix system
                os.kill(pid, SIGKILL)

        return {
            'id': id,
            'status': 'ok',
        }

    def download_results(self, id: str):
        task = db_manager.get('tasks', id=id)
        spider = db_manager.get('spiders', id=task['spider_id'])
        col_name = spider.get('col')
        if not col_name:
            return send_csv([], f'results_{col_name}_{round(time())}.csv')
        items = db_manager.list(col_name, {'task_id': id}, limit=999999999)
        fields = get_spider_col_fields(col_name, task_id=id, limit=999999999)
        return send_csv(items,
                        filename=f'results_{col_name}_{round(time())}.csv',
                        fields=fields,
                        encoding='utf-8')
