from flask import Flask, request, render_template
import redis
import json
import requests
import requests.packages.urllib3
import time
import threading

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

    r = requests.post(app.config['SLACK_API_BASE']+'chat.postMessage', data = {"token":db.get(request.form['team_id']), "channel":request.form['channel_id'], "text":"*Snapslack-`10`*: " + request.form['text'], "username":'SS - '+request.form['user_name'], "as_user":'true'})
    r = r.json()

    if r['ok']:
        snapData = {"channel_id": request.form['channel_id'], "ts":r['ts'], "team_id":request.form['team_id'], "text":request.form['text']}
        db.zadd('snaps', str(time.time()), json.JSONEncoder().encode(snapData))
    return ''


@app.route('/oauth', )
def oauth():
    code = request.args.get('code', '')
    state = request.args.get('state', '')

    if not code:
        return "Couldn't get a code from Slack. Something must have gone wrong"

    r = requests.post(app.config['SLACK_OAUTH_URL'], data = {"client_id":app.config['OAUTH_CLIENT_ID'], "client_secret":app.config['OATUH_CLIENT_SECRET'], "code":code})
    
    if r.status_code == requests.codes.ok:
        r = r.json()
        db.set(r['team_id'], r['access_token'])
    else:
        r.raise_for_status()
    
    return "Successfully Authenticated!"

@app.before_first_request
def snapProcessing():
    updateSnaps()

def updateSnaps():

    currentTime = time.time()
    expireTime = currentTime - 10
    snapsToUpdate = db.zrangebyscore('snaps', '-inf', '+inf', withscores=True)

    for snap in snapsToUpdate:
        snapData = json.loads(snap[0])
        count = int(10 - round(currentTime-float(snap[1])))
        if(count <= 0):
            r = requests.post(app.config['SLACK_API_BASE']+'chat.delete', data = {"token":db.get(snapData['team_id']), "ts":snapData['ts'], "channel":snapData['channel_id']})
            db.zrem('snaps', snap[0])
        else:
            r = requests.post(app.config['SLACK_API_BASE']+'chat.update', data = {"token":db.get(snapData['team_id']), "ts":snapData['ts'], "channel":snapData['channel_id'], "text":"*Snapslack-`"+str(count)+"`:* " + snapData['text']})
            db.zadd('snaps', snap[1], json.JSONEncoder().encode(snapData))

    threading.Timer(1, updateSnaps).start()


if __name__ == '__main__':
    app.debug = app.config['DEBUG']
    app.run(host='0.0.0.0')