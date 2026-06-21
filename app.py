from flask import Flask, Response, request
from twilio.twiml.voice_response import VoiceResponse, Gather

app = Flask(__name__)

@app.route("/voice", methods=["GET", "POST"])
def voice():
    response = VoiceResponse()
    gather = Gather(
        input="speech",
        action="/respond",
        method="POST",
        language="fr-FR",
        speech_timeout="auto"
    )
    gather.say("Bonjour, parlez apres le bip.", language="fr-FR")
    response.append(gather)
    return Response(str(response), mimetype="text/xml")

@app.route("/respond", methods=["GET", "POST"])
def respond():
    speech = request.form.get("SpeechResult", "")
    confidence = request.form.get("Confidence", "")
    
    # Affichage dans le terminal
    print("=" * 40)
    print(f"Ce que l'utilisateur a dit : {speech}")
    print(f"Confiance : {confidence}")
    print("=" * 40)
    
    # Réponse au caller
    response = VoiceResponse()
    response.say("Bien note. Merci.", language="fr-FR")
    return Response(str(response), mimetype="text/xml")

if __name__ == "__main__":
    app.run(port=5000, debug=True)