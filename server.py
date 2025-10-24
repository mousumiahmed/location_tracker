# server.py (simplified demo)
from flask import Flask, request, jsonify
import sqlite3, os, time, json, jwt
from datetime import datetime, timedelta
from twilio.rest import Client as TwilioClient

DB = 'emergency.db'
JWT_SECRET = os.getenv('JWT_SECRET', 'dev-secret')  # use strong secret in production
TW_SID = os.getenv('TW_SID')
TW_TOKEN = os.getenv('TW_TOKEN')
TW_FROM = os.getenv('TW_FROM')

tw_client = None
if TW_SID and TW_TOKEN:
    tw_client = TwilioClient(TW_SID, TW_TOKEN)

app = Flask(__name__)

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS consents (id INTEGER PRIMARY KEY, user_id TEXT, consent_text TEXT, ts TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS incidents (incident_id TEXT PRIMARY KEY, user_id TEXT, started_at TEXT, stopped_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS locations (id INTEGER PRIMARY KEY, incident_id TEXT, lat REAL, lon REAL, accuracy REAL, ts TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS contacts (user_id TEXT, name TEXT, phone TEXT, email TEXT)''')
    conn.commit()
    conn.close()

@app.before_request
def startup():
    init_db()

def gen_token(user_id):
    payload = {
        'sub': user_id,
        'iat': int(time.time()),
        'exp': int(time.time()) + 60*60*24  # 24h valid (demo)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def verify_token(auth_header):
    if not auth_header or not auth_header.startswith('Bearer '): return None
    token = auth_header.split(' ',1)[1].strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        return payload.get('sub')
    except Exception:
        return None

@app.route('/v1/consent/register', methods=['POST'])
def register_consent():
    data = request.get_json()
    if not data or 'user_id' not in data or 'consent_text' not in data:
        return jsonify({'error':'bad_payload'}), 400
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('INSERT INTO consents (user_id, consent_text, ts) VALUES (?, ?, ?)',
              (data['user_id'], data['consent_text'], datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    token = gen_token(data['user_id'])
    return jsonify({'status':'consent_recorded','token': token}), 201

@app.route('/v1/incident/start', methods=['POST'])
def incident_start():
    user = verify_token(request.headers.get('Authorization',''))
    if not user: return jsonify({'error':'unauthorized'}), 401
    data = request.get_json()
    if not data or 'incident_id' not in data or 'user_id' not in data:
        return jsonify({'error':'bad_payload'}), 400
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO incidents (incident_id, user_id, started_at) VALUES (?,?,?)',
              (data['incident_id'], data['user_id'], datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'status':'incident_started'}), 201

@app.route('/v1/incident/update', methods=['POST'])
def incident_update():
    user = verify_token(request.headers.get('Authorization',''))
    if not user: return jsonify({'error':'unauthorized'}), 401
    data = request.get_json()
    required = ['incident_id','user_id','lat','lon','timestamp']
    if not data or any(k not in data for k in required):
        return jsonify({'error':'bad_payload'}), 400

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('INSERT INTO locations (incident_id, lat, lon, accuracy, ts) VALUES (?,?,?,?,?)',
              (data['incident_id'], data['lat'], data.get('lon'), data.get('accuracy') or 0.0, data['timestamp']))
    conn.commit()

    # On first update, notify contacts
    c.execute('SELECT COUNT(*) FROM locations WHERE incident_id=?', (data['incident_id'],))
    count = c.fetchone()[0]
    if count == 1:
        # fetch contacts
        c.execute('SELECT name, phone FROM contacts WHERE user_id=?', (data['user_id'],))
        contacts = c.fetchall()
        link = f"https://www.google.com/maps/search/?api=1&query={data['lat']},{data['lon']}"
        for name, phone in contacts:
            if phone and tw_client:
                try:
                    tw_client.messages.create(
                        body=f"EMERGENCY: {data['user_id']} triggered an incident. Location: {link}",
                        from_=TW_FROM,
                        to=phone
                    )
                except Exception as e:
                    app.logger.error('twilio error: %s', e)
    conn.close()
    return jsonify({'status':'location_saved'}), 201

@app.route('/v1/incident/stop', methods=['POST'])
def incident_stop():
    user = verify_token(request.headers.get('Authorization',''))
    if not user: return jsonify({'error':'unauthorized'}), 401
    data = request.get_json()
    if not data or 'incident_id' not in data:
        return jsonify({'error':'bad_payload'}), 400
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('UPDATE incidents SET stopped_at=? WHERE incident_id=?', (datetime.utcnow().isoformat(), data['incident_id']))
    # generate a simple report
    c.execute('SELECT lat,lon,accuracy,ts FROM locations WHERE incident_id=? ORDER BY id ASC', (data['incident_id'],))
    rows = c.fetchall()
    report = [{'lat':r[0], 'lon':r[1], 'accuracy':r[2], 'ts':r[3]} for r in rows]
    conn.commit()
    conn.close()
    return jsonify({'status':'stopped','report': report}), 200

@app.route('/v1/incident/<incident_id>/report', methods=['GET'])
def get_report(incident_id):
    user = verify_token(request.headers.get('Authorization',''))
    if not user: return jsonify({'error':'unauthorized'}), 401
    # In production require elevated auth (law enforcement token) + consent verification
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('SELECT lat,lon,accuracy,ts FROM locations WHERE incident_id=? ORDER BY id ASC', (incident_id,))
    rows = c.fetchall()
    report = [{'lat':r[0], 'lon':r[1], 'accuracy':r[2], 'ts':r[3]} for r in rows]
    conn.close()
    return jsonify({'incident_id': incident_id, 'report': report}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, ssl_context='adhoc')
