"""Preserve Telegram custom emoji in names without treating user text as HTML."""
import json
from html import escape

from store import ShopError


class TitleHTML(str):
    """HTML produced only by the validated title renderer."""


def valid_entities(text, stored):
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except (ValueError, TypeError):
            stored = []
    data = text.encode('utf-16-le')
    result = []
    end = 0
    if not isinstance(stored, list):
        return result
    for entity in sorted((e for e in stored if isinstance(e, dict)), key=lambda e: e.get('offset', 0)):
        if entity.get('type') != 'custom_emoji' or not entity.get('custom_emoji_id'):
            continue
        offset, length = entity.get('offset'), entity.get('length')
        if not isinstance(offset, int) or not isinstance(length, int):
            continue
        start, stop = offset * 2, (offset + length) * 2
        if start < end or not 0 <= start < stop <= len(data):
            continue
        try:
            data[:start].decode('utf-16-le')
            data[start:stop].decode('utf-16-le')
        except UnicodeDecodeError:
            continue
        result.append({'type': 'custom_emoji', 'offset': offset, 'length': length,
                       'custom_emoji_id': str(entity['custom_emoji_id'])})
        end = stop
    return result


def read_title(msg):
    raw = msg.get('text') or ''
    text = raw.strip()
    if not 1 <= len(text) <= 70 or '\n' in text:
        raise ShopError('invalid')
    leading = (len(raw.encode('utf-16-le')) - len(raw.lstrip().encode('utf-16-le'))) // 2
    entities = []
    for entity in valid_entities(raw, msg.get('entities', [])):
        entity = dict(entity, offset=entity['offset'] - leading)
        entities.append(entity)
    return text, json.dumps(valid_entities(text, entities), ensure_ascii=False)


def title_html(row):
    text = row['title']
    stored = row['title_entities'] if 'title_entities' in row.keys() else []
    data = text.encode('utf-16-le')
    parts, cursor = [], 0
    for e in valid_entities(text, stored):
        start, stop = e['offset'] * 2, (e['offset'] + e['length']) * 2
        parts.append(escape(data[cursor:start].decode('utf-16-le')))
        icon = escape(e['custom_emoji_id'], quote=True)
        fallback = escape(data[start:stop].decode('utf-16-le'))
        parts.append(f'<tg-emoji emoji-id="{icon}">{fallback}</tg-emoji>')
        cursor = stop
    parts.append(escape(data[cursor:].decode('utf-16-le')))
    return TitleHTML(''.join(parts))


def button_title(row):
    text = row['title']
    stored = row['title_entities'] if 'title_entities' in row.keys() else []
    entities = valid_entities(text, stored)
    if not entities:
        return text, None
    first = entities[0]
    data = text.encode('utf-16-le')
    start, end = first['offset'] * 2, (first['offset'] + first['length']) * 2
    label = (data[:start] + data[end:]).decode('utf-16-le').strip()
    return label or text, first['custom_emoji_id']
