import base64
encoded = base64.b64encode(open("generator/firebase-key.json", "rb").read()).decode()
print(encoded)
