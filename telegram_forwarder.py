import asyncio
import json
import logging
import os
import argparse
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.tl.types import PeerUser, PeerChat, PeerChannel

# Load environment variables
load_dotenv()

# Maximum number of retries for FloodWait errors
MAX_RETRIES = 5

# Delay in seconds between forwarded messages during catchup to reduce rate-limit risk
CATCHUP_DELAY = 10.0


def setup_logging(disable_console=False):
    """Configure logging based on console preference."""
    if disable_console:
        # Only log to file, not console
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('telegram_forwarder.log'),
            ]
        )
    else:
        # Log to both console and file
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('telegram_forwarder.log')
            ]
        )


logger = logging.getLogger(__name__)


async def with_flood_wait(coro_func, max_retries=MAX_RETRIES):
    """Execute a zero-argument coroutine factory, retrying on FloodWaitError.

    Args:
        coro_func: A callable that returns a new coroutine each time it is called.
        max_retries: Maximum number of attempts before re-raising the error.
    """
    for attempt in range(max_retries):
        try:
            return await coro_func()
        except FloodWaitError as e:
            wait = e.seconds + 1
            if attempt < max_retries - 1:
                logger.warning(
                    f"FloodWait: sleeping {wait}s (attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    f"FloodWait: max retries ({max_retries}) reached, giving up"
                )
                raise


