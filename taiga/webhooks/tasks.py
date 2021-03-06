# Copyright (C) 2013 Andrey Antukh <niwi@niwi.be>
# Copyright (C) 2014-2016 Jesús Espino <jespinog@gmail.com>
# Copyright (C) 2014-2016 David Barragán <bameda@dbarragan.com>
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import hmac
import hashlib
import requests
from requests.exceptions import RequestException

from taiga.base.api.renderers import UnicodeJSONRenderer
from taiga.base.utils.db import get_typename_for_model_instance
from taiga.celery import app

from .serializers import (UserStorySerializer, IssueSerializer, TaskSerializer,
                          WikiPageSerializer, MilestoneSerializer,
                          HistoryEntrySerializer)
from .models import WebhookLog


def _serialize(obj):
    content_type = get_typename_for_model_instance(obj)

    if content_type == "userstories.userstory":
        return UserStorySerializer(obj).data
    elif content_type == "issues.issue":
        return IssueSerializer(obj).data
    elif content_type == "tasks.task":
        return TaskSerializer(obj).data
    elif content_type == "wiki.wikipage":
        return WikiPageSerializer(obj).data
    elif content_type == "milestones.milestone":
        return MilestoneSerializer(obj).data
    elif content_type == "history.historyentry":
        return HistoryEntrySerializer(obj).data


def _get_type(obj):
    content_type = get_typename_for_model_instance(obj)
    return content_type.split(".")[1]


def _generate_signature(data, key):
    mac = hmac.new(key.encode("utf-8"), msg=data, digestmod=hashlib.sha1)
    return mac.hexdigest()


def _send_request(webhook_id, url, key, data):
    serialized_data = UnicodeJSONRenderer().render(data)
    signature = _generate_signature(serialized_data, key)
    headers = {
        "X-TAIGA-WEBHOOK-SIGNATURE": signature,
        "Content-Type": "application/json"
    }
    request = requests.Request('POST', url, data=serialized_data, headers=headers)
    prepared_request = request.prepare()

    session = requests.Session()
    try:
        response = session.send(prepared_request)
        webhook_log = WebhookLog.objects.create(webhook_id=webhook_id, url=url,
                                                status=response.status_code,
                                                request_data=data,
                                                request_headers=dict(prepared_request.headers),
                                                response_data=response.content,
                                                response_headers=dict(response.headers),
                                                duration=response.elapsed.total_seconds())
    except RequestException as e:
        webhook_log = WebhookLog.objects.create(webhook_id=webhook_id, url=url, status=0,
                                                request_data=data,
                                                request_headers=dict(prepared_request.headers),
                                                response_data="error-in-request: {}".format(str(e)),
                                                response_headers={},
                                                duration=0)
    session.close()

    ids = [log.id for log in WebhookLog.objects.filter(webhook_id=webhook_id).order_by("-id")[10:]]
    WebhookLog.objects.filter(id__in=ids).delete()
    return webhook_log


@app.task
def change_webhook(webhook_id, url, key, obj, change):
    data = {}
    data['data'] = _serialize(obj)
    data['action'] = "change"
    data['type'] = _get_type(obj)
    data['change'] = _serialize(change)

    return _send_request(webhook_id, url, key, data)


@app.task
def create_webhook(webhook_id, url, key, obj):
    data = {}
    data['data'] = _serialize(obj)
    data['action'] = "create"
    data['type'] = _get_type(obj)

    return _send_request(webhook_id, url, key, data)


@app.task
def delete_webhook(webhook_id, url, key, obj, deleted_date):
    data = {}
    data['data'] = _serialize(obj)
    data['action'] = "delete"
    data['type'] = _get_type(obj)
    data['deleted_date'] = deleted_date

    return _send_request(webhook_id, url, key, data)


@app.task
def resend_webhook(webhook_id, url, key, data):
    return _send_request(webhook_id, url, key, data)


@app.task
def test_webhook(webhook_id, url, key):
    data = {}
    data['data'] = {"test": "test"}
    data['action'] = "test"
    data['type'] = "test"

    return _send_request(webhook_id, url, key, data)
