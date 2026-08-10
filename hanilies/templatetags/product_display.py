import re
from collections import namedtuple

from django import template
from django.core.files.storage import default_storage


register = template.Library()
ProductDetail = namedtuple('ProductDetail', ['label', 'value'])
PackageHighlight = namedtuple('PackageHighlight', ['label', 'value'])
PackageInclusion = namedtuple('PackageInclusion', ['display_label', 'image_url'])

_DETAIL_LABELS = {
    'primary_color': 'Color',
    'flavor': 'Flavor',
    'size': 'Size',
    'theme': 'Theme',
    'tier_count': 'Tiers',
}
_DETAIL_PATTERN = re.compile(
    r'(?P<key>primary_color|flavor|size|theme|tier_count)\s*=\s*'
    r'(?P<value>"[^"]*"|\'[^\']*\'|.*?)(?=\s+(?:primary_color|flavor|size|theme|tier_count)\s*=|$)',
    re.IGNORECASE,
)
_TIER_PATTERN = re.compile(r'(?P<count>\d+)\s*(?:-|\s)?\s*tier', re.IGNORECASE)
_CUPCAKE_PATTERN = re.compile(r'(?P<count>\d+)\s*cupcakes?', re.IGNORECASE)
_SETUP_PATTERN = re.compile(r'\b(?:event|table|cake table|stage|backdrop|setup|set-up|decoration)\b', re.IGNORECASE)


def _read_value(source, key, default=''):
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _format_inclusion_label(item):
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return str(item).strip()

    label = str(
        item.get('display_label')
        or item.get('label')
        or item.get('name')
        or item.get('value')
        or ''
    ).strip()
    try:
        quantity = int(item.get('quantity') or 1)
    except (TypeError, ValueError):
        quantity = 1

    if label and quantity > 1 and not label.lower().startswith(f'{quantity} x'):
        return f'{quantity} x {label}'
    return label


def _image_url_from_item(item):
    if not isinstance(item, dict):
        return ''
    if item.get('image_url'):
        return str(item['image_url'])
    if item.get('image'):
        return default_storage.url(item['image'])
    return ''


def _raw_package_inclusions(package):
    explicit = _read_value(package, 'package_inclusion_items', None)
    if explicit:
        return list(explicit)

    customization_options = _read_value(package, 'customization_options', {}) or {}
    if isinstance(customization_options, dict):
        included_items = customization_options.get('included_items') or []
        if included_items:
            return list(included_items)

    fallback_text = _read_value(package, 'included_items', '') or _read_value(package, 'features', '')
    if fallback_text:
        return [line.strip() for line in str(fallback_text).splitlines() if line.strip()]
    return []


@register.filter
def product_details(description):
    """Return labeled product details parsed from storefront description text."""
    if not description:
        return []

    values_by_key = {}
    for match in _DETAIL_PATTERN.finditer(str(description)):
        key = match.group('key').lower()
        if key in values_by_key:
            continue

        value = match.group('value').strip().strip('"\'').strip()
        if value:
            values_by_key[key] = value

    return [
        ProductDetail(label, values_by_key[key])
        for key, label in _DETAIL_LABELS.items()
        if key in values_by_key
    ]


@register.filter
def package_inclusions(package):
    """Return display-ready package inclusions from already available product data."""
    inclusions = []
    for item in _raw_package_inclusions(package):
        label = _format_inclusion_label(item)
        if label:
            inclusions.append(PackageInclusion(label, _image_url_from_item(item)))
    return inclusions


@register.filter
def remaining_count(items, visible_count=3):
    try:
        visible_count = int(visible_count)
    except (TypeError, ValueError):
        visible_count = 3
    return max(len(items or []) - visible_count, 0)


@register.filter
def package_highlights(package):
    """Return compact package highlights from existing display text and inclusions."""
    description = str(_read_value(package, 'description', '') or '')
    inclusions = package_inclusions(package)
    searchable_parts = [description]
    searchable_parts.extend(item.display_label for item in inclusions)
    searchable_text = ' '.join(searchable_parts)

    highlights = []
    tier_match = _TIER_PATTERN.search(searchable_text)
    if tier_match:
        count = tier_match.group('count')
        highlights.append(PackageHighlight('Cake', f'{count} tier' if count == '1' else f'{count} tiers'))

    cupcake_match = _CUPCAKE_PATTERN.search(searchable_text)
    if cupcake_match:
        highlights.append(PackageHighlight('Cupcakes', cupcake_match.group('count')))

    if _SETUP_PATTERN.search(searchable_text):
        highlights.append(PackageHighlight('Setup', 'Included'))

    inclusion_count = len(inclusions)
    if inclusion_count:
        label = 'Item' if inclusion_count == 1 else 'Items'
        highlights.append(PackageHighlight(label, str(inclusion_count)))

    return highlights