class TelegramForwarder:
    def __init__(self, remove_forward_signature=False, catchup=False,
                 catchup_limit=0, state_file='forwarder_state.json',
                 reset_state=False):
        """Initialize the Telegram forwarder with environment variables."""
        self.api_id = os.getenv('API_ID')
        self.api_hash = os.getenv('API_HASH')
        self.bot_token = os.getenv('BOT_TOKEN')
        self.remove_forward_signature = remove_forward_signature
        self.catchup = catchup
        self.catchup_limit = catchup_limit
        self.state_file = state_file

        # Check for legacy single source/target configuration
        self.source_id = os.getenv('SOURCE_ID')
        self.target_id = os.getenv('TARGET_ID')
        self.forwarding_rules = os.getenv('FORWARDING_RULES')

        # Validate required environment variables
        if not all([self.api_id, self.api_hash]):
            raise ValueError("Missing API_ID or API_HASH. Check your .env file.")

        # Parse forwarding configuration
        self.forwarding_map = self._parse_forwarding_rules()

        if not self.forwarding_map:
            raise ValueError(
                "No forwarding rules configured. "
                "Set either SOURCE_ID/TARGET_ID or FORWARDING_RULES."
            )

        # Handle state persistence
        if reset_state:
            self._reset_state()
        self.state = self._load_state()

        # Initialize Telegram client
        if self.bot_token:
            # Bot mode
            self.client = TelegramClient('bot_session', self.api_id, self.api_hash)
            logger.info("Initialized in bot mode")
        else:
            # User mode
            self.client = TelegramClient('user_session', self.api_id, self.api_hash)
            logger.info("Initialized in user mode")

    # ------------------------------------------------------------------
    # ID parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_id(s):
        """Parse a chat ID string.

        Accepts:
        - The special string ``me`` (case-insensitive) for Saved Messages.
        - Any integer string (positive or negative).
        """
        s = s.strip().lower()
        if s == 'me':
            return 'me'
        return int(s)

    def _parse_forwarding_rules(self):
        """Parse forwarding rules from environment variables."""
        forwarding_map = {}

        # Check for legacy single source/target configuration
        if self.source_id and self.target_id:
            try:
                source_id = self._parse_id(self.source_id)
                target_id = self._parse_id(self.target_id)
                forwarding_map[source_id] = [target_id]
                logger.info("Using legacy single source/target configuration")
                return forwarding_map
            except ValueError:
                raise ValueError(
                    "SOURCE_ID and TARGET_ID must be valid integers or 'me'."
                )

        # Parse new multiple forwarding rules
        if self.forwarding_rules:
            try:
                # Format: source1:target1:target2,source2:target3,source3:target4
                # 'me' is accepted in place of any numeric ID.
                rules = self.forwarding_rules.split(',')
                for rule in rules:
                    rule = rule.strip()
                    if not rule:
                        continue

                    parts = rule.split(':')
                    if len(parts) < 2:
                        raise ValueError(f"Invalid forwarding rule format: {rule}")

                    source_id = self._parse_id(parts[0])
                    target_ids = [self._parse_id(t) for t in parts[1:]]

                    if source_id in forwarding_map:
                        # Extend existing targets for this source
                        forwarding_map[source_id].extend(target_ids)
                    else:
                        forwarding_map[source_id] = target_ids

                logger.info(f"Parsed {len(forwarding_map)} forwarding rules")
                return forwarding_map

            except ValueError as e:
                raise ValueError(f"Error parsing FORWARDING_RULES: {e}")

        return {}

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self):
        """Load the last-processed-message state from the JSON file."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(
                    f"Could not load state file '{self.state_file}': {e}. "
                    "Starting with empty state."
                )
        return {}

    def _save_state(self):
        """Persist the current state to the JSON file."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except IOError as e:
            logger.error(f"Could not save state file '{self.state_file}': {e}")

    def _reset_state(self):
        """Delete the state file so the next run starts without prior context."""
        if os.path.exists(self.state_file):
            os.remove(self.state_file)
            logger.info(f"State file '{self.state_file}' has been reset.")
        else:
            logger.info(
                f"State file '{self.state_file}' does not exist, nothing to reset."
            )

    def _update_state(self, source_id, message_id):
        """Record the last successfully processed message ID for a source."""
        key = str(source_id)
        if key not in self.state or message_id > self.state[key]:
            self.state[key] = message_id
            self._save_state()

    # ------------------------------------------------------------------
    # Entity resolution
    # ------------------------------------------------------------------

    async def _resolve_entities(self):
        """Replace the ``'me'`` placeholder with the actual numeric user ID.

        Must be called after the client is connected so that ``get_me()``
        is available.
        """
        me_id = None
        resolved_map = {}

        for source_id, target_ids in self.forwarding_map.items():
            if source_id == 'me':
                if me_id is None:
                    me = await self.client.get_me()
                    me_id = me.id
                resolved_source = me_id
            else:
                resolved_source = source_id

            resolved_targets = []
            for target_id in target_ids:
                if target_id == 'me':
                    if me_id is None:
                        me = await self.client.get_me()
                        me_id = me.id
                    resolved_targets.append(me_id)
                else:
                    resolved_targets.append(target_id)

            resolved_map[resolved_source] = resolved_targets

        self.forwarding_map = resolved_map
        if me_id is not None:
            logger.info(f"Resolved 'me' to user ID {me_id} (Saved Messages)")

    # ------------------------------------------------------------------
    # Client startup
    # ------------------------------------------------------------------

    async def start_client(self):
        """Start the Telegram client and handle authentication."""
        await self.client.start(bot_token=self.bot_token if self.bot_token else None)

        if not self.bot_token:
            # User authentication
            if not await self.client.is_user_authorized():
                phone = input("Enter your phone number: ")
                await self.client.send_code_request(phone)
                code = input("Enter the code you received: ")

                try:
                    await self.client.sign_in(phone, code)
                except SessionPasswordNeededError:
                    password = input("Enter your 2FA password: ")
                    await self.client.sign_in(password=password)

        logger.info("Client started successfully")

    # ------------------------------------------------------------------
    # Entity info helper
    # ------------------------------------------------------------------

    async def get_entity_info(self, entity_id):
        """Get a human-readable description of an entity."""
        try:
            entity = await self.client.get_entity(entity_id)
            if hasattr(entity, 'title'):
                return f"{entity.title} (ID: {entity_id})"
            elif hasattr(entity, 'first_name'):
                name = entity.first_name
                if hasattr(entity, 'last_name') and entity.last_name:
                    name += f" {entity.last_name}"
                return f"{name} (ID: {entity_id})"
            else:
                return f"Entity (ID: {entity_id})"
        except Exception as e:
            logger.error(f"Error getting entity info for {entity_id}: {e}")
            return f"Unknown Entity (ID: {entity_id})"

    # ------------------------------------------------------------------
    # Core forwarding logic
    # ------------------------------------------------------------------

    def _make_send_coro(self, target_id, message):
        """Return a zero-argument callable that sends *message* to *target_id*."""
        return lambda: self.client.send_message(
            entity=target_id,
            message=message.message or '',
            file=message.media,
            parse_mode='html' if message.entities else None,
        )

    def _make_forward_coro(self, target_id, message, source_id):
        """Return a zero-argument callable that forwards *message* to *target_id*."""
        return lambda: self.client.forward_messages(
            entity=target_id,
            messages=message.id,
            from_peer=source_id,
        )

    async def _forward_message(self, message, source_id, target_ids):
        """Forward a single message to all configured targets with FloodWait protection."""
        for target_id in target_ids:
            try:
                target_info = await self.get_entity_info(target_id)

                if self.remove_forward_signature:
                    # Send as a new message without "Forwarded from …" header
                    await with_flood_wait(self._make_send_coro(target_id, message))
                    logger.info(
                        f"Successfully sent message (without forward signature) to {target_info}"
                    )
                else:
                    # Forward with the original "Forwarded from …" header
                    await with_flood_wait(
                        self._make_forward_coro(target_id, message, source_id)
                    )
                    logger.info(f"Successfully forwarded message to {target_info}")

            except FloodWaitError:
                logger.error(
                    f"FloodWait max retries reached for target {target_id}, "
                    f"skipping message {message.id}"
                )
            except Exception as e:
                target_info = await self.get_entity_info(target_id)
                logger.error(f"Error forwarding to {target_info}: {e}")

        self._update_state(source_id, message.id)

    # ------------------------------------------------------------------
    # Catchup
    # ------------------------------------------------------------------

    async def _catchup_source(self, source_id, target_ids):
        """Forward messages that arrived since the last known message ID.

        If no prior state exists, performs an initial catchup: fetching the
        last ``catchup_limit`` messages (or the full history when
        ``catchup_limit == 0``) and forwarding them in chronological order.
        """
        key = str(source_id)
        last_id = self.state.get(key)
        source_info = await self.get_entity_info(source_id)

        if last_id is None:
            limit = self.catchup_limit if self.catchup_limit > 0 else None
            limit_desc = str(self.catchup_limit) if self.catchup_limit > 0 else "unlimited"
            logger.info(
                f"No previous state for source {source_info}; "
                f"performing initial catchup (limit={limit_desc})…"
            )

            count = 0
            if limit is None:
                # No limit: stream from oldest to newest directly to avoid
                # loading the entire history into memory.
                async for message in self.client.iter_messages(
                    source_id, reverse=True
                ):
                    if not message.message and not message.media:
                        continue
                    await self._forward_message(message, source_id, target_ids)
                    count += 1
                    if count % 10 == 0:
                        logger.info(
                            f"Initial catchup progress for {source_info}: {count} messages forwarded"
                        )
                    await asyncio.sleep(CATCHUP_DELAY)
            else:
                # Limited: collect the newest N messages then forward in
                # chronological order (oldest first).
                messages = []
                async for message in self.client.iter_messages(source_id, limit=limit):
                    if not message.message and not message.media:
                        continue
                    messages.append(message)

                messages.reverse()

                for message in messages:
                    await self._forward_message(message, source_id, target_ids)
                    count += 1
                    if count % 10 == 0:
                        logger.info(
                            f"Initial catchup progress for {source_info}: {count} messages forwarded"
                        )
                    await asyncio.sleep(CATCHUP_DELAY)

            logger.info(
                f"Initial catchup complete for {source_info}: {count} messages forwarded"
            )
            return

        logger.info(
            f"Incremental catchup after last_id={last_id} for {source_info}…"
        )

        count = 0
        async for message in self.client.iter_messages(
            source_id, min_id=last_id, reverse=True
        ):
            if not message.message and not message.media:
                continue
            await self._forward_message(message, source_id, target_ids)
            count += 1
            if count % 10 == 0:
                logger.info(f"Catchup progress for {source_info}: {count} messages forwarded")
            await asyncio.sleep(CATCHUP_DELAY)

        logger.info(
            f"Catchup complete for {source_info}: {count} missed messages forwarded"
        )

    # ------------------------------------------------------------------
    # Setup & run
    # ------------------------------------------------------------------

    async def setup_forwarding(self):
        """Set up message forwarding from multiple sources to their respective targets."""
        # Resolve 'me' to the actual numeric user ID now that the client is connected
        await self._resolve_entities()

        # Log all active rules
        logger.info("Setting up forwarding rules:")
        for source_id, target_ids in self.forwarding_map.items():
            source_info = await self.get_entity_info(source_id)
            target_infos = [await self.get_entity_info(t) for t in target_ids]
            logger.info(f"  {source_info} -> {', '.join(target_infos)}")

        # Replay missed messages before registering the live handler
        if self.catchup:
            logger.info("Starting catchup mode…")
            for source_id, target_ids in self.forwarding_map.items():
                await self._catchup_source(source_id, target_ids)
            logger.info("Catchup complete. Switching to live forwarding.")

        # Register live handler
        source_ids = list(self.forwarding_map.keys())

        @self.client.on(events.NewMessage(chats=source_ids))
        async def forward_handler(event):
            """Handle new messages and forward them to configured targets."""
            try:
                message = event.message
                source_id = event.chat_id
                sender_id = message.sender_id if message.sender_id else "Unknown"

                target_ids = self.forwarding_map.get(source_id, [])
                if not target_ids:
                    logger.warning(f"No targets configured for source {source_id}")
                    return

                source_info = await self.get_entity_info(source_id)
                logger.info(f"Received message from {sender_id} in {source_info}")

                await self._forward_message(message, source_id, target_ids)

            except Exception as e:
                logger.error(f"Error in forward handler: {e}")

        logger.info("Message forwarding handlers registered successfully")

    async def run(self):
        """Main method to run the forwarder."""
        try:
            await self.start_client()
            await self.setup_forwarding()

            logger.info("Telegram forwarder is now running. Press Ctrl+C to stop.")
            await self.client.run_until_disconnected()

        except KeyboardInterrupt:
            logger.info("Received interrupt signal. Stopping...")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            await self.client.disconnect()
            logger.info("Client disconnected")


