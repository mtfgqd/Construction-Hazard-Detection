from __future__ import annotations

import asyncio
import os
from io import BytesIO
from typing import TypedDict

import numpy as np
from dotenv import load_dotenv
from PIL import Image
from telegram import Bot
from telegram import Message


class InputData(TypedDict):
    """
    Structure of input data for sending a Telegram notification.
    """
    chat_id: str
    message: str
    image: np.ndarray


class TelegramResponse(TypedDict):
    """
    Structure of the response from Telegram API.
    """
    message_id: int
    chat_id: int
    date: int
    text: str


class TelegramNotifier:
    """
    A class to handle sending notifications through Telegram.
    """

    def __init__(self):
        """
        Initialises the TelegramNotifier.
        """
        load_dotenv()

    async def send_notification(
        self,
        chat_id: str,
        message: str,
        image: np.ndarray | None = None,
        bot_token: str | None = None,
    ) -> Message:
        """
        Sends a notification to a specified Telegram chat.

        Args:
            chat_id (str): The chat ID where the notification will be sent.
            message (str): The text message to send.
            image (np.ndarray): An optional image in NumPy array (RGB format).
            bot_token (str, optional): The Telegram bot token. If not provided,
                attempts to read from environment variables.

        Returns:
            Message: The response object from Telegram API.

        Raises:
            ValueError: If 'TELEGRAM_BOT_TOKEN' is missing.
        """
        bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        if not bot_token:
            raise ValueError('Telegram bot token must be provided')
        bot = Bot(token=bot_token)

        if image is not None:
            # Convert NumPy array to PIL Image
            image_pil = Image.fromarray(image)
            buffer = BytesIO()
            # Save image to BytesIO buffer as PNG
            image_pil.save(buffer, format='PNG')
            buffer.seek(0)
            # Send photo with caption
            response = await bot.send_photo(
                chat_id=chat_id,
                photo=buffer,
                caption=message,
            )
        else:
            # Send text message
            response = await bot.send_message(
                chat_id=chat_id,
                text=message,
            )
        return response


# Example usage
async def main():
    notifier = TelegramNotifier()
    chat_id = 'your_chat_id_here'
    message = 'Hello, Telegram!'
    image = np.zeros((100, 100, 3), dtype=np.uint8)  # Example image (black)
    bot_token = 'your_bot_token_here'
    response = await notifier.send_notification(
        chat_id, message, image=image, bot_token=bot_token,
    )
    print(response)


if __name__ == '__main__':
    asyncio.run(main())
