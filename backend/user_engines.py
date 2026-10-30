"""Separate existing paper engines for each verified user and each selected mode."""
import os
import shutil
import threading
from engine import Engine, LOCK
from util import read_json,write_json

class UserEngines:
    def __init__(self,folder,accounts):
        self.folder,self.accounts=folder,accounts;self.cache={};self.lock=threading.RLock()
    def get(self,user):
        uid,mode=user['id'],user['mode']; key=(uid,mode)
        with self.lock:
            if key in self.cache:return self.cache[key]
            profile=os.path.join(self.folder,'users',uid)
            marker=os.path.join(profile,'initialized.json')
            if not os.path.exists(marker):
                # Only the verified first owner can adopt the pre-account installation.
                for m in ('demo','paper'):
                    directory=os.path.join(profile,m);os.makedirs(directory,mode=0o700,exist_ok=True)
                    os.chmod(profile,0o700)
                    if user['role']=='owner':
                        for name in ('settings.json','holidays.json','demo-account.json' if m=='demo' else 'account.json'):
                            source=os.path.join(self.folder,name)
                            if os.path.isfile(source) and not os.path.exists(os.path.join(directory,name)):
                                with LOCK:shutil.copy2(source,os.path.join(directory,name))
                    settings=read_json(os.path.join(directory,'settings.json'),{}) or {}
                    settings['source']='demo' if m=='demo' else settings.get('source') if settings.get('source') in ('upstox','angel') else 'upstox'
                    settings['owner']=user['name'];write_json(os.path.join(directory,'settings.json'),settings)
                if user['role']=='owner':
                    for name in ('secrets.json','angel.json'):
                        source=os.path.join(self.folder,name);destination=os.path.join(profile,name)
                        if os.path.isfile(source) and not os.path.exists(destination):
                            with LOCK:shutil.copy2(source,destination)
                write_json(marker,{'initialized':True})
            directory=os.path.join(profile,mode)
            e=Engine(data_dir=directory,credentials_dir=profile);self.cache[key]=e
            return e
    def tick_all(self):
        # Also load dormant profiles after restart, so auto exits do not depend on a browser being open.
        for user in self.accounts.users():
            for mode in ('demo','paper'):
                u=dict(user,mode=mode)
                directory=os.path.join(self.folder,'users',u['id'],mode)
                if os.path.isdir(directory):self.get(u)
        with self.lock: engines=list(self.cache.values())
        for e in engines:
            try:e.tick()
            except Exception:pass
