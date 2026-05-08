import gradio as gr
import subprocess
import threading
import json
import os

# Start the multi-agent system in a background thread
def run_agents():
    subprocess.run(["python3", "orbit_wars_agents.py"])

agent_thread = threading.Thread(target=run_agents, daemon=True)
agent_thread.start()

def get_leaderboard():
    bots = []
    # Find all best_bot files saved by the Leader
    for file in os.listdir("."):
        if file.startswith("best_bot_") and file.endswith(".py"):
            with open(file, "r") as f:
                bots.append({"name": file, "code": f.read()})

    if not bots:
        return "No winning bots yet. The agents are vibing and coding..."

    # Sort by timestamp (in the filename)
    bots.sort(key=lambda x: x["name"], reverse=True)

    markdown_content = "# Orbit Wars - Top Bots\n\n"
    # Show the top 10 recent best bots
    for i, bot in enumerate(bots[:10]):
        markdown_content += f"## Rank {i+1}: {bot['name']}\n```python\n{bot['code']}\n```\n\n"

    return markdown_content

with gr.Blocks() as demo:
    gr.Markdown("# Vibe Coding Agents: Orbit Wars")
    gr.Markdown("This Hugging Face Space hosts a multi-agent system attempting to solve the Kaggle `orbit_wars` competition. The Leader agent locally evaluates bots on this space against all previous winning bots, maintaining the leaderboard.")

    leaderboard = gr.Markdown(get_leaderboard())
    refresh_btn = gr.Button("Refresh Leaderboard")

    refresh_btn.click(fn=get_leaderboard, inputs=[], outputs=leaderboard)

demo.launch(server_name="0.0.0.0", server_port=7860)
