from flask import Flask, Response, request
from twilio.twiml.voice_response import VoiceResponse, Record

app = Flask(__name__)

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
    print(f"Audio reçu : {recording_url}")
    print("=" * 40)
    
    response = VoiceResponse()
    response.say("Bien recu. Merci.", language="fr-FR")
    return Response(str(response), mimetype="text/xml")

@app.route("/recording-status", methods=["GET", "POST"])
def recording_status():
    print("Status:", request.form.get("RecordingStatus"))
    return "", 200

if __name__ == "__main__":
    app.run(port=5000, debug=True)