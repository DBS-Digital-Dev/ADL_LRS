from __future__ import absolute_import

import urllib2
import json

from celery import shared_task
from celery.utils.log import get_task_logger

from django.conf import settings
from django.db.models import Q

from lrs.util import StatementValidator as SV

celery_logger = get_task_logger('celery-task')

@shared_task
def check_activity_metadata(stmts):
    from lrs.models import Activity
    activity_ids = list(Activity.objects.filter(object_of_statement__statement_id__in=stmts).values_list('activity_id', flat=True).distinct())
    [get_activity_metadata(a_id) for a_id in activity_ids]

@shared_task
def void_statements(stmts):
    from lrs.models import Statement    
    try:
        Statement.objects.filter(statement_id__in=stmts).update(voided=True)
    except Exception, e:
        celery_logger.exception("Voiding Statement Error: " + e.message)

@shared_task
def check_statement_hooks(stmt_ids):
    from lrs.models import Agent, Hook, Statement
    hooks = Hook.objects.all()
    for h in hooks:
        filters = h.filters
        config = h.config
        if 'endpoint' not in config:
            celery_logger.exception("Endpoint not in hook %s" % str(h.name))
        secret = str(config['secret']) if 'secret' in config else None


        

        # if 'and' in filters and isinstance(filters['and'], list):
        #     agent_andQ = Q()
        #     for agent_data in filters['and']:
        #         agent = Agent.objects.retrieve_or_create(**agent_data)[0]
        #         agent_andQ = agent_andQ & Q(actor=agent)

        # if 'or' in filters and isinstance(filters['or'], list):
        #     agent_orQ = Q()
        #     for agent_data in filters['or']:
        #         agent = Agent.objects.retrieve_or_create(**agent_data)[0]
        #         agent_orQ = agent_orQ | Q(actor=agent)


        # found = Statement.objects.filter(agent_andQ & agent_orQ & Q(statement_id__in=stmt_ids))
        found = Statement.objects.all()[:9]
        if found:
            data = found.values_list('full_statement', flat=True)
            req = urllib2.Request(str(h.config['endpoint']))
            req.add_header('Content-Type', 'application/json')
            if secret:
                req.add_header('X-XAPI-Signature', secret)
            urllib2.urlopen(req, json.dumps(data))

# Retrieve JSON data from ID
def get_activity_metadata(act_id):
    from lrs.models import Activity
    act_url_data = {}
    # See if id resolves
    try:
        req = urllib2.Request(act_id)
        req.add_header('Accept', 'application/json, */*')
        act_resp = urllib2.urlopen(req, timeout=settings.ACTIVITY_ID_RESOLVE_TIMEOUT)
    except Exception:
        # Doesn't resolve-hopefully data is in payload
        pass
    else:
        # If it resolves then try parsing JSON from it
        try:
            act_url_data = json.loads(act_resp.read())
        except Exception:
            # Resolves but no data to retrieve - this is OK
            pass

        # If there was data from the URL
        if act_url_data:
            valid_url_data = True
            # Have to validate new data given from URL
            try:
                fake_activity = {"id": act_id, "definition": act_url_data}
                validator = SV.StatementValidator()
                validator.validate_activity(fake_activity)
            except Exception, e:
                valid_url_data = False
                celery_logger.exception("Activity Metadata Retrieval Error: " + e.message)

            if valid_url_data:
                update_activity_definition(fake_activity)

def update_activity_definition(act):
    from lrs.models import Activity
    # Try to get activity by id
    try:
        activity = Activity.objects.get(activity_id=act['id'])
    except Activity.DoesNotExist:
        # Could not exist yet
        pass
    # If the activity already exists in the db
    else:
        # If there is a name in the IRI act definition add it to what already exists
        if 'name'in act['definition']:
            activity.activity_definition_name = dict(activity.activity_definition_name.items() + act['definition']['name'].items())
        # If there is a description in the IRI act definition add it to what already exists
        if 'description' in act['definition']:
            activity.activity_definition_description = dict(activity.activity_definition_description.items() + act['definition']['description'].items())

        activity.activity_definition_type = act['definition'].get('type', '')
        activity.activity_definition_moreInfo = act['definition'].get('moreInfo', '')
        activity.activity_definition_interactionType = act['definition'].get('interactionType', '')
        activity.activity_definition_extensions = act['definition'].get('extensions', {})
        activity.activity_definition_crpanswers = act['definition'].get('correctResponsesPattern', {})
        activity.activity_definition_choices = act['definition'].get('choices', {})
        activity.activity_definition_sources = act['definition'].get('source', {}) 
        activity.activity_definition_targets = act['definition'].get('target', {})
        activity.activity_definition_steps = act['definition'].get('steps', {})
        activity.activity_definition_scales = act['definition'].get('scale', {})
        activity.save()