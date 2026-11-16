"""Saved investigation program, loaded inside the native Monty sandbox."""

async def run_investigation(params):
    import asyncio
    import json
    import re
    import base64
    from datetime import datetime, timedelta, timezone
    from typing import Any

    inputs = params
    state: dict[str, Any] = {"customer":None,"status":"unknown","summary":"Investigation not completed.","likely_cause":"Not yet established.","evidence":[],"next_steps":[],"notion_page_url":None,"verification":{},"blocker":None,"write_action":"none","limitations":[]}

    def native(value):
        return json.loads(json.dumps(value))

    def unwrap(value):
        value = native(value)
        for unused in range(12):
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.startswith('{') or stripped.startswith('['):
                    value = json.loads(stripped)
                    continue
                return value
            if not isinstance(value, dict):
                return value
            if value.get('successful') is False or value.get('success') is False:
                raise ValueError('Application failure: ' + json.dumps(value)[:1500])
            if value.get('error'):
                raise ValueError('Tool error: ' + json.dumps(value['error'])[:1500])
            if 'result' in value and not any(k in value for k in ['rows','documents','messages','results','properties','emailAddress']):
                value = value['result']
                continue
            if 'data' in value and not any(k in value for k in ['rows','documents','messages','results','properties','emailAddress']):
                value = value['data']
                continue
            return value
        raise ValueError('Too many response envelopes')

    def required(value, label):
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Missing required ' + label)
        return value

    def evidence(source, reference, finding):
        state['evidence'].append({'source':source,'reference':required(reference,'evidence reference'),'finding':finding})

    def utc_date(value):
        if isinstance(value, dict):
            value = value.get('$date', value.get('$numberLong'))
            if isinstance(value, dict):
                value = value.get('$numberLong')
        if value is None or value == '':
            return None
        if isinstance(value, (int,float)) or (isinstance(value,str) and value.isdigit()):
            number = float(value)
            if abs(number) > 100000000000:
                number = number / 1000
            return datetime.fromtimestamp(number, timezone.utc)
        if isinstance(value,str):
            result = datetime.fromisoformat(value.replace('Z','+00:00'))
            if result.tzinfo is None:
                raise ValueError('Timestamp lacks timezone: ' + value)
            return result.astimezone(timezone.utc)
        raise ValueError('Unsupported timestamp: ' + json.dumps(value))

    def richtext(parts):
        if not isinstance(parts,list):
            return ''
        return ''.join([p.get('plain_text',p.get('text',{}).get('content','')) for p in parts if isinstance(p,dict)])

    def active(page):
        return not page.get('archived',False) and not page.get('in_trash',False)

    async def find_notion_database():
        found = {}
        for query in [inputs['notion_database_name'], '']:
            cursor = None
            seen = []
            while True:
                response = unwrap(await notion_NOTION_SEARCH_NOTION_PAGE(query=query, filter_value='database', page_size=100, start_cursor=cursor))
                if not isinstance(response,dict) or not isinstance(response.get('results'),list):
                    raise ValueError('Unexpected Notion search schema: ' + json.dumps(response)[:1200])
                for item in response['results']:
                    if active(item) and richtext(item.get('title',[])) == inputs['notion_database_name']:
                        found[required(item.get('id'),'Notion database ID')] = item
                if not response.get('has_more',False):
                    break
                cursor = required(response.get('next_cursor'),'Notion search cursor')
                if cursor in seen:
                    raise ValueError('Repeated Notion search cursor')
                seen.append(cursor)
            if found:
                break
        if len(found) != 1:
            raise ValueError('Expected exactly one active exact-name Notion database; found ' + str(len(found)))
        ids = list(found.keys())
        dbid = ids[0]
        db = unwrap(await notion_NOTION_FETCH_DATABASE(database_id=dbid))
        if not isinstance(db,dict) or db.get('id') != dbid or not active(db):
            raise ValueError('Notion database identity/readback mismatch')
        expected = {'Incident':'title','Status':'select','Customer':'rich_text','Email':'email','Gmail Message ID':'rich_text','Created':'created_time'}
        properties = db.get('properties',{})
        for name, kind in expected.items():
            if properties.get(name,{}).get('type') != kind:
                raise ValueError('Unexpected Notion property type: ' + name)
        options = [o.get('name') for o in properties['Status'].get('select',{}).get('options',[])]
        if not all(s in options for s in ['Open','Investigating','Awaiting intervention','Resolved']):
            raise ValueError('Required Notion status options missing')
        return db

    async def mongo_all(collection, base):
        documents = []
        last = None
        seen = []
        while True:
            filt = native(base)
            if last is not None:
                filt['_id'] = {'$gt':last}
            result = unwrap(await mongo_find(connectionId='preconfigured', database=inputs['mongo_database'], collection=collection, filter=native(filt), limit=100, sort=native({'_id':1})))
            if not isinstance(result,dict) or not isinstance(result.get('documents'),list):
                raise ValueError('Unexpected Mongo response for ' + collection + ': ' + json.dumps(result)[:1000])
            limits = result.get('appliedLimits')
            if not isinstance(limits,list):
                raise ValueError('Mongo appliedLimits missing for ' + collection)
            if limits:
                state['limitations'].append(collection + ' applied limits: ' + json.dumps(limits) + '; continued by native _id')
            batch = result['documents']
            if not batch:
                break
            for doc in batch:
                if '_id' not in doc:
                    raise ValueError('Mongo document missing _id')
                marker = json.dumps(doc['_id'],sort_keys=True)
                if marker in seen:
                    raise ValueError('Mongo pagination repeated an _id in ' + collection)
                seen.append(marker)
                documents.append(doc)
            last = batch[-1]['_id']
        return documents

    def message_id(message):
        return required(message.get('messageId',message.get('id')),'Gmail API message ID')

    def from_address(message):
        sender = message.get('sender',message.get('from'))
        if sender is None:
            headers = message.get('payload',{}).get('headers',[])
            senders = [h.get('value') for h in headers if h.get('name','').lower() == 'from']
            if len(senders) == 1:
                sender = senders[0]
        if not isinstance(sender,str):
            return None
        addresses = re.findall(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',sender)
        if len(addresses) != 1:
            raise ValueError('Missing or ambiguous actual From address')
        return addresses[0].lower()

    def message_time(message):
        value = message.get('messageTimestamp',message.get('internalDate'))
        return utc_date(value)

    def labels(message):
        return message.get('labelIds',message.get('label_ids'))

    async def complete_metadata(message):
        mid = message_id(message)
        if message_time(message) is None or from_address(message) is None or not isinstance(labels(message),list):
            metadata = unwrap(await gmail_GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID(message_id=mid,user_id='me',format='metadata'))
            if not isinstance(metadata,dict) or message_id(metadata) != mid:
                raise ValueError('Gmail metadata ID mismatch')
            message = native(message)
            message.update(metadata)
        if message_time(message) is None or from_address(message) is None or not isinstance(labels(message),list):
            raise ValueError('Cannot verify timestamp, sender or inbox membership for ' + mid)
        return message

    def email_batch(response):
        if not isinstance(response,dict):
            raise ValueError('Unexpected Gmail list response: ' + json.dumps(response)[:1200])
        batch = response.get('messages',response.get('emails'))
        if batch is None and response.get('resultSizeEstimate') == 0:
            return []
        if not isinstance(batch,list):
            raise ValueError('Missing Gmail messages list: ' + json.dumps(response)[:1200])
        return batch

    async def latest_email():
        query = 'from:"' + inputs['gmail_sender'] + '"'
        initial = unwrap(await gmail_GMAIL_FETCH_EMAILS(query=query,user_id='me',label_ids=['INBOX'],include_spam_trash=False,ids_only=False,verbose=False,include_payload=False,max_results=1))
        first = email_batch(initial)
        candidates = {}
        if first:
            candidate = await complete_metadata(first[0])
            candidates[message_id(candidate)] = candidate
            date_before = message_time(candidate) - timedelta(days=1)
            query = query + ' after:' + date_before.strftime('%Y/%m/%d')
        cursor = None
        seen = []
        while True:
            response = unwrap(await gmail_GMAIL_FETCH_EMAILS(query=query,user_id='me',label_ids=['INBOX'],include_spam_trash=False,ids_only=False,verbose=False,include_payload=False,max_results=100,page_token=cursor))
            batch = email_batch(response)
            for item in batch:
                item = await complete_metadata(item)
                candidates[message_id(item)] = item
            cursor = response.get('nextPageToken',response.get('next_page_token'))
            if not cursor:
                break
            if cursor in seen:
                raise ValueError('Repeated Gmail pagination token')
            seen.append(cursor)
        selected = None
        selected_key = None
        for mid, item in candidates.items():
            if from_address(item) == inputs['gmail_sender'].lower() and 'INBOX' in labels(item):
                key = (message_time(item).timestamp(),mid)
                if selected_key is None or key > selected_key:
                    selected_key = key
                    selected = item
        if selected is None:
            return None
        mid = message_id(selected)
        full = unwrap(await gmail_GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID(message_id=mid,user_id='me',format='full'))
        if not isinstance(full,dict) or message_id(full) != mid or from_address(full) != inputs['gmail_sender'].lower():
            raise ValueError('Selected full Gmail message ID/From mismatch')
        if isinstance(labels(full),list) and 'INBOX' not in labels(full):
            raise ValueError('Selected message no longer in INBOX')
        content = full.get('messageText',full.get('text'))
        if not isinstance(content,str) or not content.strip():
            content = full.get('body')
        if not isinstance(content,str) or not content.strip():
            parts = [full.get('payload',{})]
            texts = []
            while parts:
                part = parts.pop(0)
                parts.extend(part.get('parts',[]))
                body = part.get('body',{}).get('data')
                if body and part.get('mimeType') == 'text/plain':
                    texts.append(base64.urlsafe_b64decode(body + '=' * ((4-len(body)%4)%4)).decode('utf-8'))
            content = '\n'.join(texts)
        required(content,'full Gmail message content')
        full['verified_content'] = content
        full['verified_received_utc'] = message_time(selected).isoformat()
        return full

    async def query_incident(dbid, mid):
        cursor = None
        seen = []
        matches = {}
        while True:
            response = unwrap(await notion_NOTION_QUERY_DATABASE_WITH_FILTER(database_id=dbid,filter=native({'property':'Gmail Message ID','rich_text':{'equals':mid}}),page_size=100,start_cursor=cursor))
            if not isinstance(response,dict) or not isinstance(response.get('results'),list):
                raise ValueError('Unexpected Notion incident query response: ' + json.dumps(response)[:1000])
            for page in response['results']:
                if active(page):
                    matches[required(page.get('id'),'Notion incident page ID')] = page
            if not response.get('has_more',False):
                break
            cursor = required(response.get('next_cursor'),'Notion incident query cursor')
            if cursor in seen:
                raise ValueError('Repeated incident query cursor')
            seen.append(cursor)
        if len(matches) > 1:
            raise ValueError('Duplicate active incidents for selected Gmail message')
        pages = list(matches.values())
        return pages

    def check_page(page, dbid, mid, sender, target=None):
        if not isinstance(page,dict) or not active(page):
            raise ValueError('Notion incident is inactive or invalid')
        properties = page.get('properties',{})
        if richtext(properties.get('Gmail Message ID',{}).get('rich_text',[])) != mid:
            raise ValueError('Notion message identity mismatch')
        if properties.get('Email',{}).get('email','').lower() != sender.lower():
            raise ValueError('Notion sender identity mismatch')
        parent = page.get('parent',{})
        if parent.get('database_id') != dbid:
            raise ValueError('Notion parent database mismatch')
        if target is not None and properties.get('Status',{}).get('select',{}).get('name') != target:
            raise ValueError('Notion target status mismatch')

    def object_ref(value):
        if isinstance(value,dict) and isinstance(value.get('$oid'),str):
            return value['$oid']
        return required(value,'Mongo document identifier')

    def sql_literal(value):
        return "'" + required(value,'SQL value').replace("'","''") + "'"

    async def investigate():
        initial = await asyncio.gather(gmail_GMAIL_GET_PROFILE(user_id='me'),logfire_query_schema_reference(intent='Investigate the selected customer order incident using attempt traces.'),find_notion_database())
        profile = unwrap(initial[0])
        if not isinstance(profile,dict) or profile.get('emailAddress','').lower() != inputs['mailbox'].lower():
            raise ValueError('Authenticated Gmail mailbox does not match requested mailbox')
        state['verification']['mailbox'] = profile['emailAddress']
        schema = unwrap(initial[1])
        if not isinstance(schema,str):
            raise ValueError('Unexpected Logfire schema response: ' + json.dumps(schema)[:1200])
        db = initial[2]
        dbid = required(db.get('id'),'Notion database ID')
        state['verification']['notion_database_id'] = dbid
        email = await latest_email()
        if email is None:
            state['summary'] = 'No matching inbox message after complete paginated sender search.'
            state['likely_cause'] = 'No incident email was available to investigate.'
            state['verification']['complete'] = True
            return
        mid = message_id(email)
        sender = required(from_address(email),'observed email sender')
        state['verification']['gmail_message_id'] = mid
        evidence('gmail',mid,'Latest verified inbox message from ' + sender + '; received ' + email['verified_received_utc'] + '; subject: ' + email.get('subject',''))
        customers = await mongo_all('customers',{'email':sender,'scenario':inputs['scenario']})
        if len(customers) != 1:
            raise ValueError('Expected exactly one Mongo customer matching observed sender and scenario; found ' + str(len(customers)))
        customer = customers[0]
        cid = customer['_id']
        customer_ref = object_ref(cid)
        customer_name = customer.get('name',customer.get('company_name',customer.get('company',sender)))
        if not isinstance(customer_name,str) or not customer_name:
            customer_name = sender
        state['customer'] = customer_name
        evidence('mongo',customer_ref,'Unique customer matched observed sender ' + sender + ' and scenario ' + inputs['scenario'] + '.')
        collection_results = await asyncio.gather(mongo_all('orders',{'customer_id':cid,'scenario':inputs['scenario']}),mongo_all('sync_attempts',{'customer_id':cid,'scenario':inputs['scenario']}))
        orders = collection_results[0]
        attempts = collection_results[1]
        state['verification']['orders_complete'] = True
        state['verification']['attempts_complete'] = True
        if not attempts:
            raise ValueError('No historical sync attempts available; cannot query actual attempt traces')
        # Infer the current order state only from fields actually returned.
        order_states = []
        for order in orders:
            observed = order.get('sync_status',order.get('status'))
            if not isinstance(observed,str):
                raise ValueError('Missing current order state: ' + json.dumps(order)[:1200])
            order_states.append(observed.lower())
        failed = [orders[i] for i in range(len(orders)) if order_states[i] == 'failed']
        if failed:
            status = 'ongoing'
        elif orders and all(value == 'synced' for value in order_states):
            status = 'recovered'
        else:
            status = 'unknown'
        state['status'] = status
        state_counts = {}
        for value in order_states:
            state_counts[value] = state_counts.get(value,0) + 1
        for order in orders:
            ref = object_ref(order['_id'])
            evidence('mongo',ref,'Current order ' + str(order.get('order_id',order.get('external_order_id',ref))) + ': ' + str(order.get('sync_status',order.get('status'))) + (('; error_code=' + str(order['error_code'])) if order.get('error_code') else ''))
        trace_ids = []
        dates = []
        error_codes = []
        attempt_orders = []
        for attempt in attempts:
            trace = required(attempt.get('trace_id'),'attempt trace_id')
            if trace not in trace_ids:
                trace_ids.append(trace)
            started = utc_date(attempt.get('started_at'))
            finished = utc_date(attempt.get('finished_at'))
            if started is None:
                raise ValueError('Attempt missing started_at: ' + json.dumps(attempt)[:1000])
            dates.append(started)
            if finished is not None:
                dates.append(finished)
            code = attempt.get('error_code')
            if code and code not in error_codes:
                error_codes.append(code)
            oid = attempt.get('order_id')
            if oid is not None:
                marker = json.dumps(oid,sort_keys=True)
                if marker not in attempt_orders:
                    attempt_orders.append(marker)
            evidence('mongo',object_ref(attempt['_id']),'Historical attempt: status=' + str(attempt.get('status',attempt.get('result','not provided'))) + '; error_code=' + str(code) + '; trace_id=' + trace + '; started_at=' + started.isoformat())
        # Validate actual records columns before building SQL. Attribute keys remain JSON, not invented columns.
        match = re.search(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:[\w]+\.)?["`]?records["`]?\s*\((.*?)\)\s*;',schema,re.I|re.S)
        record_schema = match.group(1) if match else schema
        preferred = ['start_timestamp','trace_id','span_id','service_name','span_name','message','level','is_exception','exception_type','exception_message','attributes']
        columns = [col for col in preferred if re.search(r'\b' + col + r'\b',record_schema)]
        for col in ['start_timestamp','trace_id','service_name','attributes']:
            if col not in columns:
                raise ValueError('Logfire records schema missing required column ' + col + ': ' + schema[:1800])
        start = min(dates).replace(hour=0,minute=0,second=0,microsecond=0)
        end = max(dates).replace(hour=0,minute=0,second=0,microsecond=0) + timedelta(days=1)
        windows = []
        position = start
        while position < end:
            finish = min(position + timedelta(days=14),end)
            windows.append((position.isoformat(),finish.isoformat()))
            position = finish
        query = 'SELECT ' + ', '.join(columns) + ' FROM records WHERE service_name = ' + sql_literal('orders-sync-demo') + ' AND trace_id IN (' + ', '.join([sql_literal(t) for t in trace_ids]) + ') ORDER BY start_timestamp ASC LIMIT 1000'
        trace_rows = []
        for window in windows:
            result = unwrap(await logfire_query_run(project=inputs['logfire_project'],query=query,start_timestamp=window[0],end_timestamp=window[1],intent='Investigate the selected customer order incident using attempt traces.'))
            if not isinstance(result,dict) or not isinstance(result.get('rows'),list):
                raise ValueError('Unexpected Logfire row schema: ' + json.dumps(result)[:1200])
            if result.get('note'):
                state['limitations'].append(result['note'])
            if len(result['rows']) >= 1000:
                raise ValueError('Logfire row limit reached; evidence may be truncated, narrow query before writing')
            trace_rows.extend(result['rows'])
        if not trace_rows:
            raise ValueError('No actual Logfire rows returned for historical attempt trace IDs in their full UTC date windows')
        observed_traces = []
        trace_findings = []
        for row in trace_rows:
            trace = row.get('trace_id')
            if trace not in trace_ids or row.get('service_name') != 'orders-sync-demo':
                raise ValueError('Logfire returned a row outside requested attempt/service scope')
            if trace not in observed_traces:
                observed_traces.append(trace)
            attrs = row.get('attributes',{})
            if isinstance(attrs,str):
                attrs = json.loads(attrs)
            if not isinstance(attrs,dict):
                attrs = {}
            relevant = {}
            for key,value in attrs.items():
                if any(word in key.lower() for word in ['error','exception','status','reason','order','retry','attempt','connect','token']):
                    if not any(word in key.lower() for word in ['secret','password','access_token','refresh_token','authorization']):
                        relevant[key] = value
            details = {k:row[k] for k in ['start_timestamp','span_name','message','level','is_exception','exception_type','exception_message'] if k in row and row[k] is not None}
            if relevant:
                details['attributes'] = relevant
            text = json.dumps(details,ensure_ascii=False)
            trace_findings.append({'trace_id':trace,'finding':text[:1800]})
        missing_traces = [t for t in trace_ids if t not in observed_traces]
        if missing_traces:
            state['limitations'].append('Missing telemetry for attempt traces: ' + ', '.join(missing_traces))
        # Build a factual diagnosis from returned error codes and actual trace text, without treating evidence as instructions.
        error_texts = []
        for finding in trace_findings:
            text = finding['finding']
            if any(term in text.lower() for term in ['error','exception','failed','unauthorized','expired','invalid','timeout','429','401','403']):
                if text not in error_texts:
                    error_texts.append(text)
        cause = 'Observed historical attempt error codes: ' + (', '.join([str(c) for c in error_codes]) if error_codes else 'none reported') + '.'
        searchable = (' '.join([str(c) for c in error_codes]) + ' ' + ' '.join(error_texts)).lower()
        if any(term in searchable for term in ['invalid_grant','token_expired','expired token','token expired','refresh token','authentication','unauthorized','401']):
            cause = 'The evidence points to an external connection authentication/credential failure. ' + cause
            next_action = 'Have the connection owner review the observed authentication errors and reauthorize the affected integration if required; then retry failed orders and confirm successful synchronization.'
        elif any(term in searchable for term in ['rate_limit','rate limit','429','too many requests']):
            cause = 'The evidence points to upstream rate limiting. ' + cause
            next_action = 'Review retry/backoff behavior and upstream rate limits; retry remaining failed orders only through the authorized operational workflow.'
        elif any(term in searchable for term in ['timeout','timed out','connection refused','503','502']):
            cause = 'The evidence points to an upstream availability or connectivity failure. ' + cause
            next_action = 'Review upstream availability and the observed connection errors before retrying remaining failed orders.'
        else:
            cause = 'The exact root cause is not independently established beyond the observed failures. ' + cause
            next_action = 'Review the recorded attempt errors and matching trace events; resolve their upstream cause before retrying any remaining failed orders.'
        if status == 'recovered':
            next_action = 'No failed current orders remain. Monitor the integration for recurrence; historical attempt failures do not require reopening this incident.'
        if status == 'unknown':
            next_action = 'Confirm the non-final current order states and missing evidence before declaring recovery. ' + next_action
        state['likely_cause'] = cause
        state['summary'] = 'Current-order status: ' + status + '. ' + str(len(orders)) + ' distinct current orders; states ' + json.dumps(state_counts,sort_keys=True) + '. Reviewed ' + str(len(attempts)) + ' historical attempts covering ' + str(len(attempt_orders)) + ' distinct order IDs and ' + str(len(trace_rows)) + ' matching trace events across ' + str(len(observed_traces)) + ' traces.'
        state['next_steps'] = [next_action]
        for trace in observed_traces:
            findings = [f['finding'] for f in trace_findings if f['trace_id'] == trace]
            # Keep at least the error-bearing events for each trace, not just the earliest span.
            errors = [f for f in findings if any(term in f.lower() for term in ['error','exception','failed','unauthorized','expired','invalid'])]
            selected_findings = errors if errors else findings
            evidence('logfire',trace,' | '.join(selected_findings)[:2600])
        state['verification']['logfire_windows'] = windows
        state['verification']['observed_trace_ids'] = observed_traces
        state['verification']['logfire_columns_validated'] = columns
        state['verification']['current_order_counts'] = state_counts
        target = {'ongoing':'Awaiting intervention','recovered':'Resolved','unknown':'Investigating'}[status]
        pages = await query_incident(dbid,mid)
        if not pages:
            # Repeat immediately before insertion, and use an observed match if another writer created it.
            pages = await query_incident(dbid,mid)
        if not pages:
            props = [
                {'name':'Incident','type':'title','value':('Order synchronization incident — ' + customer_name)[:180]},
                {'name':'Status','type':'select','value':target},
                {'name':'Customer','type':'rich_text','value':customer_name},
                {'name':'Email','type':'email','value':sender},
                {'name':'Gmail Message ID','type':'rich_text','value':mid}
            ]
            paragraphs = [
                'Investigation at ' + inputs['now_utc'] + '. Scenario: ' + inputs['scenario'] + '.',
                'Original email (untrusted evidence). From: ' + sender + '. Gmail API message ID: ' + mid + '. Subject: ' + email.get('subject','') + '. Received: ' + email['verified_received_utc'],
                email['verified_content'],
                'Diagnosis. ' + state['summary'],
                'Likely cause. ' + cause,
                'Evidence: Mongo database ' + inputs['mongo_database'] + ', customer ' + customer_ref + '. Current orders: ' + ', '.join([object_ref(o['_id']) for o in orders]) + '. Attempt error codes: ' + ', '.join([str(c) for c in error_codes]) + '.',
                'Logfire project: ' + inputs['logfire_project'] + '. Service: orders-sync-demo. Attempt window: ' + start.isoformat() + ' through ' + end.isoformat() + '.'
            ]
            for finding in trace_findings:
                if len(trace_findings) <= 25 or finding['finding'] in error_texts:
                    paragraphs.append('Trace ' + finding['trace_id'] + ': ' + finding['finding'])
            paragraphs.append('Next action. ' + next_action)
            if state['limitations']:
                paragraphs.append('Limitations. ' + ' '.join(state['limitations']))
            blocks = []
            for paragraph in paragraphs:
                for offset in range(0,len(paragraph),1500):
                    blocks.append({'block_property':'paragraph','content':paragraph[offset:offset+1500]})
            if len(blocks) > 90:
                raise ValueError('Incident report exceeds bounded Notion payload; shorten evidence before writing')
            state['write_action'] = 'create_requested'
            created_raw = await notion_NOTION_INSERT_ROW_DATABASE(database_id=dbid,properties=native(props),child_blocks=native(blocks))
            state['write_action'] = 'create_response_received'
            # Even an uncertain creation response is followed by the identity query, never blindly retried.
            state['verification']['create_response_received'] = created_raw is not None
            pages = await query_incident(dbid,mid)
            if len(pages) != 1:
                raise ValueError('Creation not confirmed by duplicate query; no blind retry')
            pid = required(pages[0].get('id'),'created page ID')
            state['write_action'] = 'created'
        else:
            pid = required(pages[0].get('id'),'existing page ID')
            current = unwrap(await notion_NOTION_FETCH_ROW(page_id=pid))
            check_page(current,dbid,mid,sender)
            if current.get('properties',{}).get('Status',{}).get('select',{}).get('name') != target:
                state['write_action'] = 'update_requested'
                updated = unwrap(await notion_NOTION_UPDATE_PAGE(page_id=pid,properties=native({'Status':{'select':{'name':target}}})))
                state['write_action'] = 'updated_status_only'
            else:
                state['write_action'] = 'reused_without_changes'
        page = unwrap(await notion_NOTION_FETCH_ROW(page_id=pid))
        if page.get('id') != pid:
            raise ValueError('Notion readback page ID mismatch')
        check_page(page,dbid,mid,sender,target)
        url = required(page.get('url'),'verified Notion page URL')
        state['notion_page_url'] = url
        state['verification']['notion_page_id'] = pid
        state['verification']['notion_status'] = target
        state['verification']['notion_identity_active_status_url'] = True
        state['verification']['complete'] = True
        evidence('notion',url,'Readback verified exact Gmail API message ID, sender email, parent database, active state and status ' + target + '; action: ' + state['write_action'] + '.')

    try:
        await investigate()
    except Exception as exc:
        state['blocker'] = str(exc)
        state['next_steps'].append('Resolve investigation blocker: ' + str(exc))
        state['verification']['complete'] = False
    return state
