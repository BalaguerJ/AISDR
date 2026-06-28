import json, os, datetime

path = "backend/campaigns/test-sim-campaign-5.json"
if os.path.exists(path):
    with open(path, "r") as f:
        data = json.load(f)
    if "created_at" not in data:
        data["created_at"] = datetime.datetime.now().isoformat()
    with open(path, "w") as f:
        json.dump(data, f)
