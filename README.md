# Orbit Wars Vibe Coding

This Hugging Face Space hosts a multi-agent system built on the Google Jules API that automatically writes and evaluates bots for the Kaggle `orbit_wars` competition.

## How it works

- **Workers:** Multiple Jules API sessions are created simultaneously. Each session is instructed to generate a Python bot for the competition.
- **Leader:** The background system extracts generated code from the Jules activities and runs local Kaggle Environment matches. New bots must defeat *all* previous top-performing bots to be accepted.
- **Leaderboard:** A Gradio UI displays the source code of the best bots found so far.

## Configuration

To run this locally or on a space, you must provide your Google Jules API key.

```bash
export JULES_API_KEY="your-key-here"
python3 app.py
```
