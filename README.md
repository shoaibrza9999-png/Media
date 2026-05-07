# Orbit Wars Agents

This is an autonomous framework where multiple AI agents compete and collaborate to build the best bot for the Kaggle `orbit_wars` competition.

## Overview

The system consists of:
- **Leader**: Evaluates submitted bots. If a new bot performs better than the current best bot, it makes the new bot the standard and broadcasts its code to all workers. It evaluates bots locally by matching them against the current best.
- **Workers (Vibe Coding Agents)**: Try to write winning Python bots. They are prompted with the current best code, receive feedback from the leader (win/loss/crash details), and can chat with each other to exchange ideas.

## Requirements

1. Install requirements:
   ```bash
   pip install kaggle-environments litellm
   ```

2. Set your LLM provider API key in your environment (e.g., `OPENAI_API_KEY` for OpenAI models, or `ANTHROPIC_API_KEY` for Anthropic).

   You can also specify the model:
   ```bash
   export LLM_MODEL="gpt-4o-mini" # or "claude-3-5-sonnet-20241022", etc.
   export OPENAI_API_KEY="..."
   ```

## Running

Run the script:

```bash
python3 orbit_wars_agents.py
```

The script will keep running indefinitely, saving the best bot whenever a worker finds a better one.
