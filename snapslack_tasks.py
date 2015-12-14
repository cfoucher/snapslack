from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from multiprocessing import Process
import sys
import redis
import json
import requests
import requests.packages.urllib3
import time
import os

app = Flask(__name__)
app.config.from_object(__name__)
app.config.from_envvar('SNAPSLACK_SETTINGS')
db = redis.StrictRedis(host='localhost', port=6379, db=0)
requests.packages.urllib3.disable_warnings()

def updateCountdowns():
    currentTime = time.time()
    expireTime = currentTime - 10
    # Grab all snaps from db that need to have their countdowns updated. 
    snapsToUpdate = db.zrangebyscore('snaps', '('+str(expireTime), '+inf', withscores=True)

    for snap in snapsToUpdate:
        snapData = json.loads(snap[0])
        count = int(10 - round(currentTime-float(snap[1])))
        if(count > 0):
            # Remove Snap from 'snaps' list to prevent race condition between delete requests and update requests. Make a backup of it at the same time.
            pipe = db.pipeline()
            removeAndBackup = pipe.zrem('snaps', snap[0]).set('tmp-Update-'+str(snap[1]), snap[0]).execute()
            if(removeAndBackup[0] > 0):
                # We grabed it before the delete process -> update it
                r = requests.post(app.config['SLACK_API_BASE']+'chat.update', data = {"token":db.get(snapData['user_id']+'-'+snapData['team_id']), "ts":snapData['ts'], "channel":snapData['channel_id'], "text":"*Snapslack-`"+str(count)+"`:* " + snapData['text']}, timeout=5)
                # Remove the tmp-backup entry and add it back to the 'snaps' list
                pipe = db.pipeline()
                removeAndAdd = pipe.delete('tmp-Update-'+str(snap[1])).zadd('snaps', snap[1], snap[0]).execute()
                if(removeAndAdd[1] < 1):
                    # Couldn't add the snap back to the list. Removing it from slack!
                    deleted = deleteSnap(snapData['user_id'], snapData['team_id'], snapData['ts'], snapData['channel_id'])
            else:
                # Looks like the delete process grabed it first -> delete tmp backup
                db.delete('tmp-Update-'+str(snap[1]))

def removeSnaps():
    currentTime = time.time()
    expireTime = currentTime - 10
    # Grab all snaps from db that need to be removed from slack
    snapsToRemove = db.zrangebyscore('snaps', '-inf', str(expireTime), withscores=True)
    
    for snap in snapsToRemove:
        snapData = json.loads(snap[0])
        pipe = db.pipeline()
        removeAndBackup = pipe.zrem('snaps', snap[0]).set('tmp-Remove-'+str(snap[1]), snap[0]).execute()
        if(removeAndBackup[0] > 0):
            # Successfully removed it from the db. Update Process didn't get it :)
            deleted = deleteSnap(snapData['user_id'], snapData['team_id'], snapData['ts'], snapData['channel_id'])
            if deleted:
                # Snap successfully removed from slack -> delete backup
                db.delete('tmp-Remove-'+str(snap[1]))
            else:
                # Remove the tmp-backup entry and add it back to the 'snaps' list so that we can try deleting it next round
                pipe = db.pipeline()
                removeAndAdd = pipe.delete('tmp-Remove-'+str(snap[1])).zadd('snaps', snap[1], snap[0]).execute()

def deleteSnap(user_id, team_id, ts, channel_id):
    # We will try to delete the message 3 times
    for x in range(0, 3):
        r = requests.post(app.config['SLACK_API_BASE']+'chat.delete', data = {"token":db.get(user_id+'-'+team_id), "ts":ts, "channel":channel_id}, timeout=2)
        r = r.json()
        if r['ok']:
            return True
    return False

if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    scheduler.add_job(removeSnaps, 'interval', seconds=1,  max_instances=2 )
    scheduler.add_job(updateCountdowns, 'interval', seconds=1,  max_instances=2 )
    scheduler.start()

    try:
        # This is here to simulate application activity (which keeps the main thread alive).
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        # Not strictly necessary if daemonic mode is enabled but should be done if possible
        scheduler.shutdown()