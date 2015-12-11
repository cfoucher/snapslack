from flask import Flask, request, render_template
from multiprocessing import Process
import sys
import redis
import json
import requests
import requests.packages.urllib3
import time

requests.packages.urllib3.disable_warnings()

app = Flask(__name__)

app.config.from_object(__name__)
app.config.from_envvar('SNAPSLACK_SETTINGS')

db = redis.StrictRedis(host='localhost', port=6379, db=0)

@app.route('/')
def landingPage():
    return render_template('landingpage.html')

@app.route('/test')
def test():
    return render_template('error.html')

@app.route('/slash', methods=['POST'])
def slashCommand():

    if request.form['token'] != app.config['SLACK_VERYFICATION_TOKEN']:
        return ''
    
    token = db.get(request.form['user_id']+'-'+request.form['team_id'])
    if not token:
        return "Looks like you don't have Snapslack enabled for your account yet. Please visit https://snapslack.conradfoucher.ca to enable it."

    if request.form['text']:
        r = requests.post(app.config['SLACK_API_BASE']+'chat.postMessage', data = {"token":token, "channel":request.form['channel_id'], "text":"*Snapslack-`10`*: " + request.form['text'], "username":'SS - '+request.form['user_name'], "as_user":'true'})
        r = r.json()

        if r['ok']:
            snapData = {"channel_id": request.form['channel_id'], "ts":r['ts'], "team_id":request.form['team_id'], "text":request.form['text'], "user_id":request.form['user_id']}
            db.zadd('snaps', str(time.time()), json.JSONEncoder().encode(snapData))
            return ''
        else:
            if r['error'] == 'invalid_auth' or r['error'] == 'not_authed' or r['error'] == 'account_inactive':
                return "Looks like you don't have Snapslack enabled for your account yet. Please visit https://snapslack.conradfoucher.ca to enable it."
            else:
                return "Something went wrong. Please try again later. If the issue persists please try reauthenticating at https://snapslack.conradfoucher.ca"
    else:
        return "You need to type something in order to Snapslack!"


@app.route('/oauth', )
def oauth():
    code = request.args.get('code', '')
    state = request.args.get('state', '')

    if not code:
        return "Couldn't get a code from Slack. Something must have gone wrong"

    r = requests.post(app.config['SLACK_API_BASE']+'oauth.access', data = {"client_id":app.config['OAUTH_CLIENT_ID'], "client_secret":app.config['OATUH_CLIENT_SECRET'], "code":code})
    
    if r.status_code == requests.codes.ok:
        r = r.json()
        team_id = r['team_id']
        access_token = r['access_token']
        # Get User ID
        r = requests.post(app.config['SLACK_API_BASE']+'auth.test', data = {"token":access_token})
        r = r.json()
        db.set(r['user_id']+'-'+team_id, access_token)
    else:
        r.raise_for_status()
        return render_template('error.html')
    
    return render_template('authsuccess.html')

@app.before_first_request
def snapProcessing():
    print "Starting Snapslack Process Workers"
    updateProcess = Process(target=updateCountdowns)
    removeProcess = Process(target=removeSnaps)
    updateProcess.start()
    removeProcess.start()
    return 'Processing workers are Running'


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
    time.sleep(1)
    updateCountdowns()

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

    time.sleep(1)
    removeSnaps()

def deleteSnap(user_id, team_id, ts, channel_id):
    # We will try to delete the message 3 times
    for x in range(0, 3):
        r = requests.post(app.config['SLACK_API_BASE']+'chat.delete', data = {"token":db.get(user_id+'-'+team_id), "ts":ts, "channel":channel_id}, timeout=2)
        r = r.json()
        if r['ok']:
            return True
    return False


if __name__ == '__main__':
    app.debug = app.config['DEBUG']
    app.run(host='0.0.0.0')
    

