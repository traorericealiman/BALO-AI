from flask import Flask, request, Response, send_file
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
from rapidfuzz import fuzz
import unicodedata
import requests
import tempfile
import threading
import time
import json
import os

load_dotenv()

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DJELIA_API_KEY     = os.getenv("DJELIA_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
BASE_URL           = os.getenv("BASE_URL")

print(f"[CONFIG] BASE_URL={BASE_URL}")
print(f"[CONFIG] DJELIA_API_KEY={'OK' if DJELIA_API_KEY else 'MANQUANT'}")
print(f"[CONFIG] TWILIO_ACCOUNT_SID={'OK' if TWILIO_ACCOUNT_SID else 'MANQUANT'}")
print(f"[CONFIG] TWILIO_AUTH_TOKEN={'OK' if TWILIO_AUTH_TOKEN else 'MANQUANT'}")

TRANSCRIBE_URL = "https://djelia.cloud/api/v1/models/transcribe"
DJELIA_HEADERS = {"x-api-key": DJELIA_API_KEY}

with open(os.path.join(BASE_DIR, "references.json"), encoding="utf-8") as f:
    REFERENCES = json.load(f)
print(f"[CONFIG] {len(REFERENCES)} références chargées")

call_state = {}
call_audio = {}


# ── helpers ───────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


def find_best_match(transcription: str):
    transcription_norm = normalize(transcription)
    best_score = 0
    best_ref   = None

    for ref in REFERENCES:
        ref_norm = normalize(ref["transcription"])
        score    = fuzz.token_sort_ratio(transcription_norm, ref_norm)
        print(f"[MATCH] '{ref['label']}' | score: {score} | transcrit: '{transcription_norm}' | ref: '{ref_norm}'")
        if score > best_score:
            best_score = score
            best_ref   = ref

    # Seuil fixé à 15% minimum
    seuil = best_ref.get("seuil", 15) if best_ref else 15
    if best_score >= seuil:
        return best_ref, best_score
    return None, best_score


def download_recording(url, auth, retries=3, delay=2):
    print(f"[DOWNLOAD] Téléchargement depuis {url}")
    for attempt in range(retries):
        resp = requests.get(url, auth=auth)
        print(f"[DOWNLOAD] Tentative {attempt+1} | status: {resp.status_code} | taille: {len(resp.content)} bytes")
        if resp.status_code == 200 and len(resp.content) > 1000:
            print(f"[DOWNLOAD] Succès !")
            return resp.content
        time.sleep(delay)
    print(f"[DOWNLOAD] Échec après {retries} tentatives")
    return None


# ── traitement arrière-plan ───────────────────────────────────────────────────

def process_audio(recording_url, call_sid):
    print(f"[PROCESS] Début traitement pour {call_sid}")
    call_state[call_sid] = "processing"

    content = download_recording(recording_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
    if not content:
        print(f"[PROCESS] Impossible de télécharger l'audio pour {call_sid}")
        call_state[call_sid] = "error"
        return

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.write(content)
    tmp.close()
    print(f"[PROCESS] Audio sauvegardé temporairement : {tmp.name}")

    try:
        print(f"[TRANSCRIBE] Envoi à Djelia...")
        with open(tmp.name, "rb") as f:
            res = requests.post(
                TRANSCRIBE_URL,
                headers=DJELIA_HEADERS,
                files={"file": f},
                params={"translate_to_french": False}
            )
        print(f"[TRANSCRIBE] status: {res.status_code} | réponse: {res.text[:200]}")

        raw = res.json()
        if isinstance(raw, list):
            transcription = " ".join(segment.get("text", "") for segment in raw)
        else:
            transcription = raw.get("text", "")
        print(f"[TRANSCRIPTION] '{transcription}'")

        match, score = find_best_match(transcription)

        if match:
            print(f"[HIT] {match['label']} (score {score})")
            audio_path = os.path.join(BASE_DIR, match["audio"])
            print(f"[HIT] Fichier audio : {audio_path} | exists: {os.path.exists(audio_path)}")
            call_audio[call_sid] = audio_path
            call_state[call_sid] = "ready"
        else:
            print(f"[MISS] score max {score}")
            call_state[call_sid] = "no_match"

    except Exception as e:
        print(f"[ERROR] {e}")
        call_state[call_sid] = "error"
    finally:
        os.remove(tmp.name)
        print(f"[PROCESS] Fichier temporaire supprimé")


# ── routes ────────────────────────────────────────────────────────────────────

@app.route("/voice", methods=["GET", "POST"])
def voice():
    print(f"[VOICE] Appel entrant")
    r = VoiceResponse()
    r.play(f"{BASE_URL}/audio/Bienvenue.mp3")
    r.record(max_length=20, play_beep=True, action="/handle-recording")
    return Response(str(r), mimetype="text/xml")


@app.route("/handle-recording", methods=["POST"])
def handle_recording():
    recording_url = request.form.get("RecordingUrl") + ".wav"
    call_sid      = request.form.get("CallSid")
    print(f"[RECORDING] call_sid={call_sid} | url={recording_url}")

    t = threading.Thread(target=process_audio, args=(recording_url, call_sid))
    t.daemon = True
    t.start()

    r = VoiceResponse()
    r.play(f"{BASE_URL}/audio/Fin.mp3")
    r.redirect(f"{BASE_URL}/wait?call_sid={call_sid}")
    return Response(str(r), mimetype="text/xml")


@app.route("/wait", methods=["GET", "POST"])
def wait():
    call_sid = request.args.get("call_sid")
    state    = call_state.get(call_sid, "processing")
    print(f"[WAIT] call_sid={call_sid} | state={state}")

    r = VoiceResponse()

    if state == "ready":
        print(f"[WAIT] Audio prêt → lecture résultat")
        r.play(f"{BASE_URL}/result?call_sid={call_sid}")
        call_state.pop(call_sid, None)

    elif state == "no_match":
        print(f"[WAIT] No match → message vocal")
        r.say("Je n'ai pas compris. Veuillez réessayer.", language="fr-FR")
        call_state.pop(call_sid, None)
        call_audio.pop(call_sid, None)

    elif state == "error":
        print(f"[WAIT] Erreur pour {call_sid}")
        r.say("Une erreur est survenue. Veuillez rappeler.", language="fr-FR")
        call_state.pop(call_sid, None)
        call_audio.pop(call_sid, None)

    else:
        print(f"[WAIT] Toujours en traitement, on attend...")
        r.pause(length=3)
        r.redirect(f"{BASE_URL}/wait?call_sid={call_sid}")

    return Response(str(r), mimetype="text/xml")


@app.route("/result", methods=["GET"])
def result():
    call_sid   = request.args.get("call_sid")
    audio_file = call_audio.get(call_sid)
    print(f"[RESULT] call_sid={call_sid} | audio_file={audio_file}")

    if audio_file and os.path.exists(audio_file):
        print(f"[RESULT] Envoi du fichier : {audio_file}")
        with open(audio_file, "rb") as f:
            data = f.read()
        mimetype = "audio/mpeg" if audio_file.endswith(".mp3") else "audio/wav"
        return Response(data, mimetype=mimetype, headers={
            "Content-Length": str(len(data)),
            "Cache-Control": "no-cache"
        })

    print(f"[RESULT] Fichier introuvable !")
    return "No audio found", 404


@app.route("/audio/<filename>", methods=["GET"])
def serve_audio(filename):
    path = os.path.join(BASE_DIR, filename)
    print(f"[AUDIO] serving: {path} | exists: {os.path.exists(path)}")
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
        print(f"[AUDIO] bytes: {len(data)}")
        mimetype = "audio/mpeg" if filename.endswith(".mp3") else "audio/wav"
        return Response(data, mimetype=mimetype, headers={
            "Content-Length": str(len(data)),
            "Cache-Control": "no-cache"
        })
    return "File not found", 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)