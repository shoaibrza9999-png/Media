import os
import time
import queue
import threading
import tempfile
import traceback
import sys
import requests
import json
from kaggle_environments import make

JULES_API_KEY = os.getenv("JULES_API_KEY")

BASE_BOT = """
def agent(obs, conf):
    # Default bot doing nothing
    return [[0, 0, 0]]
"""

class Message:
    def __init__(self, sender_id, sender_name, msg_type, payload):
        self.sender_id = sender_id
        self.sender_name = sender_name
        self.msg_type = msg_type
        self.payload = payload

def evaluate_bot(new_code, best_code, num_matches=3):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f_new, \
         tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f_best:
        f_new.write(new_code)
        f_best.write(best_code)
        f_new_name = f_new.name
        f_best_name = f_best.name

    env = make("orbit_wars", configuration={"episodeSteps": 100})
    wins, crashes, details = 0, 0, ""

    try:
        for i in range(num_matches):
            out = env.run([f_new_name, f_best_name])
            if len(out) == 0:
                crashes += 1; details += f"Match {i}: No steps. "
                continue

            p1_status = out[-1][0]['status']
            r1 = out[-1][0]['reward'] or 0
            r2 = out[-1][1]['reward'] or 0
            if p1_status == 'ERROR': crashes += 1; details += f"Match {i}: Bot crashed. "
            elif r1 > r2: wins += 1

            out2 = env.run([f_best_name, f_new_name])
            p2_status = out2[-1][1]['status']
            r1_2 = out2[-1][0]['reward'] or 0
            r2_2 = out2[-1][1]['reward'] or 0
            if p2_status == 'ERROR': crashes += 1; details += f"Match {i} (p2): Bot crashed. "
            elif r2_2 > r1_2: wins += 1
    except Exception as e:
        crashes += 1; details += f"Exception: {e}\\n{traceback.format_exc()}"

    os.remove(f_new_name)
    os.remove(f_best_name)

    total_games = num_matches * 2
    if crashes > 0: return False, f"Crashed {crashes} times: {details}"
    if wins > total_games / 2: return True, f"Won {wins}/{total_games} matches!"
    return False, f"Won {wins}/{total_games} matches, not enough to beat previous."

class Leader(threading.Thread):
    def __init__(self, leader_queue, worker_queues):
        super().__init__()
        self.inbox = leader_queue
        self.worker_queues = worker_queues
        self.all_winning_bots = [BASE_BOT]
        self.daemon = True

    def run(self):
        print("[Leader] Started...")
        while True:
            try:
                msg = self.inbox.get(timeout=1)

                if msg.msg_type == 'SUBMIT':
                    print(f"[Leader] Evaluating bot from {msg.sender_name} against {len(self.all_winning_bots)} previous bots...")
                    all_success = True
                    details_log = ""
                    for idx, old_bot in enumerate(self.all_winning_bots):
                        success, details = evaluate_bot(msg.payload, old_bot, num_matches=2)
                        details_log += f"Vs Bot {idx}: {details}\n"
                        if not success:
                            all_success = False
                            break

                    if all_success:
                        print(f"[Leader] ACCEPTED! {msg.sender_name}'s bot beat all previous {len(self.all_winning_bots)} bots!")
                        self.all_winning_bots.append(msg.payload)
                        for q in self.worker_queues:
                            q.put(Message(-1, "Leader", "ANNOUNCE", f"New best bot by {msg.sender_name}!\\n{details_log}"))
                        with open(f"best_bot_{msg.sender_name}_{int(time.time())}.py", "w") as f:
                            f.write(msg.payload)
                    else:
                        self.worker_queues[msg.sender_id].put(Message(-1, "Leader", "FEEDBACK", f"Evaluation failed:\\n{details_log}"))
                elif msg.msg_type == 'CHAT':
                    for i, q in enumerate(self.worker_queues):
                        if i != msg.sender_id: q.put(msg)
            except queue.Empty:
                pass

