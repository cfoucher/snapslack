from flask import Flask, request, render_template
import sys
import redis
import json
import requests
import requests.packages.urllib3
import time
import threading
import multiprocessing

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
    return 'OK'

@app.route('/slash', methods=['POST'])
def slashCommand():

    if request.form['token'] != app.config['SLACK_VERYFICATION_TOKEN']:
        return ''
    
    token = db.get(request.form['user_id']+'-'+request.form['team_id'])
    if not token:
        return "Looks like you don't have Snapslack enabled for your account yet. Please visit https://snapslack.conradfoucher.ca to enable it."

    r = requests.post(app.config['SLACK_API_BASE']+'chat.postMessage', data = {"token":token, "channel":request.form['channel_id'], "text":"*Snapslack-`10`*: " + request.form['text'], "username":'SS - '+request.form['user_name'], "as_user":'true'})
    r = r.json()

    if r['ok']:
        snapData = {"channel_id": request.form['channel_id'], "ts":r['ts'], "team_id":request.form['team_id'], "text":request.form['text'], "user_id":request.form['user_id']}
        db.zadd('snaps', str(time.time()), json.JSONEncoder().encode(snapData))
    return ''


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
    
    return "Successfully Authenticated!"

#@app.before_first_request
#def snapProcessing():
#    print "yo"
#    #p = multiprocessing.Process(target=updateSnaps())
#    #p.start()
#    return 'ok'
#    #updateSnaps()

def updateSnaps():

    currentTime = time.time()
    expireTime = currentTime - 10
    snapsToUpdate = db.zrangebyscore('snaps', '-inf', '+inf', withscores=True)

    for snap in snapsToUpdate:
        snapData = json.loads(snap[0])
        count = int(10 - round(currentTime-float(snap[1])))
        if(count <= 0):
            sys.stdout.flush()
            deleted = delete(snapData['user_id'], snapData['team_id'], snapData['ts'], snapData['channel_id'])
            if deleted:
                db.zrem('snaps', snap[0])
            else:
                print ('message did not successfully delete')
                sys.stdout.flush()
        else:
            r = requests.post(app.config['SLACK_API_BASE']+'chat.update', data = {"token":db.get(snapData['user_id']+'-'+snapData['team_id']), "ts":snapData['ts'], "channel":snapData['channel_id'], "text":"*Snapslack-`"+str(count)+"`:* " + snapData['text']}, timeout=2)

    time.sleep(1)
    updateSnaps()

def delete(user_id, team_id, ts, channel_id):
    print ("We will try to delete the message 3 times")
    for x in range(0, 3):
        r = requests.post(app.config['SLACK_API_BASE']+'chat.delete', data = {"token":db.get(user_id+'-'+team_id), "ts":ts, "channel":channel_id}, timeout=2)
        r = r.json()

        if r['ok']:
            print "RESPONSE SAYS MESSAGE IS DELETED!"
            sys.stdout.flush()
            return True

    return False

if __name__ == '__main__':
    app.debug = app.config['DEBUG']
    app.run(host='0.0.0.0')
    print "Starting processing of snaps"
    p = multiprocessing.Process(target=updateSnaps())
    p.start()