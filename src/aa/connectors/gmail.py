"""Gmail (Resilio) connector using Google OAuth 2.0."""
from __future__ import annotations

import base64
import os
import re

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from aa.connectors.base import BaseConnector

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]


class GmailConnector(BaseConnector):
    """Connector for Gmail via the Google API (Resilio source)."""

    source_name = "resilio"

    def __init__(self, credentials_path: str, token_path: str) -> None:
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None

    async def authenticate(self) -> None:
        """Authenticate using Google OAuth 2.0, storing/refreshing tokens."""
        creds: Credentials | None = None

        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)

            with open(self.token_path, "w") as token_file:
                token_file.write(creds.to_json())

        self.service = build("gmail", "v1", credentials=creds)

    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        """Fetch unread messages via Gmail API.

        Args:
            cursor: Optional page token for pagination.

        Returns:
            Tuple of (list of item dicts, next page token or None).
        """
        kwargs: dict = {
            "userId": "me",
            "q": "is:unread",
            "maxResults": 50,
        }
        if cursor:
            kwargs["pageToken"] = cursor

        response = self.service.users().messages().list(**kwargs).execute()
        messages = response.get("messages", [])
        next_cursor = response.get("nextPageToken")

        items: list[dict] = []
        for msg_ref in messages:
            msg = (
                self.service.users()
                .messages()
                .get(userId="me", id=msg_ref["id"], format="full")
                .execute()
            )
            items.append(self._parse_message(msg))

        return items, next_cursor

    def _parse_message(self, msg: dict) -> dict:
        """Parse a Gmail API message into our standard item dict format."""
        headers = {
            h["name"]: h["value"] for h in msg["payload"].get("headers", [])
        }
        from_name, from_address = self._parse_from(headers.get("From", ""))
        body = self._extract_body(msg["payload"])

        return {
            "id": f"resilio-{msg['id']}",
            "source": "resilio",
            "source_id": msg["id"],
            "type": "email",
            "from_name": from_name,
            "from_address": from_address,
            "subject": headers.get("Subject", ""),
            "body": body,
            "timestamp": msg.get("internalDate", ""),
        }

    def _parse_from(self, from_header: str) -> tuple[str, str]:
        """Extract name and email from 'Name <email>' format.

        Returns:
            Tuple of (name, email).
        """
        match = re.match(r'^"?([^"<]*?)"?\s*<([^>]+)>$', from_header.strip())
        if match:
            name = match.group(1).strip()
            email = match.group(2).strip()
            return name, email
        # Bare email address
        return "", from_header.strip()

    def _extract_body(self, payload: dict) -> str:
        """Extract text/plain body from payload, handling multipart."""
        mime_type = payload.get("mimeType", "")

        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8")
            return ""

        if mime_type.startswith("multipart/"):
            for part in payload.get("parts", []):
                result = self._extract_body(part)
                if result:
                    return result

        return ""
