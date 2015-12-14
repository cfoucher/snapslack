from flask import Flask, request, render_template, make_response
import threading
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

@app.route('/slash', methods=['POST'])
def slashCommand():
    if request.form['token'] != app.config['SLACK_VERYFICATION_TOKEN']:
        return ''
    
    token = db.get(request.form['user_id']+'-'+request.form['team_id'])
    if not token:
        return "Looks like you don't have Snapslack enabled for your account yet. Please visit https://snapslack.conradfoucher.ca to enable it."

    if request.form['text']:
        # Must response in 3000 ms so spawn thread to do work and responde immediately
        thread = threading.Thread(target=slashResponse(request.form, token))
        thread.start()
        response = make_response("", 200)
        return response
    else:
        return "You need to type something in order to Snapslack!"

def slashResponse(form, token):
    message = form['text']
    tag = message
    R = False
    if message.find("/giphy") != -1:
        if message.find("/giphyr") != -1:
            tag = message.replace("/giphyr", "")
            tag = tag.strip()
            if tag:
                r = requests.get(app.config['GIHPY_API_BASE']+'random', params={"api_key":app.config['GIHPY_API_KEY'], "tag":tag, "rating":"r"})
            else:
                response = "You must type something for Giphy to match against"
                r = requests.post(form['response_url'], data = json.JSONEncoder().encode({"text":response}), headers = {'Content-Type': 'application/json'})
                return
        else:
            tag = message.replace("/giphy", "")
            tag = tag.strip()
            if tag:
                r = requests.get(app.config['GIHPY_API_BASE']+'random', params={"api_key":app.config['GIHPY_API_KEY'], "tag":tag})
            else:
                response = "You must type something for Giphy to match against"
                r = requests.post(form['response_url'], data = json.JSONEncoder().encode({"text":response}), headers = {'Content-Type': 'application/json'})
                return
        r = r.json()
        if r['meta']['msg'] == 'OK':
            if r['data']:
                message = message + "\n"+r['data']['url']
            else:
                response = "Giphy could not match "+tag
                r = requests.post(form['response_url'], data = json.JSONEncoder().encode({"text":response}), headers = {'Content-Type': 'application/json'})
                return
    
    r = requests.post(app.config['SLACK_API_BASE']+'chat.postMessage', data = {"token":token, "channel":form['channel_id'], "text":"*Snapslack-`10`*: " + message, "username":'SS - '+form['user_name'], "as_user":'true'})
    r = r.json()

    if r['ok']:
        snapData = {"channel_id": form['channel_id'], "ts":r['ts'], "team_id":form['team_id'], "text":form['text'], "user_id":form['user_id']}
        db.zadd('snaps', str(time.time()), json.JSONEncoder().encode(snapData))
        return
    else:
        if r['error'] == 'invalid_auth' or r['error'] == 'not_authed' or r['error'] == 'account_inactive':
            response = "Looks like you don't have Snapslack enabled for your account yet. Please visit https://snapslack.conradfoucher.ca to enable it."
            r = requests.post(form['response_url'], data = json.JSONEncoder().encode({"text":response}), headers = {'Content-Type': 'application/json'})
            
        else:
            response = "Something went wrong. Please try again later. If the issue persists please try reauthenticating at https://snapslack.conradfoucher.ca"
            r = requests.post(form['response_url'], data = json.JSONEncoder().encode({"text":response}), headers = {'Content-Type': 'application/json'})

if __name__ == '__main__':
    app.debug = app.config['DEBUG']
    app.run(host='0.0.0.0')
    

