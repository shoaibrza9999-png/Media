import os
import time
import queue
import threading
import tempfile
import re
import traceback
import sys
from kaggle_environments import make
import litellm

# Set API key and model through environment variables
MODEL_NAME = os.getenv("LLM_MODEL", "gpt-4o-mini")
print(f"Using model: {MODEL_NAME}")

BASE_BOT = """
def agent(obs, conf):
    # Default bot doing nothing
    return [[0, 0, 0]]
"""

class Message:
    def __init__(self, sender_id, sender_name, msg_type, payload):
        self.sender_id = sender_id
        self.sender_name = sender_name
        self.msg_type = msg_type  # 'SUBMIT', 'CHAT', 'ANNOUNCE', 'FEEDBACK'
        self.payload = payload

def evaluate_bot(new_code, best_code, num_matches=3):
    """
    Evaluates new_code against best_code for a given number of matches.
    Returns (success_boolean, details_string).
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f_new, \
         tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f_best:
        f_new.write(new_code)
        f_best.write(best_code)
        f_new_name = f_new.name
        f_best_name = f_best.name

    env = make("orbit_wars", configuration={"episodeSteps": 100}) # Shorter steps for faster evaluation

    wins = 0
    crashes = 0
    details = ""

    try:
        for i in range(num_matches):
            # Play as player 1
            out = env.run([f_new_name, f_best_name])
            if len(out) == 0:
                crashes += 1
                details += f"Match {i}: Environment returned no steps. "
                continue

            p1_status = out[-1][0]['status']
            r1 = out[-1][0]['reward'] or 0
            r2 = out[-1][1]['reward'] or 0

            if p1_status == 'ERROR':
                crashes += 1
                details += f"Match {i}: Bot crashed. "
            elif r1 > r2:
                wins += 1

            # Play as player 2
            out2 = env.run([f_best_name, f_new_name])
            p2_status = out2[-1][1]['status']
            r1_2 = out2[-1][0]['reward'] or 0
            r2_2 = out2[-1][1]['reward'] or 0

            if p2_status == 'ERROR':
                crashes += 1
                details += f"Match {i} (p2): Bot crashed. "
            elif r2_2 > r1_2:
                wins += 1
    except Exception as e:
        crashes += 1
        details += f"Exception during eval: {e}\n{traceback.format_exc()}"

    os.remove(f_new_name)
    os.remove(f_best_name)

    total_games = num_matches * 2
    if crashes > 0:
        return False, f"Crashed or errored {crashes} times: {details}"
    if wins > total_games / 2:
        return True, f"Won {wins}/{total_games} matches!"
    return False, f"Won {wins}/{total_games} matches, not enough to beat current best."


class Leader(threading.Thread):
    def __init__(self, leader_queue, worker_queues):
        super().__init__()
        self.inbox = leader_queue
        self.worker_queues = worker_queues
        self.all_winning_bots = [BASE_BOT]
        self.daemon = True

    def run(self):
        print("[Leader] Started and listening for submissions...")
        while True:
            try:
                msg = self.inbox.get(timeout=1)

                if msg.msg_type == 'SUBMIT':
                    print(f"[Leader] Evaluating new bot from {msg.sender_name} against {len(self.all_winning_bots)} previous bots...")

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
                        # Broadcast success
                        for q in self.worker_queues:
                            q.put(Message(-1, "Leader", "ANNOUNCE", f"New best bot by {msg.sender_name}! Details:\n{details_log}\nHere is the code to improve upon:\n```python\n{msg.payload}\n```"))
                        # Also save to disk
                        with open(f"best_bot_{msg.sender_name}_{int(time.time())}.py", "w") as f:
                            f.write(msg.payload)
                    else:
                        print(f"[Leader] REJECTED {msg.sender_name}'s bot. It failed against one of the previous bots.")
                        self.worker_queues[msg.sender_id].put(Message(-1, "Leader", "FEEDBACK", f"Bot evaluation failed:\n{details_log}"))

                elif msg.msg_type == 'CHAT':
                    print(f"[Leader] Forwarding chat from {msg.sender_name}")
                    for i, q in enumerate(self.worker_queues):
                        if i != msg.sender_id:
                            q.put(msg)

            except queue.Empty:
                pass


class Worker(threading.Thread):
    def __init__(self, worker_id, name, inbox, leader_queue):
        super().__init__()
        self.worker_id = worker_id
        self.name = name
        self.inbox = inbox
        self.leader_queue = leader_queue
        self.daemon = True
        self.messages_history = [
            {"role": "system", "content": f"You are a vibe coding AI agent named {self.name} participating in the Kaggle 'orbit_wars' competition. "
                                          "Your goal is to write a Python bot that wins. "
                                          "You must return Python code enclosed in ```python ... ``` blocks. "
                                          "The environment expects a function `def agent(obs, conf):` which returns a list of moves `[[x, y, power]]`. "
                                          "If you want to just chat with other agents, do not include code blocks. "
                                          "The leader will automatically evaluate any code block you send. "
                                          "Start with simple strategies and improve them based on feedback."}
        ]

    def run(self):
        print(f"[{self.name}] Started.")
        # Initial submission
        self.messages_history.append({"role": "user", "content": "Please write an initial basic bot for orbit_wars. Make sure it has the `def agent(obs, conf):` signature and returns a list of moves like `[[1, 0, 0]]` or similar."})

        while True:
            # Check inbox
            while not self.inbox.empty():
                msg = self.inbox.get()
                if msg.msg_type in ['ANNOUNCE', 'FEEDBACK', 'CHAT']:
                    self.messages_history.append({"role": "user", "content": f"Message from {msg.sender_name}: {msg.payload}"})

            try:
                # Keep history size manageable to avoid context window limit
                if len(self.messages_history) > 20:
                    # Keep system prompt (index 0) and last 10 messages
                    self.messages_history = [self.messages_history[0]] + self.messages_history[-10:]

                # Call LLM
                response = litellm.completion(model=MODEL_NAME, messages=self.messages_history)
                reply = response.choices[0].message.content
                self.messages_history.append({"role": "assistant", "content": reply})

                # Extract code if present
                code_matches = re.findall(r'```python\n(.*?)```', reply, re.DOTALL)
                if not code_matches:
                    code_matches = re.findall(r'```(.*?)```', reply, re.DOTALL)

                if code_matches:
                    code = code_matches[0].strip()
                    print(f"[{self.name}] Submitted a new bot.")
                    self.leader_queue.put(Message(self.worker_id, self.name, "SUBMIT", code))
                else:
                    print(f"[{self.name}] Sent a chat message.")
                    self.leader_queue.put(Message(self.worker_id, self.name, "CHAT", reply))

            except Exception as e:
                print(f"[{self.name}] LLM Error: {e}")

            # Wait a bit before next action to avoid API spam
            time.sleep(20)

if __name__ == "__main__":
    num_workers = 3
    leader_queue = queue.Queue()
    worker_queues = [queue.Queue() for _ in range(num_workers)]

    leader = Leader(leader_queue, worker_queues)
    leader.start()

    workers = []
    for i in range(num_workers):
        w = Worker(i, f"Agent-{i+1}", worker_queues[i], leader_queue)
        workers.append(w)
        w.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting...")