async def main():
    """Main function to run the application."""
    parser = argparse.ArgumentParser(description='Telegram Message Forwarder')
    parser.add_argument(
        '--remove-forward-signature', '-r', action='store_true',
        help='Remove "Forward from…" signature by sending as new messages instead of forwarding',
    )
    parser.add_argument(
        '--disable-console-log', '-q', action='store_true',
        help='Disable console logging (only log to file)',
    )
    parser.add_argument(
        '--catchup', action='store_true',
        help=(
            'Forward messages missed since the last run before starting live '
            'forwarding. If no prior state exists, performs an initial catchup '
            'controlled by --catchup-limit.'
        ),
    )
    parser.add_argument(
        '--catchup-limit', type=int, default=0, metavar='N',
        help=(
            'Maximum number of messages to fetch during an initial catchup '
            '(when no prior state exists). '
            '0 = no limit (fetch full history). '
            'N > 0 = fetch only the last N messages (default: 0).'
        ),
    )
    parser.add_argument(
        '--state-file', default='forwarder_state.json', metavar='FILE',
        help=(
            'Path to the JSON file used to persist the last processed message '
            'ID per source (default: forwarder_state.json)'
        ),
    )
    parser.add_argument(
        '--reset-state', action='store_true',
        help='Delete the state file before starting so all positions are forgotten',
    )

    args = parser.parse_args()

    # Setup logging based on arguments
    setup_logging(disable_console=args.disable_console_log)

    try:
        forwarder = TelegramForwarder(
            remove_forward_signature=args.remove_forward_signature,
            catchup=args.catchup,
            catchup_limit=args.catchup_limit,
            state_file=args.state_file,
            reset_state=args.reset_state,
        )
        await forwarder.run()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        print("\nPlease check your .env file and ensure all required variables are set.")
        print("You can use .env.example as a template.")
    except Exception as e:
        logger.error(f"Application error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
