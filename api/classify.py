import json
from http.server import BaseHTTPRequestHandler
from google import genai
from google.genai import types

_client = genai.Client()  # reads GEMINI_API_KEY automatically


def ask(system, user, tokens=2000):
    r = _client.models.generate_content(
        model="gemini-2.5-flash", contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system, response_mime_type="application/json",
            max_output_tokens=tokens, thinking_config=types.ThinkingConfig(thinking_budget=0)))
    return json.loads(r.text)


KB = [
    {"id": "KB-01", "topic": "Billing", "title": "Duplicate or incorrect charge", "text": "We are sorry about the billing issue. We have flagged the charge for review, and the billing team will confirm the outcome within 3 business days. Any confirmed duplicate charge is refunded to the original payment method."},
    {"id": "KB-02", "topic": "Technical", "title": "Service error or outage", "text": "Thank you for reporting this. Please share the steps that lead to the problem, the time it happened, and a screenshot if possible. Our technical team will investigate and update you within 1 business day."},
    {"id": "KB-03", "topic": "Account", "title": "Login and access", "text": "To regain access, please use the Forgot password link on the sign-in page. If the reset email does not arrive within 10 minutes, reply here and we will verify your identity and help manually."},
    {"id": "KB-04", "topic": "Feature", "title": "Feature request", "text": "Thank you for the suggestion. We have recorded it with our product team. We cannot promise a delivery date, but we will let you know if it is scheduled."},
    {"id": "KB-05", "topic": "General", "title": "General enquiry", "text": "Thank you for getting in touch. Here is the information that should answer your question. If anything is still unclear, reply and we will be glad to help."},
]
TEAMS = {"Billing": "Billing & Finance", "Technical": "Technical Support", "Account": "Account Services", "Feature": "Product Team", "General": "Customer Success", "Legal": "Legal & Compliance"}
SENSITIVE = ["lawyer", "legal action", "lawsuit", "sue", "gdpr", "breach", "chargeback", "harass", "discriminat", "press", "regulator", "fraud", "threat"]
SYSTEM = """You are a support triage assistant. Classify the email and draft a reply.
Rules:
- Choose topic from: Billing, Technical, Account, Feature, General, Legal.
- Choose urgency from: High, Medium, Low.
- Draft the reply ONLY from the approved guidance below. Pick the single best entry by id. If none fits, set kb_id to null and write a short holding reply promising a human follow-up.
- Never promise refunds, dates, or outcomes beyond what the guidance says.
- Set sensitive=true for legal threats, privacy or security incidents, harassment, fraud, or media/regulator contact.
- confidence is a number from 0 to 1.
Return ONLY JSON: {"topic":"","urgency":"","confidence":0,"sensitive":false,"reason":"","kb_id":"","draft":""}
Approved guidance:
""" + "\n".join(f'{k["id"]} ({k["topic"]}) {k["title"]}: {k["text"]}' for k in KB)


class handler(BaseHTTPRequestHandler):
    def send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("content-length", 0) or 0)) or b"{}")
        except ValueError:
            return self.send(400, {"error": "Invalid JSON"})
        frm, subject, body = d.get("from", ""), d.get("subject", ""), d.get("body", "")
        if not (subject + body).strip():
            return self.send(400, {"error": "Empty email"})
        try:
            ai = ask(SYSTEM, f"From: {frm}\nSubject: {subject}\n\n{body}", 800)
            text = (subject + " " + body).lower()
            kw = [k for k in SENSITIVE if k in text]
            kb = next((k for k in KB if k["id"] == ai.get("kb_id")), None)
            conf = float(ai.get("confidence", 0))
            reasons = []
            # Safety layer in code, so escalation never depends on the model alone
            if ai.get("sensitive") or kw:
                reasons.append("Sensitive content" + (f" ({', '.join(kw)})" if kw else "") + ". A person must handle this case.")
            if conf < 0.6:
                reasons.append(f"Low confidence ({round(conf * 100)}%). A person should confirm the topic.")
            if not kb:
                reasons.append("No approved guidance matched this email.")
            topic = ai.get("topic") if ai.get("topic") in TEAMS else "General"
            self.send(200, {"topic": topic, "urgency": ai.get("urgency"), "team": TEAMS[topic], "confidence": round(conf * 100),
                            "escalate": bool(reasons), "reasons": reasons,
                            "source": f'{kb["id"]} · {kb["title"]}' if kb else "None", "why": ai.get("reason", ""), "draft": ai.get("draft", "")})
        except Exception as e:
            self.send(500, {"error": str(e)})