# Alert AI

## Overview
Prometheus Alert → AI → Telegram bot that analyzes alert groups and generates human-readable summaries.

## Setup
1. Clone the repository:
```bash
git clone https://github.com/punk-link/alert-ai.git
cd alert-ai
```

2. Create a `.env` file with required variables:
```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHANNEL_ID=@channel_name_or_id
ANTHROPIC_API_KEY=your_anthropic_key
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage
```bash
uvicorn main:app --reload
```

## Dependencies
- FastAPI
- Anthropic API
- Python-dotenv
- aiogram
- pydantic

## Notes
- The AI model version (claude-3-5-sonnet-20241022) may need updating to the latest available version
- Ensure your Anthropic API key has sufficient tokens
- Telegram channel must be set up with appropriate permissions

[View on GitHub](https://github.com/punk-link/alert-ai)
```

```tool
TOOL_NAME: run_terminal_command
BEGIN_ARG: command
"cd alert-ai && git add README.md && git commit -m 'Add README'"