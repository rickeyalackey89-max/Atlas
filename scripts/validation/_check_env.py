import os, winreg
for var in ['DISCORD_PICKS_WEBHOOK_URL', 'DISCORD_WEBHOOK_URL', 'ATLAS_DISCORD_BOT_TOKEN', 'ATLAS_DISCORD_CHANNEL_ID']:
    val = os.environ.get(var, '')
    if not val:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Environment')
            v, _ = winreg.QueryValueEx(key, var)
            val = str(v).strip()
        except Exception:
            val = ''
    masked = (val[:12] + '...' + val[-4:]) if len(val) > 20 else (val if val else '(not set)')
    print(f'{var}: {masked}')
