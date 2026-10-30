#!/usr/bin/env python3
"""Single local launcher. Opens first-run setup authorization only on this Mac."""
import os
import sys
import threading
import time
import urllib.request
import urllib.error
import json
import webbrowser
import config
from accounts import Accounts
from gmail_sender import GmailSender

def main():
    accounts=Accounts(config.DATA_DIR,GmailSender(config.DATA_DIR))
    url='http://localhost:%d/start.html'%config.PORT
    if not accounts.has_users():url+='#setup='+accounts.setup
    health='http://localhost:%d/healthz'%config.PORT
    try:
        with urllib.request.urlopen(health,timeout=1) as r:info=json.load(r)
    except urllib.error.HTTPError:
        print('Another app is using port %d. Close its window and start IndianTrader again.'%config.PORT);return 1
    except (urllib.error.URLError,TimeoutError):info=None
    if info:
        if info.get('app')=='IndianTrader' and info.get('version')==3:
            webbrowser.open(url);print('IndianTrader is already running. Opening the mode selection screen.');return 0
        print('Close the existing Paper Trader server window, then open Start IndianTrader.command again. Your data will be preserved.');return 1
    def open_when_ready():
        for _ in range(60):
            try:
                with urllib.request.urlopen(health,timeout=.5) as r:
                    if json.load(r).get('version')==3:webbrowser.open(url);return
            except (urllib.error.URLError,TimeoutError,ValueError):pass
            time.sleep(.25)
    threading.Thread(target=open_when_ready,daemon=True).start()
    from server import main as serve
    serve()
    return 0
if __name__=='__main__':sys.exit(main())
