# Telegram Forwarder

A Python script using Telethon to automatically forward messages from a source chat/group/channel to a target destination.

## Features

- Forward messages from any Telegram chat, group, or channel
- **Multiple source/target mapping support**
- **One-to-many and many-to-one forwarding**
- **Saved Messages (`me`) support as source or target**
- Support for both user accounts and bot accounts
- Optional removal of "Forward from..." signature
- Optional quiet mode for console logging
- **Catchup mode** – replay missed messages on restart
- **JSON state persistence** – tracks the last processed message per source
- **Anti-FloodWait retries** – automatic back-off and retry on rate limits
- Comprehensive logging
- Easy configuration via environment variables

## Prerequisites

1. **Telegram API Credentials**: Get your `api_id` and `api_hash` from [https://my.telegram.org](https://my.telegram.org)
2. **Bot Token** (optional): If you want to use a bot account, get a bot token from [@BotFather](https://t.me/BotFather)
3. **Chat IDs**: You need the IDs of the source and target chats/groups/channels

## Installation

1. Clone this repository:
```bash
git clone https://github.com/Linuxmaster14/TGForwarder.git
cd TGForwarder
```

2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file based on the example:
```bash
cp .env.example .env
```

4. Edit the `.env` file and fill in your credentials:

**Option 1: Single Source/Target (Legacy)**
```env
API_ID=your_api_id_here
API_HASH=your_api_hash_here
BOT_TOKEN=your_bot_token_here  # Optional, for bot mode
SOURCE_ID=your_source_chat_id
TARGET_ID=your_target_chat_id
```

**Option 2: Multiple Sources/Targets (Recommended)**
```env
API_ID=your_api_id_here
API_HASH=your_api_hash_here
BOT_TOKEN=your_bot_token_here  # Optional, for bot mode
FORWARDING_RULES=-1001111111111:-1002222222222,-1003333333333:-1004444444444
```

## Getting Chat IDs

To find chat IDs, you can:

1. **For private chats**: Use the user's ID (positive number)
2. **For groups/channels**: Use the negative ID format
   - For groups: `-100` + group ID (e.g., `-1001234567890`)
   - For channels: `-100` + channel ID (e.g., `-1001234567890`)
3. **For Saved Messages**: Use the special value `me`

You can use tools like [@userinfobot](https://t.me/userinfobot) or [@get_id_bot](https://t.me/get_id_bot) to get chat IDs.

## Usage

Run the script with various options:

```bash
# Basic usage
python telegram_forwarder.py

# Remove "Forward from..." signature (sends as new messages)
python telegram_forwarder.py --remove-forward-signature

# Disable console logging (only log to file)
python telegram_forwarder.py --disable-console-log

# Replay messages missed since the last run, then continue live
python telegram_forwarder.py --catchup

# First run: replay the last 50 messages from each source, then go live
python telegram_forwarder.py --catchup --catchup-limit 50

# First run: replay the full history from each source, then go live
python telegram_forwarder.py --catchup --catchup-limit 0

# Use a custom state file location
python telegram_forwarder.py --state-file /var/lib/tgforwarder/state.json

# Forget all previously tracked positions and start fresh
python telegram_forwarder.py --reset-state

# Combine options
python telegram_forwarder.py -r -q --catchup
```

### Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--remove-forward-signature` | `-r` | Remove "Forward from..." signature by sending as new messages instead of forwarding |
| `--disable-console-log` | `-q` | Disable console logging (only log to telegram_forwarder.log file) |
| `--catchup` | | Forward messages missed since the last run before resuming live forwarding. If no prior state exists, performs an initial catchup (see `--catchup-limit`) |
| `--catchup-limit N` | | Maximum messages to fetch during an **initial** catchup (no prior state). `0` = full history (default). `N > 0` = last N messages only |
| `--state-file FILE` | | Path to the JSON state file (default: `forwarder_state.json`) |
| `--reset-state` | | Delete the state file before starting so all positions are forgotten |

### First Run

- **User Mode**: If you're not using a bot token, you'll be prompted to enter your phone number and verification code
- **Bot Mode**: If you provided a bot token, the script will start immediately

The script will run continuously and forward any new messages from the source to the target.

## Configuration Options

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `API_ID` | Yes | Your Telegram API ID |
| `API_HASH` | Yes | Your Telegram API Hash |
| `BOT_TOKEN` | No | Bot token for bot mode (leave empty for user mode) |
| `SOURCE_ID` | No* | ID of the source chat/group/channel, or `me` (legacy single mode) |
| `TARGET_ID` | No* | ID of the target chat/group/channel, or `me` (legacy single mode) |
| `FORWARDING_RULES` | No* | Multiple forwarding rules (see format below) |

*Either `SOURCE_ID`/`TARGET_ID` OR `FORWARDING_RULES` must be provided.

### Forwarding Rules Format

The `FORWARDING_RULES` environment variable supports flexible mapping.  
Use `me` (case-insensitive) anywhere in place of a numeric ID to refer to your **Saved Messages** chat.

**Format**: `source_id:target_id1:target_id2,source_id2:target_id3`

**Examples**:
```env
# One-to-one mapping
FORWARDING_RULES=-1001111111111:-1002222222222

# One-to-many (one source to multiple targets)
FORWARDING_RULES=-1001111111111:-1002222222222:-1003333333333

# Many-to-one (multiple sources to one target)
FORWARDING_RULES=-1001111111111:-1004444444444,-1002222222222:-1004444444444

# Saved Messages as source (forward your own saved messages to a group)
FORWARDING_RULES=me:-1001111111111

# Saved Messages as target (archive a channel into your Saved Messages)
FORWARDING_RULES=-1001111111111:me

# Complex mapping
FORWARDING_RULES=-1001111111111:-1002222222222,-1001111111111:-1003333333333,-1004444444444:-1005555555555
```

## Forwarding Patterns

The script supports various forwarding patterns:

### 1. One-to-One Forwarding
Forward messages from one source to one target:
```env
FORWARDING_RULES=-1001111111111:-1002222222222
```

### 2. One-to-Many Forwarding
Forward messages from one source to multiple targets:
```env
FORWARDING_RULES=-1001111111111:-1002222222222:-1003333333333:-1004444444444
```

### 3. Many-to-One Forwarding
Forward messages from multiple sources to one target:
```env
FORWARDING_RULES=-1001111111111:-1005555555555,-1002222222222:-1005555555555,-1003333333333:-1005555555555
```

### 4. Complex Mapping
Mix of different patterns:
```env
FORWARDING_RULES=-1001111111111:-1002222222222,-1001111111111:-1003333333333,-1004444444444:-1005555555555:-1006666666666
```

### User Mode vs Bot Mode

- **User Mode**: Uses your personal Telegram account. Can access any chat you're a member of.
- **Bot Mode**: Uses a bot account. The bot must be added to both source and target chats with appropriate permissions.

## State Persistence & Catchup

The forwarder saves the **last processed message ID** for every source channel in a JSON file (default: `forwarder_state.json`).  
This allows it to resume after a restart without forwarding duplicates or losing messages.

```json
{
  "-1001111111111": 123456,
  "987654321": 78900
}
```

### Catchup mode (`--catchup`)

When started with `--catchup`, the forwarder will:

1. Read the state file to find the last known message ID for each source.
2. **Incremental catchup** (state exists): fetch and forward all messages that arrived after that ID, in chronological order.
3. **Initial catchup** (no state yet): fetch and forward messages from scratch, controlled by `--catchup-limit`.
4. Switch to normal live-forwarding once catchup is complete.

#### `--catchup-limit N`

Controls how many messages are fetched during an **initial** catchup (i.e. when no state file exists for a source):

| Value | Behaviour |
|-------|-----------|
| `0` (default) | Fetch the **full history** of the source chat |
| `N > 0` | Fetch only the **last N messages** of the source chat |

Messages are always forwarded in chronological order (oldest first).

**Examples**

```bash
# First run – replay the last 50 messages from each source, then go live
python telegram_forwarder.py --catchup --catchup-limit 50

# First run – replay the entire history of each source, then go live
python telegram_forwarder.py --catchup --catchup-limit 0

# Subsequent runs – incremental catchup (--catchup-limit is ignored when state exists)
python telegram_forwarder.py --catchup
```

> **Note**: After an initial catchup the state file is updated to the most recent message ID from the catchup batch.  
> Subsequent runs with `--catchup` will therefore only forward messages that arrived after that point (incremental mode).

### Resetting state (`--reset-state`)

Use `--reset-state` to delete the state file before starting.  
This is useful when you want to change your forwarding rules completely or recover from a corrupted state.

```bash
python telegram_forwarder.py --reset-state
```

### Custom state file (`--state-file`)

Keep the state file anywhere you like:

```bash
python telegram_forwarder.py --state-file /var/lib/tgforwarder/state.json
```

## Anti-FloodWait Retries

All Telegram API calls that forward or send messages are wrapped in an automatic retry loop.  
If Telegram responds with a `FloodWaitError`, the script:

1. Logs the required wait time.
2. Sleeps for `wait + 1` seconds.
3. Retries the same call (up to **5** attempts by default).
4. Skips the message and logs an error only if all retries are exhausted.

This prevents the forwarder from crashing during high-volume forwarding sessions.

## Important Notes

1. **Rate Limits**: The script automatically handles Telegram's rate limits with retries and back-off
2. **Permissions**: Ensure the account/bot has necessary permissions in both source and target chats
3. **Privacy**: Be mindful of privacy and legal considerations when forwarding messages
4. **Session Files**: The script creates session files (`user_session.session` or `bot_session.session`) to avoid re-authentication
5. **Saved Messages**: Using `me` as source or target requires **user mode** (not bot mode)

## Logging

The script provides detailed logging including:
- Connection status
- Message forwarding events
- Catchup progress
- Error handling
- Rate limit notifications

### Log Output
- **Default**: Logs to both console and `telegram_forwarder.log` file
- **Quiet mode** (`-q` flag): Logs only to `telegram_forwarder.log` file

### Forward Signature Options
- **Default**: Messages are forwarded with "Forward from..." signature
- **Remove signature** (`-r` flag): Messages are sent as new messages without the forward signature

## Troubleshooting

### Common Issues

1. **Authentication Failed**: Check your API credentials
2. **Permission Denied**: Ensure the account/bot has access to both chats
3. **Invalid Chat ID**: Verify the chat IDs are correct
4. **Rate Limited**: The script handles this automatically with retries
5. **Saved Messages not working**: Make sure you are running in user mode (no `BOT_TOKEN`)

### Error Messages

- `Missing required environment variables`: Check your `.env` file
- `SOURCE_ID and TARGET_ID must be valid integers or 'me'`: Ensure IDs are numbers or the literal string `me`
- `Error getting entity info`: The account/bot cannot access the specified chat

## License

This project is licensed under the terms specified in the [`LICENSE`](./LICENSE) file.

## Author

Made with [Linuxmaster14](https://github.com/Linuxmaster14)

## Disclaimer

This tool is for educational and personal use. Please respect Telegram's Terms of Service and applicable laws regarding message forwarding and privacy.
