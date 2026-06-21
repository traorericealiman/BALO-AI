from flask import Flask, Response, request
from twilio.twiml.voice_response import VoiceResponse, Record
import requests
import os

app = Flask(__name__)

ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")

@app.route("/voice", methods=["GET", "POST"])
def voice():
    response = VoiceResponse()
    response.say("Bonjour, parlez apres le bip.", language="fr-FR")
    response.record(
        max_length=30,
        action="/handle-recording",
        recording_status_callback="/recording-status",
        play_beep=True,
        transcribe=False
    )
    return Response(str(response), mimetype="text/xml")

@app.route("/handle-recording", methods=["GET", "POST"])
def handle_recording():
    recording_url = request.form.get("RecordingUrl", "")

    print("=" * 40)
    print(f"URL audio : {recording_url}")
    print("=" * 40)

    # Télécharger le fichier audio
    audio_response = requests.get(
        recording_url + ".mp3",
        auth=(ACCOUNT_SID, AUTH_TOKEN)
    )

    if audio_response.status_code == 200:
        with open("recording.mp3", "wb") as f:
            f.write(audio_response.content)
        print("Audio sauvegardé : recording.mp3")
    else:
        print(f"Erreur téléchargement audio : {audio_response.status_code}")

    response = VoiceResponse()
    response.say("Bien recu. Merci.", language="fr-FR")
    return Response(str(response), mimetype="text/xml")

@app.route("/recording-status", methods=["GET", "POST"])
def recording_status():
    status = request.form.get("RecordingStatus")
    print(f"Status enregistrement : {status}")
    return "", 200

@app.route("/download-recording", methods=["GET"])
def download_recording():
    if os.path.exists("recording.mp3"):
        with open("recording.mp3", "rb") as f:
            return Response(
                f.read(),
                mimetype="audio/mpeg",
                headers={"Content-Disposition": "attachment; filename=recording.mp3"}
            )
    else:
        return "Aucun enregistrement trouvé", 404
if __name__ == "__main__":
    app.run(port=5000, debug=True)