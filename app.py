from flask import Flask, request
from twilio.twiml.voice_response import VoiceResponse, Gather
import os

app = Flask(__name__)

@app.route("/voice", methods=["GET", "POST"])
def voice():
    response = VoiceResponse()

    gather = Gather(
        input="speech dtmf",
        action="/respond",
        method="POST",
        language="fr-FR",
        speech_timeout="auto"
    )

    gather.say("Bonjour, parlez après le bip.", language="fr-FR")
    response.append(gather)

    return str(response), 200, {"Content-Type": "text/xml"}


@app.route("/respond", methods=["GET", "POST"])
def respond():
    speech = request.form.get("SpeechResult", "")
    confidence = request.form.get("Confidence", "")

    print("=" * 40)
    print("Utilisateur :", speech)
    print("Confiance :", confidence)
    print("=" * 40)

    response = VoiceResponse()
    response.say("Bien noté. Merci.", language="fr-FR")

    return str(response), 200, {"Content-Type": "text/xml"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)