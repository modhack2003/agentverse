"""Bound shared context without dropping the current input or task identity."""
import json


def bounded_records(rows, keys, budget=16000, field_limit=4000, newest_last=False):
    result = []
    for row in reversed(rows) if newest_last else rows:
        item = {key: row[key] for key in keys if key in row}
        for key, value in item.items():
            if isinstance(value, str) and len(value) > field_limit:
                item[key] = value[:field_limit] + '\n[Context truncated; consult the shared record for details.]'
        size = len(json.dumps(item, ensure_ascii=False))
        if size > budget:
            break
        result.append(item)
        budget -= size
    return list(reversed(result)) if newest_last else result


def chat_history(rows):
    return bounded_records(rows, ('id', 'sender_id', 'recipient_id', 'channel', 'content', 'reply_to_id', 'created_at'),
                           budget=32000, newest_last=True)


def shared_memory(rows):
    return bounded_records(rows, ('id', 'title', 'content', 'version', 'author_id'))


def team_context(rows):
    return bounded_records(rows, ('id', 'name', 'kind', 'description', 'capabilities', 'limitations', 'status', 'online'),
                           budget=20000, field_limit=1000)
