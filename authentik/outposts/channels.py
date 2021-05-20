"""Outpost websocket handler"""
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Optional

from channels.exceptions import DenyConnection
from dacite import from_dict
from dacite.data import Data
from guardian.shortcuts import get_objects_for_user
from structlog.stdlib import get_logger

from authentik.core.channels import AuthJsonConsumer
from authentik.outposts.models import OUTPOST_HELLO_INTERVAL, Outpost, OutpostState

LOGGER = get_logger()


class WebsocketMessageInstruction(IntEnum):
    """Commands which can be triggered over Websocket"""

    # Simple message used by either side when a message is acknowledged
    ACK = 0

    # Message used by outposts to report their alive status
    HELLO = 1

    # Message sent by us to trigger an Update
    TRIGGER_UPDATE = 2


@dataclass
class WebsocketMessage:
    """Complete Websocket Message that is being sent"""

    instruction: int
    args: dict[str, Any] = field(default_factory=dict)


class OutpostConsumer(AuthJsonConsumer):
    """Handler for Outposts that connect over websockets for health checks and live updates"""

    outpost: Outpost

    last_uid: Optional[str] = None

    def connect(self):
        super().connect()
        uuid = self.scope["url_route"]["kwargs"]["pk"]
        outpost = get_objects_for_user(
            self.user, "authentik_outposts.view_outpost"
        ).filter(pk=uuid)
        if not outpost.exists():
            raise DenyConnection()
        self.accept()
        self.outpost = outpost.first()
        self.last_uid = self.channel_name
        LOGGER.debug(
            "added outpost instace to cache",
            outpost=self.outpost,
            channel_name=self.channel_name,
        )

    # pylint: disable=unused-argument
    def disconnect(self, close_code):
        if self.outpost and self.last_uid:
            state = OutpostState.for_instance_uid(self.outpost, self.last_uid)
            if self.channel_name in state.channel_ids:
                state.channel_ids.remove(self.channel_name)
                state.save()
        LOGGER.debug(
            "removed outpost instance from cache",
            outpost=self.outpost,
            instance_uuid=self.last_uid,
        )

    def receive_json(self, content: Data):
        msg = from_dict(WebsocketMessage, content)
        uid = msg.args.get("uuid", self.channel_name)
        self.last_uid = uid
        state = OutpostState.for_instance_uid(self.outpost, uid)
        if self.channel_name not in state.channel_ids:
            state.channel_ids.append(self.channel_name)
        state.last_seen = datetime.now()
        if msg.instruction == WebsocketMessageInstruction.HELLO:
            state.version = msg.args.get("version", None)
            state.build_hash = msg.args.get("buildHash", "")
        elif msg.instruction == WebsocketMessageInstruction.ACK:
            return
        state.save(timeout=OUTPOST_HELLO_INTERVAL * 1.5)

        response = WebsocketMessage(instruction=WebsocketMessageInstruction.ACK)
        self.send_json(asdict(response))

    # pylint: disable=unused-argument
    def event_update(self, event):
        """Event handler which is called by post_save signals, Send update instruction"""
        self.send_json(
            asdict(
                WebsocketMessage(instruction=WebsocketMessageInstruction.TRIGGER_UPDATE)
            )
        )
