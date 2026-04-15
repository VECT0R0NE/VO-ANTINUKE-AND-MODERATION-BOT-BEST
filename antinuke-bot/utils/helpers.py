import re

def parse_time(time_str: str):
    time_regex = re.compile(r'(\d+)([smhdwy]|mo)')
    matches = time_regex.findall(time_str.lower())
    
    if not matches:
        return None
    
    total_seconds = 0
    for value, unit in matches:
        value = int(value)
        if unit == 's':
            total_seconds += value
        elif unit == 'm':
            total_seconds += value * 60
        elif unit == 'h':
            total_seconds += value * 3600
        elif unit == 'd':
            total_seconds += value * 86400
        elif unit == 'w':
            total_seconds += value * 604800
        elif unit == 'mo':
            total_seconds += value * 2592000
        elif unit == 'y':
            total_seconds += value * 31536000
    
    return total_seconds

def format_time(seconds: int):
    if seconds < 60:
        return f'{seconds}s'
    elif seconds < 3600:
        return f'{seconds // 60}m'
    elif seconds < 86400:
        return f'{seconds // 3600}h'
    elif seconds < 604800:
        return f'{seconds // 86400}d'
    elif seconds < 2592000:
        return f'{seconds // 604800}w'
    elif seconds < 31536000:
        return f'{seconds // 2592000}mo'
    else:
        return f'{seconds // 31536000}y'

ACTIONS = [
    'banning_members',
    'kicking_members',
    'pruning_members',
    'creating_channels',
    'deleting_channels',
    'creating_roles',
    'deleting_roles',
    'authorizing_applications',
    'giving_dangerous_permissions',
    'giving_administrative_roles',
    'editing_channels',
    'editing_roles',
    'adding_bots',
    'updating_server',
    'creating_webhooks',
    'deleting_webhooks'
]

PUNISHMENTS = [
    'ban',
    'kick',
    'clear_roles',
    'timeout',
    'warn'
]

def get_user_from_string(guild, user_str: str):
    user_str = user_str.strip()
    
    if user_str.startswith('<@') and user_str.endswith('>'):
        user_id = int(user_str[2:-1].replace('!', ''))
        return guild.get_member(user_id)
    
    if user_str.isdigit():
        return guild.get_member(int(user_str))
    
    for member in guild.members:
        if member.name.lower() == user_str.lower() or (member.nick and member.nick.lower() == user_str.lower()):
            return member
    
    return None