class JulesWorker(threading.Thread):
    def __init__(self, worker_id, name, inbox, leader_queue):
        super().__init__()
        self.worker_id = worker_id
        self.name = name
        self.inbox = inbox
        self.leader_queue = leader_queue
        self.daemon = True
        self.session_id = None
        self.headers = {"X-Goog-Api-Key": JULES_API_KEY, "Content-Type": "application/json"}
        self.last_activity_count = 0

    def get_source(self):
        resp = requests.get('https://jules.googleapis.com/v1alpha/sources', headers=self.headers)
        if resp.status_code == 200 and resp.json().get('sources'):
            # Just take the first source available for the user's API key
            return resp.json()['sources'][0]['name'], "main"
        return "sources/github/shoaibrza9999-png/Orbital-war", "main"

    def create_session(self):
        source_name, branch = self.get_source()
        payload = {
            "prompt": f"You are {self.name}. Write a python bot for the Kaggle 'orbit_wars' competition. Ensure it has `def agent(obs, conf):` and returns `[[x, y, power]]`.\n\nCRITICAL: Do not just write the code to a file like submission.py. You MUST output the final code directly in your message or progress update wrapped in ```python ... ``` blocks so I can extract it.",
            "sourceContext": {
                "source": source_name,
                "githubRepoContext": {
                    "startingBranch": branch
                }
            },
            "title": f"Orbit Wars Bot - {self.name}"
        }
        resp = requests.post('https://jules.googleapis.com/v1alpha/sessions', headers=self.headers, json=payload)
        if resp.status_code == 200:
            self.session_id = resp.json().get("name").split("/")[-1]
            print(f"[{self.name}] Created Jules session: {self.session_id}")
        else:
            print(f"[{self.name}] Failed to create session: {resp.text}")

    def send_message(self, message):
        if not self.session_id: return
        payload = {"prompt": message}
        requests.post(f'https://jules.googleapis.com/v1alpha/sessions/{self.session_id}:sendMessage', headers=self.headers, json=payload)

    def check_activities(self):
        if not self.session_id: return
        resp = requests.get(f'https://jules.googleapis.com/v1alpha/sessions/{self.session_id}/activities', headers=self.headers)
        if resp.status_code == 200:
            activities = resp.json().get('activities', [])
            if len(activities) > self.last_activity_count:
                for act in activities[self.last_activity_count:]:
                    # Search for code in agent progress or standard messages
                    desc = ""
                    if act.get("progressUpdated"):
                        desc += act["progressUpdated"].get("description", "")
                    if act.get("chatMessage"):
                        desc += "\n" + act["chatMessage"].get("content", "")

                    if act.get("originator") == "agent" and desc:
                        # Try to extract python code block from Jules activity
                        code_matches = re.findall(r'```python(.*?)```', desc, re.DOTALL)
                        if code_matches:
                            code = code_matches[0].strip()
                            self.leader_queue.put(Message(self.worker_id, self.name, "SUBMIT", code))
                        elif "Message from" in desc:
                            self.leader_queue.put(Message(self.worker_id, self.name, "CHAT", desc))
                self.last_activity_count = len(activities)

    def run(self):
        print(f"[{self.name}] Starting...")
        if not JULES_API_KEY:
            print(f"[{self.name}] JULES_API_KEY missing. Cannot use Jules API.")
            return

        self.create_session()

        while True:
            while not self.inbox.empty():
                msg = self.inbox.get()
                if msg.msg_type in ['ANNOUNCE', 'FEEDBACK', 'CHAT']:
                    self.send_message(f"Update: {msg.payload}")

            self.check_activities()
            time.sleep(10)

def start_agents():
    num_workers = 3
    leader_queue = queue.Queue()
    worker_queues = [queue.Queue() for _ in range(num_workers)]

    leader = Leader(leader_queue, worker_queues)
    leader.start()

    for i in range(num_workers):
        JulesWorker(i, f"Agent-{i+1}", worker_queues[i], leader_queue).start()

if __name__ == "__main__":
    start_agents()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt: pass
