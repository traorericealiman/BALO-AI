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

GITHUB_RAW = "https://raw.githubusercontent.com/traorericealiman/BALO-AI/main"

TRANSCRIBE_URL = "https://djelia.cloud/api/v1/models/transcribe"
TTS_URL        = "https://djelia.cloud/api/v2/models/tts"
DJELIA_HEADERS = {"x-api-key": DJELIA_API_KEY}

with open(os.path.join(BASE_DIR, "references.json"), encoding="utf-8") as f:
    REFERENCES = json.load(f)

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

    seuil = best_ref["seuil"] if best_ref else 60
    if best_score >= seuil:
        return best_ref, best_score
    return None, best_score


def download_recording(url, auth, retries=3, delay=2):
    for _ in range(retries):
        resp = requests.get(url, auth=auth)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content
        time.sleep(delay)
    return None


def generate_no_match_audio():
    path = "/tmp/no_match.mp3"
    if os.path.exists(path):
        return path

    texte = "D'accord, je n'ai pas bien compris. Pouvez-vous répéter s'il vous plaît ?"
    tts = requests.post(TTS_URL, headers=DJELIA_HEADERS, json={"text": texte})
    if tts.status_code == 200 and len(tts.content) > 0:
        with open(path, "wb") as f:
            f.write(tts.content)
        return path
    return None


# ── traitement arrière-plan ───────────────────────────────────────────────────

def process_audio(recording_url, call_sid):
    call_state[call_sid] = "processing"

    content = download_recording(recording_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
    if not content:
        call_state[call_sid] = "error"
        return

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.write(content)
    tmp.close()

    try:
        with open(tmp.name, "rb") as f:
            res = requests.post(
                TRANSCRIBE_URL,
                headers=DJELIA_HEADERS,
                files={"file": f},
                params={"translate_to_french": False}
            )
        transcription = res.json().get("text", "")
        print(f"[TRANSCRIPTION] {transcription}")

        match, score = find_best_match(transcription)

        if match:
            print(f"[HIT] {match['label']} (score {score})")
            call_audio[call_sid] = f"{GITHUB_RAW}/{match['audio']}"
            call_state[call_sid] = "ready"
        else:
            print(f"[MISS] score max {score}")
            call_audio[call_sid] = generate_no_match_audio()
            call_state[call_sid] = "no_match"

    except Exception as e:
        print(f"[ERROR] {e}")
        call_state[call_sid] = "error"
    finally:
        os.remove(tmp.name)


# ── routes ────────────────────────────────────────────────────────────────────

@app.route("/voice", methods=["GET", "POST"])
def voice():
    r = VoiceResponse()
    r.play(f"{GITHUB_RAW}/Bienvenue.wav")
    r.record(max_length=20, play_beep=True, action="/handle-recording")
    return Response(str(r), mimetype="text/xml")


@app.route("/handle-recording", methods=["POST"])
def handle_recording():
    recording_url = request.form.get("RecordingUrl") + ".wav"
    call_sid      = request.form.get("CallSid")

    t = threading.Thread(target=process_audio, args=(recording_url, call_sid))
    t.daemon = True
    t.start()

    r = VoiceResponse()
    r.play(f"{GITHUB_RAW}/Fin.wav")
    r.redirect(f"{BASE_URL}/wait?call_sid={call_sid}")
    return Response(str(r), mimetype="text/xml")


@app.route("/wait", methods=["GET", "POST"])
def wait():
    call_sid = request.args.get("call_sid")
    state    = call_state.get(call_sid, "processing")

    r = VoiceResponse()

    if state in ("ready", "no_match"):
        r.play(f"{BASE_URL}/result?call_sid={call_sid}")
        call_state.pop(call_sid, None)

    elif state == "error":
        r.say("Une erreur est survenue. Veuillez rappeler.", language="fr-FR")
        call_state.pop(call_sid, None)
        call_audio.pop(call_sid, None)

    else:
        r.pause(length=3)
        r.redirect(f"{BASE_URL}/wait?call_sid={call_sid}")

    return Response(str(r), mimetype="text/xml")


@app.route("/result", methods=["GET"])
def result():
    call_sid   = request.args.get("call_sid")
    audio_file = call_audio.get(call_sid)

    if not audio_file:
        return "No audio found", 404

    # URL GitHub → on redirige Twilio directement
    if audio_file.startswith("http"):
        return Response(
            f'<?xml version="1.0" encoding="UTF-8"?><Response><Play>{audio_file}</Play></Response>',
            mimetype="text/xml"
        )

    # Fichier local (no_match.mp3)
    if os.path.exists(audio_file):
        return send_file(audio_file, mimetype="audio/mpeg")

    return "No audio found", 404


@app.route("/audio/<filename>", methods=["GET"])
def serve_audio(filename):
    path = os.path.join(BASE_DIR, filename)
    print(f"[AUDIO] serving: {path} | exists: {os.path.exists(path)}")
    if os.path.exists(path):
        return send_file(path)
    return "File not found", 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)